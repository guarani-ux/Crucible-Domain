#!/usr/bin/env python3
"""In-RAM capability index, selective router, and closed-loop doctor for Crucible Domain."""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import re
import subprocess
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

DEFAULT_GLOBAL_CONFIG_DIR = Path.home() / ".gemini" / "config"

STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "at",
        "be",
        "by",
        "can",
        "do",
        "for",
        "from",
        "how",
        "i",
        "in",
        "into",
        "is",
        "it",
        "my",
        "need",
        "of",
        "on",
        "or",
        "should",
        "that",
        "the",
        "this",
        "to",
        "use",
        "what",
        "when",
        "where",
        "which",
        "who",
        "with",
        "write",
    }
)

ROLE_CARD_CODES = (
    "COM-D",
    "COM-M",
    "COM-S",
    "MKT-D",
    "MKT-M",
    "MKT-S",
    "CNT-D",
    "CNT-M",
    "CNT-S",
    "PROD-D",
    "PROD-M",
    "PROD-S",
)

# Host-agnostic mapping from legacy ChatGPT skill IDs to canonical local IDs.
CHATGPT_SKILL_BINDINGS: dict[str, dict[str, Any]] = {
    "6a88759040a88191a896614be5d93a01": {
        "label": "Shape media brief",
        "targets": ["MW-01", "OP-01"],
    },
    "6ad142fb15388191a1634e7da79674dc": {
        "label": "Write video concept",
        "targets": ["MW-02", "MP-01"],
    },
    "6a8875c54d3c81919a7f6de589f82d02": {
        "label": "Write A/V script",
        "targets": ["MW-04"],
        "host_skills": ["av-craft"],
    },
    "6a8875e68af88191940f923dd303141b": {
        "label": "Plan media production",
        "targets": ["MP-01", "MP-02", "MP-03", "MP-04"],
    },
    "6af01c95eb148191b50f2ee390de4170": {
        "label": "Prepare media workback",
        "targets": ["OP-03"],
    },
    "6a8875fd6f8c81918cd0bd3934e74711": {
        "label": "Audit media release",
        "targets": ["MP-10", "MP-11", "CH-03", "CH-04"],
    },
    "6acfae059d5881918e34ff0b0a55f8b6": {
        "label": "Investigate with evidence",
        "targets": ["CD-01", "MK-02"],
    },
    "6add61269f9081919a9eb9e24f7aae64": {
        "label": "Recover working practice",
        "targets": ["OP-08", "ig-discover-method"],
    },
    "6add61c97c0c8191bc6cb4f84a1f3312": {
        "label": "Trial practice in use",
        "targets": ["OP-08", "ig-improve"],
    },
    "6afa4e6d26a08191bd80f1926eddb3bc": {
        "label": "Create Work Graphs",
        "targets": ["WOS-GRAPH", "K-GRAPH-01"],
    },
}

CORE_ENTRY_DOCS: dict[str, tuple[str, str, str]] = {
    "WOS-GRAPH": (
        "Work Operating System Graph Catalog (7 Graph Types)",
        "Project/Work Operating System/Work_Operating_System_Graph_Catalog.md",
        "Choose a graph type (capability, process, decision, dependency, trace, outcome, target architecture) with Mermaid examples.",
    ),
    "WOS-README": (
        "Work Operating System Entry Point",
        "Project/Work Operating System/README.md",
        "Plan, delegate, execute, and review digital work across roles and forks.",
    ),
    "MA-ROUTING": (
        "Media Work Routing",
        "Knowledge/Media Agency/Media_Work_Routing.md",
        "Choose responsible Media Agency discipline, level, and method by incoming work object.",
    ),
    "MA-SKILLS": (
        "Media Agency Skills and Workflows Catalogue",
        "Knowledge/Media Agency/Skills and Workflows/README.md",
        "Lookup index of all 55 Media Agency procedures across writing, production, campaigns, comms, channel, and portfolio.",
    ),
    "IG-README": (
        "Inner Gravity Harness Self-Model",
        "Project/Inner Gravity/README.md",
        "Seven-graph map, install_pack specs, and verification evidence for Antigravity inside Crucible Domain.",
    ),
    "TEST-PHIL": (
        "Testing Philosophy & 4 Evidence Rungs",
        "Knowledge/Testing_Philosophy.md",
        "Four Evidence Rungs, 3 Non-Negotiable Test Laws, red-first/mutation kills, and Rung-3 planted-defect evals (K-TEST-01).",
    ),
}

CANONICAL_LOCAL_FIRST_FILES = (
    "README.md",
    "Knowledge/Media Agency/Skills and Workflows/README.md",
    "Knowledge/Media Agency/Media_Work_Routing.md",
    "Knowledge/Knowledge_Register.md",
    "Knowledge/Testing_Philosophy.md",
    "Calgary Public Library/GROUND_TRUTH.md",
    "Project/Project_Register.md",
    "Archive/README.md",
)

PROC_HEADING_RE = re.compile(r"^#{1,4}\s+((?:MW|MP|MK|CD|CH|OP)-\d+)\b[:\s·—-]*(.*)$")
TABLE_ROW_RE = re.compile(r"^\|\s*([KPAC]-\S+?)\s*\|\s*(.*)$")
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---", re.DOTALL)
MD_LINK_RE = re.compile(r"\[([^\]]*)\]\(([^)]+)\)")
BARE_URL_RE = re.compile(r"https?://[^\s)>\"'`]+")
TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9_-]*")


@dataclass(frozen=True)
class CapabilityEntry:
    """Single indexed local capability, role, knowledge lesson, project, exhibit, or skill."""

    id: str
    kind: str  # procedure | role | knowledge | project | exhibit | doc | skill
    title: str
    path: str
    line: int = 1
    domain: str = ""
    summary: str = ""
    use_when: str = ""
    related_ids: tuple[str, ...] = ()
    reachability: str = "local"  # local | slash_only | host_global


@dataclass(frozen=True)
class BindingStatus:
    """Resolved status for one external ChatGPT skill ID."""

    skill_id: str
    label: str
    target_ids: tuple[str, ...]
    resolved_paths: tuple[str, ...]
    missing_targets: tuple[str, ...]

    @property
    def ok(self) -> bool:
        return bool(self.target_ids) and not self.missing_targets


@dataclass
class CapabilityIndex:
    """In-memory index of all reachable Crucible Domain capabilities and bindings."""

    root: Path
    entries: dict[str, CapabilityEntry]
    alias_map: dict[str, str]
    chatgpt_bindings: dict[str, BindingStatus]
    skill_frontmatter_bytes: int
    build_ms: float
    counts_by_kind: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class RouteMatch:
    """One ranked match from route_query."""

    entry: CapabilityEntry
    score: float
    matched_via: str


@dataclass(frozen=True)
class RouteResult:
    """Result returned by route_query with explicit abstention signal."""

    query: str
    match_mode: str  # exact | chatgpt_binding | lexical | abstained
    abstained: bool
    reason: str
    matches: list[RouteMatch]

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "match_mode": self.match_mode,
            "abstained": self.abstained,
            "reason": self.reason,
            "matches": [
                {
                    "id": m.entry.id,
                    "kind": m.entry.kind,
                    "title": m.entry.title,
                    "path": m.entry.path,
                    "line": m.entry.line,
                    "reachability": m.entry.reachability,
                    "score": round(m.score, 3),
                    "matched_via": m.matched_via,
                    "summary": m.entry.summary,
                    "related_ids": list(m.entry.related_ids),
                }
                for m in self.matches
            ],
        }


@dataclass(frozen=True)
class DiagnosticFinding:
    """Single closed-loop verification finding from run_doctor."""

    category: str
    severity: str  # PASS | WARN | FAIL
    subject: str
    detail: str
    remediation: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DoctorReport:
    """Full workspace + host reachability health report."""

    root: str
    findings: list[DiagnosticFinding]
    metrics: dict[str, Any]

    @property
    def fail_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "FAIL")

    @property
    def warn_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "WARN")

    @property
    def pass_count(self) -> int:
        return sum(1 for f in self.findings if f.severity == "PASS")

    @property
    def ok(self) -> bool:
        return self.fail_count == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "ok": self.ok,
            "summary": {
                "pass": self.pass_count,
                "warn": self.warn_count,
                "fail": self.fail_count,
            },
            "metrics": self.metrics,
            "findings": [f.to_dict() for f in self.findings],
        }


def _strip_md(text: str) -> str:
    """Collapse Markdown links and emphasis into clean plain text."""
    cleaned = MD_LINK_RE.sub(lambda m: m.group(1), text)
    cleaned = re.sub(r"[*_`]+", "", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _parse_frontmatter(text: str) -> tuple[dict[str, str], int]:
    """Extract simple scalar fields and raw byte length from YAML frontmatter without PyYAML."""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, 0
    block = m.group(1)
    fields: dict[str, str] = {}
    current_key: str | None = None
    for raw_line in block.splitlines():
        if not raw_line.strip():
            continue
        kv = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", raw_line)
        if kv:
            current_key = kv.group(1).strip()
            val = kv.group(2).strip().strip("'\"")
            fields[current_key] = "" if val in (">-", ">", "|", "|-") else val
        elif current_key and raw_line.startswith((" ", "\t")):
            joined = (fields[current_key] + " " + raw_line.strip()).strip()
            fields[current_key] = joined
    return fields, len(block.encode("utf-8"))


def _add_entry(entries: dict[str, CapabilityEntry], alias_map: dict[str, str], entry: CapabilityEntry) -> None:
    entries[entry.id] = entry
    alias_map[entry.id.lower()] = entry.id


def _index_procedures(root: Path, entries: dict[str, CapabilityEntry], alias_map: dict[str, str]) -> None:
    sw_dir = root / "Knowledge" / "Media Agency" / "Skills and Workflows"
    if not sw_dir.is_dir():
        return
    for md_file in sorted(sw_dir.glob("*.md")):
        if md_file.name.lower() == "readme.md":
            continue
        lines = md_file.read_text(encoding="utf-8", errors="replace").splitlines()
        rel = str(md_file.relative_to(root)).replace("\\", "/")
        headings: list[tuple[int, str, str]] = []
        for idx, line in enumerate(lines, 1):
            m = PROC_HEADING_RE.match(line.strip())
            if m:
                headings.append((idx, m.group(1).upper(), m.group(2).strip()))
        for pos, (start_ln, proc_id, raw_title) in enumerate(headings):
            end_ln = headings[pos + 1][0] - 1 if pos + 1 < len(headings) else len(lines)
            body_lines = [ln.strip() for ln in lines[start_ln:end_ln] if ln.strip() and not ln.strip().startswith("|---")]
            summary = _strip_md(" ".join(body_lines[:3]))[:320]
            related = tuple(sorted(set(re.findall(r"\b(?:MW|MP|MK|CD|CH|OP)-\d+\b", " ".join(body_lines)))))
            _add_entry(
                entries,
                alias_map,
                CapabilityEntry(
                    id=proc_id,
                    kind="procedure",
                    title=_strip_md(raw_title) or proc_id,
                    path=rel,
                    line=start_ln,
                    domain=md_file.stem,
                    summary=summary,
                    use_when=_strip_md(" ".join(body_lines[:2]))[:220],
                    related_ids=related,
                    reachability="local",
                ),
            )


def _index_roles(root: Path, entries: dict[str, CapabilityEntry], alias_map: dict[str, str]) -> None:
    ma_dir = root / "Knowledge" / "Media Agency"
    if not ma_dir.is_dir():
        return
    for code in ROLE_CARD_CODES:
        role_path = ma_dir / f"{code}.md"
        if not role_path.is_file():
            continue
        lines = role_path.read_text(encoding="utf-8", errors="replace").splitlines()
        title = code
        for line in lines:
            if line.strip().startswith("# "):
                title = _strip_md(line.strip()[2:])
                break
        body = "\n".join(lines[:12])
        related = tuple(sorted(set(re.findall(r"\b(?:MW|MP|MK|CD|CH|OP)-\d+\b", "\n".join(lines)))))
        summary_lines = [ln.strip() for ln in lines[1:10] if ln.strip() and not ln.strip().startswith("#")]
        _add_entry(
            entries,
            alias_map,
            CapabilityEntry(
                id=code,
                kind="role",
                title=title,
                path=str(role_path.relative_to(root)).replace("\\", "/"),
                line=1,
                domain="media-agency-role",
                summary=_strip_md(" ".join(summary_lines[:2]))[:300],
                use_when=_strip_md(body)[:200],
                related_ids=related,
                reachability="local",
            ),
        )


def _index_markdown_table(
    md_file: Path,
    root: Path,
    kind: str,
    entries: dict[str, CapabilityEntry],
    alias_map: dict[str, str],
) -> None:
    if not md_file.is_file():
        return
    rel = str(md_file.relative_to(root)).replace("\\", "/")
    for ln, raw in enumerate(md_file.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        m = TABLE_ROW_RE.match(raw.strip())
        if not m:
            continue
        rec_id = m.group(1).strip()
        cells = [_strip_md(c) for c in m.group(2).split("|") if c.strip()]
        if not cells or rec_id.upper() in ("ID", "---"):
            continue
        title = cells[0][:140]
        use_when = cells[1][:220] if len(cells) > 1 else ""
        summary = " · ".join(cells[:3])[:320]
        _add_entry(
            entries,
            alias_map,
            CapabilityEntry(
                id=rec_id,
                kind=kind,
                title=title,
                path=rel,
                line=ln,
                domain=kind,
                summary=summary,
                use_when=use_when,
                reachability="local",
            ),
        )


def _index_exhibits(root: Path, entries: dict[str, CapabilityEntry], alias_map: dict[str, str]) -> None:
    arch_dir = root / "Knowledge" / "Repository Archaeology"
    if not arch_dir.is_dir():
        return
    for md_file in sorted(arch_dir.glob("[0-9][0-9]-*.md")):
        if md_file.name.startswith("00-"):
            continue
        num_match = re.match(r"^(\d{2})-(.+)\.md$", md_file.name)
        if not num_match:
            continue
        exhibit_id = f"A{num_match.group(1)}"
        lines = md_file.read_text(encoding="utf-8", errors="replace").splitlines()
        title = num_match.group(2)
        for line in lines:
            if line.strip().startswith("# "):
                title = _strip_md(line.strip()[2:])
                break
        summary = _strip_md(" ".join(ln.strip() for ln in lines[1:8] if ln.strip()))[:300]
        _add_entry(
            entries,
            alias_map,
            CapabilityEntry(
                id=exhibit_id,
                kind="exhibit",
                title=title,
                path=str(md_file.relative_to(root)).replace("\\", "/"),
                line=1,
                domain="archaeology",
                summary=summary,
                reachability="local",
            ),
        )


def _index_core_docs(root: Path, entries: dict[str, CapabilityEntry], alias_map: dict[str, str]) -> None:
    for doc_id, (title, rel_path, summary) in CORE_ENTRY_DOCS.items():
        if (root / rel_path).is_file():
            _add_entry(
                entries,
                alias_map,
                CapabilityEntry(
                    id=doc_id,
                    kind="doc",
                    title=title,
                    path=rel_path,
                    line=1,
                    domain="core-doc",
                    summary=summary,
                    use_when=summary,
                    reachability="local",
                ),
            )


def _scan_skill_dir(
    skills_dir: Path,
    entries: dict[str, CapabilityEntry],
    alias_map: dict[str, str],
    reachability: str,
    include_only: set[str] | None = None,
) -> int:
    if not skills_dir.is_dir():
        return 0
    total_fm_bytes = 0
    for skill_file in sorted(skills_dir.glob("*/SKILL.md")):
        folder_name = skill_file.parent.name
        if include_only is not None and folder_name not in include_only:
            continue
        raw = skill_file.read_text(encoding="utf-8", errors="replace")
        fm, fm_bytes = _parse_frontmatter(raw)
        name = fm.get("name") or folder_name
        desc = fm.get("description") or ""
        slash_only = fm.get("disable-model-invocation", "").lower() == "true"
        skill_reach = "slash_only" if slash_only else reachability
        if not slash_only:
            total_fm_bytes += fm_bytes
        if name not in entries:
            _add_entry(
                entries,
                alias_map,
                CapabilityEntry(
                    id=name,
                    kind="skill",
                    title=name,
                    path=str(skill_file).replace("\\", "/"),
                    line=1,
                    domain="agent-skill",
                    summary=desc[:320],
                    use_when=desc[:220],
                    reachability=skill_reach,
                ),
            )
    return total_fm_bytes


def _index_skills(
    root: Path,
    global_config_dir: Path | None,
    entries: dict[str, CapabilityEntry],
    alias_map: dict[str, str],
) -> int:
    fm_bytes = 0
    ig_skills = root / ".agents" / "plugins" / "inner-gravity" / "skills"
    fm_bytes += _scan_skill_dir(ig_skills, entries, alias_map, reachability="local")
    if global_config_dir and global_config_dir.is_dir():
        fm_bytes += _scan_skill_dir(global_config_dir / "skills", entries, alias_map, reachability="host_global")
        skills_json = global_config_dir / "skills.json"
        if skills_json.is_file():
            try:
                cfg = json.loads(skills_json.read_text(encoding="utf-8"))
                for item in cfg.get("entries", []):
                    raw_path = item.get("path")
                    if not isinstance(raw_path, str):
                        continue
                    include = item.get("include_only")
                    inc_set = set(include) if isinstance(include, list) else None
                    fm_bytes += _scan_skill_dir(
                        Path(raw_path),
                        entries,
                        alias_map,
                        reachability="host_global",
                        include_only=inc_set,
                    )
            except (OSError, json.JSONDecodeError):
                pass
    return fm_bytes


def _resolve_chatgpt_bindings(root: Path, entries: dict[str, CapabilityEntry]) -> dict[str, BindingStatus]:
    resolved: dict[str, BindingStatus] = {}
    for skill_id, spec in CHATGPT_SKILL_BINDINGS.items():
        targets = tuple(spec["targets"])
        host_skills = tuple(spec.get("host_skills", ()))
        resolved_targets: list[str] = []
        paths: list[str] = []
        missing: list[str] = []
        for tid in targets:
            entry = entries.get(tid)
            if entry is None:
                missing.append(tid)
                continue
            full_path = Path(entry.path) if Path(entry.path).is_absolute() else (root / entry.path)
            if full_path.exists():
                resolved_targets.append(tid)
                paths.append(entry.path)
            else:
                missing.append(tid)
        for hskill in host_skills:
            entry = entries.get(hskill)
            if entry is not None and Path(entry.path).exists():
                resolved_targets.append(hskill)
                paths.append(entry.path)
        resolved[skill_id] = BindingStatus(
            skill_id=skill_id,
            label=spec["label"],
            target_ids=tuple(resolved_targets) if not missing else targets,
            resolved_paths=tuple(dict.fromkeys(paths)),
            missing_targets=tuple(missing),
        )
    return resolved


def build_index(
    root: Path,
    global_config_dir: Path | None = DEFAULT_GLOBAL_CONFIG_DIR,
) -> CapabilityIndex:
    """Parse live Crucible Domain docs and reachable skills directly into RAM."""
    t0 = time.perf_counter()
    root = root.resolve()
    entries: dict[str, CapabilityEntry] = {}
    alias_map: dict[str, str] = {}

    _index_procedures(root, entries, alias_map)
    _index_roles(root, entries, alias_map)
    _index_markdown_table(root / "Knowledge" / "Knowledge_Register.md", root, "knowledge", entries, alias_map)
    _index_markdown_table(root / "Project" / "Project_Register.md", root, "project", entries, alias_map)
    _index_exhibits(root, entries, alias_map)
    _index_core_docs(root, entries, alias_map)
    fm_bytes = _index_skills(root, global_config_dir, entries, alias_map)

    bindings = _resolve_chatgpt_bindings(root, entries)
    counts: dict[str, int] = {}
    for entry in entries.values():
        counts[entry.kind] = counts.get(entry.kind, 0) + 1

    elapsed_ms = (time.perf_counter() - t0) * 1000.0
    return CapabilityIndex(
        root=root,
        entries=entries,
        alias_map=alias_map,
        chatgpt_bindings=bindings,
        skill_frontmatter_bytes=fm_bytes,
        build_ms=elapsed_ms,
        counts_by_kind=counts,
    )


def _tokenize(text: str) -> list[str]:
    return [tok for tok in TOKEN_RE.findall(text.lower()) if tok not in STOPWORDS and len(tok) > 1]


def _extract_chatgpt_skill_id(query: str) -> str | None:
    q = query.strip()
    if q in CHATGPT_SKILL_BINDINGS:
        return q
    m = re.search(r"skill_id=([0-9a-f]{24,40})", q, re.IGNORECASE)
    return m.group(1).lower() if m else None


def route_query(
    index: CapabilityIndex,
    query: str,
    *,
    top_k: int = 5,
    min_score: float = 1.5,
) -> RouteResult:
    """Resolve an ID, ChatGPT skill_id, or natural-language task in RAM with selective abstention."""
    raw = query.strip()
    if not raw:
        return RouteResult(query=query, match_mode="abstained", abstained=True, reason="Empty query.", matches=[])

    # 1. ChatGPT skill_id or URL resolution
    cgpt_id = _extract_chatgpt_skill_id(raw)
    if cgpt_id is not None:
        binding = index.chatgpt_bindings.get(cgpt_id)
        if binding:
            matches = [
                RouteMatch(entry=index.entries[tid], score=100.0, matched_via=f"chatgpt_skill:{cgpt_id} ({binding.label})")
                for tid in binding.target_ids
                if tid in index.entries
            ]
            if matches:
                return RouteResult(
                    query=query,
                    match_mode="chatgpt_binding",
                    abstained=False,
                    reason=f"Bound ChatGPT skill '{binding.label}' ({cgpt_id}) to {len(matches)} local target(s).",
                    matches=matches,
                )

    # 2. Exact canonical ID / skill name lookup (O(1))
    norm_key = raw.lower()
    if norm_key in index.alias_map:
        canon_id = index.alias_map[norm_key]
        primary = index.entries[canon_id]
        matches = [RouteMatch(entry=primary, score=100.0, matched_via="exact_id")]
        for rel_id in primary.related_ids[: max(0, top_k - 1)]:
            if rel_id in index.entries:
                matches.append(RouteMatch(entry=index.entries[rel_id], score=10.0, matched_via=f"linked_from:{canon_id}"))
        return RouteResult(
            query=query,
            match_mode="exact",
            abstained=False,
            reason=f"Resolved canonical ID {canon_id}.",
            matches=matches,
        )

    # 3. BM25-weighted lexical scoring with field boosts
    q_tokens = _tokenize(raw)
    if not q_tokens:
        return RouteResult(
            query=query,
            match_mode="abstained",
            abstained=True,
            reason="Query had no domain-bearing tokens; act directly or inspect README.md.",
            matches=[],
        )

    doc_tokens_map: dict[str, tuple[set[str], set[str], set[str]]] = {}
    df: dict[str, int] = {}
    for eid, entry in index.entries.items():
        title_toks = set(_tokenize(f"{entry.id} {entry.title}"))
        use_toks = set(_tokenize(f"{entry.use_when} {entry.domain} {entry.kind}"))
        body_toks = set(_tokenize(entry.summary))
        doc_tokens_map[eid] = (title_toks, use_toks, body_toks)
        for tok in title_toks | use_toks | body_toks:
            df[tok] = df.get(tok, 0) + 1

    n_docs = max(1, len(index.entries))
    scored: list[RouteMatch] = []
    for eid, entry in index.entries.items():
        title_toks, use_toks, body_toks = doc_tokens_map[eid]
        score = 0.0
        hit_tokens: list[str] = []
        for qtok in set(q_tokens):
            idf = math.log(1.0 + (n_docs - df.get(qtok, 0) + 0.5) / (df.get(qtok, 0) + 0.5))
            weight = 0.0
            if qtok in title_toks:
                weight += 3.0
            if qtok in use_toks:
                weight += 2.0
            if qtok in body_toks:
                weight += 1.0
            if weight > 0:
                score += idf * min(weight, 4.0)
                hit_tokens.append(qtok)
        if score > 0 and entry.kind == "procedure" and len(hit_tokens) >= 2:
            score += 0.5
        if score >= min_score:
            scored.append(
                RouteMatch(
                    entry=entry,
                    score=score,
                    matched_via="tokens:" + ",".join(sorted(hit_tokens)),
                )
            )

    scored.sort(key=lambda m: (-m.score, m.entry.kind != "procedure", m.entry.id))
    top_matches = scored[:top_k]
    if not top_matches:
        return RouteResult(
            query=query,
            match_mode="abstained",
            abstained=True,
            reason=f"No capability reached confidence threshold ({min_score}); act directly without forcing a skill.",
            matches=[],
        )

    return RouteResult(
        query=query,
        match_mode="lexical",
        abstained=False,
        reason=f"Matched {len(top_matches)} local capability item(s) in {index.build_ms:.1f}ms.",
        matches=top_matches,
    )


def _extract_python_script_arg(cmd: str) -> str | None:
    m = re.search(r'\bpython(?:3)?(?:\.exe)?\s+(?:"([^"]+)"|(\S+))', cmd or "")
    if not m:
        return None
    return (m.group(1) or m.group(2)).strip()


def _probe_hook_command(cmd: str, cwd: Path, event_name: str) -> tuple[bool, str]:
    probe_payloads = {
        "SessionStart": json.dumps({"conversationId": "doctor-probe", "workspacePaths": [str(cwd)]}),
        "PreInvocation": json.dumps({"conversationId": "doctor-probe", "lastUserInput": "doctor health check"}),
        "Stop": json.dumps({"terminationReason": "USER_CANCELED", "executionNum": 0}),
    }
    if event_name not in probe_payloads:
        return True, "path exists (skipped live execution for tool hook)"
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        shell=True,
        input=probe_payloads[event_name],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=5,
        check=False,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:]
        detail = err[0] if err else f"exit {proc.returncode}"
        return False, f"exited {proc.returncode}: {detail}"
    out = proc.stdout.strip()
    if out:
        try:
            parsed = json.loads(out)
            if not isinstance(parsed, dict):
                return False, "hook stdout JSON is not an object"
        except json.JSONDecodeError as exc:
            return False, f"hook stdout is not valid JSON: {exc.msg}"
    return True, "executed cleanly from real cwd and emitted valid JSON"


def _audit_hooks(
    root: Path,
    global_config_dir: Path | None,
    execute_hooks: bool,
    findings: list[DiagnosticFinding],
) -> dict[str, int]:
    hook_files: list[Path] = [root / ".agents" / "hooks.json"]
    plugins_dir = root / ".agents" / "plugins"
    if plugins_dir.is_dir():
        hook_files.extend(sorted(plugins_dir.glob("*/hooks.json")))
    if global_config_dir and (global_config_dir / "hooks.json").is_file():
        hook_files.append(global_config_dir / "hooks.json")

    counts = {"checked": 0, "failed": 0, "disabled": 0}
    crucible_wired_events: set[str] = set()

    for hf in hook_files:
        if not hf.is_file():
            findings.append(
                DiagnosticFinding(
                    category="hooks",
                    severity="WARN",
                    subject=str(hf),
                    detail="hooks.json not found",
                )
            )
            continue
        try:
            data = json.loads(hf.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            findings.append(
                DiagnosticFinding(
                    category="hooks",
                    severity="FAIL",
                    subject=str(hf),
                    detail=f"invalid hooks.json: {exc}",
                )
            )
            counts["failed"] += 1
            continue

        hook_cwd = hf.parent
        rel_hf = str(hf.relative_to(root)).replace("\\", "/") if hf.is_relative_to(root) else str(hf)
        for hook_name, hook_cfg in data.items():
            if not isinstance(hook_cfg, dict):
                continue
            if hook_cfg.get("enabled", True) is False:
                counts["disabled"] += 1
                continue
            for ev in ("SessionStart", "PreInvocation", "PostInvocation", "PreToolUse", "PostToolUse", "Stop"):
                for entry in hook_cfg.get(ev) or []:
                    cmds = (
                        [h.get("command", "") for h in entry.get("hooks", [])]
                        if isinstance(entry, dict) and "hooks" in entry
                        else [entry.get("command", "") if isinstance(entry, dict) else ""]
                    )
                    for cmd in cmds:
                        counts["checked"] += 1
                        if hf == root / ".agents" / "hooks.json":
                            crucible_wired_events.add(ev)
                        script_arg = _extract_python_script_arg(cmd)
                        if script_arg is not None:
                            sp = Path(script_arg)
                            resolved = sp if sp.is_absolute() else (hook_cwd / sp).resolve()
                            if not resolved.is_file():
                                counts["failed"] += 1
                                findings.append(
                                    DiagnosticFinding(
                                        category="hooks",
                                        severity="FAIL",
                                        subject=f"{rel_hf}::{hook_name}.{ev}",
                                        detail=f"command '{cmd}' from cwd='{hook_cwd}' resolves to missing '{resolved}'",
                                        remediation="Apply Project/Inner Gravity/install_pack/crucible_hooks.json.fixed (use 'scripts/crucible_gate.py ...').",
                                    )
                                )
                                continue
                        if execute_hooks:
                            ok, msg = _probe_hook_command(cmd, hook_cwd, ev)
                            if not ok:
                                counts["failed"] += 1
                                findings.append(
                                    DiagnosticFinding(
                                        category="hooks",
                                        severity="FAIL",
                                        subject=f"{rel_hf}::{hook_name}.{ev}",
                                        detail=msg,
                                    )
                                )
                                continue
                        findings.append(
                            DiagnosticFinding(
                                category="hooks",
                                severity="PASS",
                                subject=f"{rel_hf}::{hook_name}.{ev}",
                                detail=f"ok from cwd='{hook_cwd}'",
                            )
                        )

    missing_events = {"SessionStart", "PreToolUse", "Stop"} - crucible_wired_events
    if missing_events:
        findings.append(
            DiagnosticFinding(
                category="hooks",
                severity="WARN",
                subject=".agents/hooks.json",
                detail=f"crucible_gate.py events not wired: {', '.join(sorted(missing_events))}",
                remediation="Run Project/Inner Gravity/install_pack/apply_protected_fixes.ps1 to wire SessionStart, PreToolUse, and Stop.",
            )
        )
    return counts


def _audit_links_and_bindings(root: Path, index: CapabilityIndex, findings: list[DiagnosticFinding]) -> dict[str, int]:
    chatgpt_bound = 0
    chatgpt_external = 0
    chatgpt_unbound = 0
    drive_total = 0

    if (root / "Knowledge").is_dir():
        for sid, bstatus in index.chatgpt_bindings.items():
            if not bstatus.ok:
                findings.append(
                    DiagnosticFinding(
                        category="bindings",
                        severity="FAIL",
                        subject=f"chatgpt_skill:{sid}",
                        detail=f"'{bstatus.label}' missing local target(s): {', '.join(bstatus.missing_targets)}",
                    )
                )

    for md_file in sorted(root.rglob("*.md")):
        if ".git" in md_file.parts:
            continue
        text = md_file.read_text(encoding="utf-8", errors="replace")
        rel = str(md_file.relative_to(root)).replace("\\", "/")

        for url in BARE_URL_RE.findall(text):
            if "drive.google.com" in url:
                drive_total += 1
            elif "chatgpt.com" in url or "chat.openai.com" in url:
                parsed = urlparse(url)
                qs = parse_qs(parsed.query)
                if parsed.path.startswith("/skills") and "skill_id" in qs:
                    sid = qs["skill_id"][0].lower()
                    bstatus = index.chatgpt_bindings.get(sid)
                    if bstatus and bstatus.ok:
                        chatgpt_bound += 1
                    else:
                        chatgpt_unbound += 1
                        findings.append(
                            DiagnosticFinding(
                                category="links",
                                severity="FAIL",
                                subject=rel,
                                detail=f"unbound ChatGPT skill URL: {url}",
                                remediation="Add local binding in CHATGPT_SKILL_BINDINGS or replace with local relative path.",
                            )
                        )
                else:
                    chatgpt_external += 1

        if rel in CANONICAL_LOCAL_FIRST_FILES:
            broken_local: list[str] = []
            for _, target in MD_LINK_RE.findall(text):
                if target.startswith(("http://", "https://", "mailto:", "#")):
                    continue
                target_path = (md_file.parent / unquote(target.split("#", 1)[0])).resolve()
                if not target_path.exists():
                    broken_local.append(target)
            if broken_local:
                findings.append(
                    DiagnosticFinding(
                        category="links",
                        severity="FAIL",
                        subject=rel,
                        detail=f"broken local Markdown links: {', '.join(broken_local)}",
                    )
                )
            else:
                findings.append(
                    DiagnosticFinding(
                        category="links",
                        severity="PASS",
                        subject=rel,
                        detail="all local relative Markdown links resolve on disk",
                    )
                )

    if chatgpt_unbound == 0:
        findings.append(
            DiagnosticFinding(
                category="bindings",
                severity="PASS",
                subject="chatgpt-skills",
                detail=f"all {chatgpt_bound} ChatGPT skill link occurrences map to verified local files ({chatgpt_external} receipt URL(s) marked external-only)",
            )
        )
    return {
        "chatgpt_bound": chatgpt_bound,
        "chatgpt_external_only": chatgpt_external,
        "chatgpt_unbound": chatgpt_unbound,
        "drive_links": drive_total,
    }


def _audit_duplicates_and_storage(
    root: Path,
    global_config_dir: Path | None,
    findings: list[DiagnosticFinding],
) -> dict[str, Any]:
    metrics: dict[str, Any] = {}

    # 1. Media Agency duplicate copy check
    k_ma = root / "Knowledge" / "Media Agency"
    p_ma = root / "Project" / "Media Agency"
    identical = 0
    diverged: list[str] = []
    if k_ma.is_dir() and p_ma.is_dir():
        for pf in sorted(p_ma.glob("*.md")):
            kf = k_ma / pf.name
            if not kf.is_file():
                continue
            kh = hashlib.sha256(kf.read_bytes()).hexdigest()
            ph = hashlib.sha256(pf.read_bytes()).hexdigest()
            if kh == ph:
                identical += 1
            else:
                diverged.append(pf.name)
    metrics["media_agency_identical"] = identical
    metrics["media_agency_diverged"] = len(diverged)
    if diverged:
        findings.append(
            DiagnosticFinding(
                category="duplicates",
                severity="WARN",
                subject="Project/Media Agency vs Knowledge/Media Agency",
                detail=f"{len(diverged)} duplicate file(s) diverged ({identical} identical), creating split-brain edits",
                remediation="Designate Knowledge/Media Agency as canonical and replace or archive the stale Project/Media Agency copy.",
            )
        )

    # 2. Drive lock dirs inside git working tree
    drive_locks = [name for name in (".tmp.drivedownload", ".tmp.driveupload") if (root / name).exists()]
    metrics["drive_sync_locks"] = drive_locks
    if drive_locks:
        findings.append(
            DiagnosticFinding(
                category="storage",
                severity="WARN",
                subject=",".join(drive_locks),
                detail="Drive sync temp folders present inside Git repo (Git + OneDrive + Drive concurrency risk)",
            )
        )

    # 3. Root governance files
    missing_root = [name for name in ("AGENTS.md", ".agents/acceptance.lock.json") if not (root / name).is_file()]
    metrics["missing_root_governance"] = missing_root
    if missing_root:
        if "AGENTS.md" in missing_root:
            rem = "Run Project/Inner Gravity/install_pack/apply_protected_fixes.ps1 to install AGENTS.md."
        else:
            rem = "Stage Operator Spec 2 from Project/Inner Gravity/README.md into .agents/acceptance.lock.json when ready to enforce required_files."
        findings.append(
            DiagnosticFinding(
                category="governance",
                severity="WARN",
                subject="root",
                detail=f"missing protected governance files: {', '.join(missing_root)}",
                remediation=rem,
            )
        )

    # 4. Global Antigravity config hygiene (read-only observations)
    if global_config_dir and global_config_dir.is_dir():
        is_git = (global_config_dir / ".git").exists()
        bak_files = [p.name for p in global_config_dir.iterdir() if p.is_file() and (".bak" in p.name or "backup" in p.name)]
        scripts_bak = [p.name for p in (global_config_dir / "scripts").glob("*.bak*") if (global_config_dir / "scripts").is_dir()]
        dead_js = (global_config_dir / "scripts" / "pre_tool_guard.js").is_file()

        dup_mcps: list[str] = []
        mcp_path = global_config_dir / "mcp_config.json"
        cfg_path = global_config_dir / "config.json"
        if mcp_path.is_file() and cfg_path.is_file():
            try:
                mcp_servers = set((json.loads(mcp_path.read_text(encoding="utf-8")).get("mcpServers") or {}).keys())
                plugins = json.loads(cfg_path.read_text(encoding="utf-8")).get("plugins") or {}
                enabled_plugins = {k for k, v in plugins.items() if isinstance(v, dict) and v.get("enabled", True)}
                dup_mcps = sorted(mcp_servers & enabled_plugins)
            except (OSError, json.JSONDecodeError):
                pass

        metrics["global_config_git"] = is_git
        metrics["global_bak_count"] = len(bak_files) + len(scripts_bak)
        metrics["global_dup_mcps"] = dup_mcps
        if not is_git or bak_files or scripts_bak or dead_js or dup_mcps:
            findings.append(
                DiagnosticFinding(
                    category="host_config",
                    severity="WARN",
                    subject=str(global_config_dir),
                    detail=(
                        f"git={is_git}, bak_files={len(bak_files) + len(scripts_bak)}, "
                        f"unreferenced_pre_tool_guard_js={dead_js}, duplicate_mcp_entries={dup_mcps}"
                    ),
                )
            )
    return metrics


def _audit_test_quality(
    root: Path,
    global_config_dir: Path | None,
    findings: list[DiagnosticFinding],
) -> dict[str, Any]:
    """Run AST test-quality checks (TQ-01..TQ-05) on workspace tests when gate is available."""
    if global_config_dir is None:
        return {"test_quality_violations": 0}
    tests_dir = root / ".agents" / "scripts" / "tests"
    if not tests_dir.is_dir():
        return {"test_quality_violations": 0}
    test_files = sorted(
        f for f in tests_dir.rglob("*.py") if f.name.startswith("test_") or f.name.endswith("_test.py")
    )
    if not test_files:
        return {"test_quality_violations": 0}

    tq_path = global_config_dir / "scripts" / "test_quality_gate.py"
    if not tq_path.is_file():
        tq_path = DEFAULT_GLOBAL_CONFIG_DIR / "scripts" / "test_quality_gate.py"
    if not tq_path.is_file():
        return {"test_quality_violations": 0}

    spec = importlib.util.spec_from_file_location("crucible_tq_gate", tq_path)
    if spec is None or spec.loader is None:
        return {"test_quality_violations": 0}
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)

    tq_findings = mod.audit_paths([tests_dir])
    if tq_findings:
        for item in tq_findings:
            try:
                rel = Path(item.file).resolve().relative_to(root).as_posix()
            except ValueError:
                rel = Path(item.file).name
            findings.append(
                DiagnosticFinding(
                    category="test_quality",
                    severity="FAIL",
                    subject=f"{rel}:{item.line}",
                    detail=f"[{item.rule_id}] {item.message}",
                )
            )
    else:
        findings.append(
            DiagnosticFinding(
                category="test_quality",
                severity="PASS",
                subject=".agents/scripts/tests",
                detail=f"all {len(test_files)} test file(s) satisfy TQ-01..TQ-05",
            )
        )
    return {"test_quality_violations": len(tq_findings)}


def run_doctor(
    root: Path,
    *,
    global_config_dir: Path | None = DEFAULT_GLOBAL_CONFIG_DIR,
    execute_hooks: bool = True,
) -> DoctorReport:
    """Run closed-loop verification over hooks, bindings, links, duplicates, and storage."""
    root = root.resolve()
    index = build_index(root, global_config_dir=global_config_dir)
    findings: list[DiagnosticFinding] = []

    hook_metrics = _audit_hooks(root, global_config_dir, execute_hooks, findings)
    link_metrics = _audit_links_and_bindings(root, index, findings)
    storage_metrics = _audit_duplicates_and_storage(root, global_config_dir, findings)
    tq_metrics = _audit_test_quality(root, global_config_dir, findings)

    metrics: dict[str, Any] = {
        "index_build_ms": round(index.build_ms, 2),
        "indexed_total": len(index.entries),
        "indexed_counts": index.counts_by_kind,
        "skill_frontmatter_bytes": index.skill_frontmatter_bytes,
        **hook_metrics,
        **link_metrics,
        **storage_metrics,
        **tq_metrics,
    }
    return DoctorReport(root=str(root), findings=findings, metrics=metrics)


def _format_route_text(result: RouteResult) -> str:
    if result.abstained:
        return f"ABSTAINED: {result.reason}"
    lines = [f"[{result.match_mode}] {result.reason}"]
    for idx, match in enumerate(result.matches, 1):
        e = match.entry
        loc = f"{e.path}:{e.line}" if e.line > 1 else e.path
        lines.append(f"{idx}. {e.id} ({e.kind}, {e.reachability}, score={match.score:.2f}) — {e.title}")
        lines.append(f"   Open: {loc}")
        if e.summary:
            lines.append(f"   Note: {e.summary[:180]}")
        if e.related_ids:
            lines.append(f"   Linked: {', '.join(e.related_ids[:8])}")
    return "\n".join(lines)


def _format_doctor_text(report: DoctorReport) -> str:
    m = report.metrics
    lines = [
        f"Crucible Doctor ({report.root})",
        (
            f"Index: {m['indexed_total']} capabilities in {m['index_build_ms']}ms "
            f"(procedures={m['indexed_counts'].get('procedure', 0)}, "
            f"roles={m['indexed_counts'].get('role', 0)}, "
            f"knowledge={m['indexed_counts'].get('knowledge', 0)}, "
            f"projects={m['indexed_counts'].get('project', 0)}, "
            f"exhibits={m['indexed_counts'].get('exhibit', 0)}, "
            f"skills={m['indexed_counts'].get('skill', 0)}, "
            f"skill_frontmatter={m['skill_frontmatter_bytes']}B)"
        ),
        f"Checks: {report.pass_count} PASS | {report.warn_count} WARN | {report.fail_count} FAIL",
        "",
    ]
    for f in report.findings:
        lines.append(f"[{f.severity}] {f.category} · {f.subject}: {f.detail}")
        if f.remediation:
            lines.append(f"       fix -> {f.remediation}")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Crucible Domain in-RAM index, router, and doctor.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_route = sub.add_parser("route", help="Resolve an ID or task query to local capabilities in RAM.")
    p_route.add_argument("query", nargs="+")
    p_route.add_argument("--top", type=int, default=5)
    p_route.add_argument("--json", action="store_true")
    p_route.add_argument("--no-global", action="store_true")

    p_doc = sub.add_parser("doctor", help="Audit hooks, bindings, links, duplicates, and storage.")
    p_doc.add_argument("--json", action="store_true")
    p_doc.add_argument("--no-global", action="store_true")
    p_doc.add_argument("--skip-exec", action="store_true")

    args = parser.parse_args(argv)
    global_dir = None if args.no_global else DEFAULT_GLOBAL_CONFIG_DIR

    if args.cmd == "route":
        idx = build_index(args.root, global_config_dir=global_dir)
        res = route_query(idx, " ".join(args.query), top_k=args.top)
        print(json.dumps(res.to_dict(), indent=2, ensure_ascii=False) if args.json else _format_route_text(res))
        return 0

    report = run_doctor(args.root, global_config_dir=global_dir, execute_hooks=not args.skip_exec)
    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False) if args.json else _format_doctor_text(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
