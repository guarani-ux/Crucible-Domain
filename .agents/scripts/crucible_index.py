#!/usr/bin/env python3
"""In-RAM capability index, selective router, and closed-loop doctor for Crucible Domain."""

from __future__ import annotations

import argparse
import hashlib
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
}

CANONICAL_LOCAL_FIRST_FILES = (
    "README.md",
    "Knowledge/Media Agency/Skills and Workflows/README.md",
    "Knowledge/Media Agency/Media_Work_Routing.md",
    "Knowledge/Knowledge_Register.md",
)

EXHIBIT_LESSON_LINKS: dict[str, tuple[str, ...]] = {
    "A02": ("K-ARCH-03",),
    "A03": ("K-WOS-03",),
    "A04": ("K-ARCH-02",),
    "A05": ("K-WOS-03",),
    "A06": ("K-SIDECAR-01", "K-ARCH-02"),
    "A07": ("K-STORY-01",),
    "A08": ("K-WOS-03",),
    "A09": ("K-ARCH-01",),
    "A10": ("K-ARCH-03", "K-WOS-03"),
}

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
    mechanisms: str = ""
    breakpoints: str = ""
    transfers: str = ""
    limit_or_action: str = ""


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
        limit_or_action = cells[2][:260] if len(cells) > 2 else ""
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
                limit_or_action=limit_or_action,
            ),
        )


def _parse_exhibit_sections(text: str) -> dict[str, str]:
    """Extract mechanisms, breakpoints, and transfers from an archaeology exhibit's 3 sections."""
    sections: list[list[str]] = []
    current: list[str] | None = None
    in_fence = False
    for raw in text.splitlines():
        st = raw.strip()
        if st.startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if st.startswith("## "):
            if current is not None:
                sections.append(current)
            current = []
        elif current is not None and not st.startswith("### "):
            if st:
                current.append(st)
    if current is not None:
        sections.append(current)

    def clean_section(sec_lines: list[str]) -> str:
        kept: list[str] = []
        for idx, line in enumerate(sec_lines):
            if line.startswith("| ---"):
                continue
            if line.startswith("|") and idx + 1 < len(sec_lines) and sec_lines[idx + 1].startswith("| ---"):
                continue
            kept.append(line)
        joined = re.sub(r"\s*\|\s*", " · ", " ".join(kept))
        return _strip_md(joined)

    return {
        "mechanisms": clean_section(sections[0])[:500] if len(sections) >= 1 else "",
        "breakpoints": clean_section(sections[1])[:600] if len(sections) >= 2 else "",
        "transfers": clean_section(sections[2])[:600] if len(sections) >= 3 else "",
    }


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
        full_text = md_file.read_text(encoding="utf-8", errors="replace")
        lines = full_text.splitlines()
        title = num_match.group(2)
        for line in lines:
            if line.strip().startswith("# "):
                title = _strip_md(line.strip()[2:])
                break
        summary = _strip_md(" ".join(ln.strip() for ln in lines[1:8] if ln.strip()))[:300]
        sections = _parse_exhibit_sections(full_text)
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
                related_ids=EXHIBIT_LESSON_LINKS.get(exhibit_id, ()),
                reachability="local",
                mechanisms=sections["mechanisms"],
                breakpoints=sections["breakpoints"],
                transfers=sections["transfers"],
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


PRIMITIVE_VALID_STATUSES = frozenset({"WIRED_HERE", "EXTERNAL_PROVEN", "PROTOTYPE"})
PRIMITIVE_REQUIRED_KEYS = (
    "id",
    "name",
    "family",
    "domains",
    "inputs",
    "mechanism",
    "outputs",
    "breakpoints",
    "status",
    "sources",
    "receiving_check",
)


def _index_primitives(
    root: Path,
    entries: dict[str, CapabilityEntry],
    alias_map: dict[str, str],
) -> None:
    """Load atomic primitives from Knowledge/Crucible_Primitives.json into RAM index."""
    prim_file = root / "Knowledge" / "Crucible_Primitives.json"
    if not prim_file.is_file():
        return
    try:
        payload = json.loads(prim_file.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError:
        return
    primitives = payload.get("primitives")
    if not isinstance(primitives, list):
        return

    rel_path = "Knowledge/Crucible_Primitives.json"
    for item in primitives:
        if not isinstance(item, dict):
            continue
        pid = str(item.get("id") or "").strip()
        name = str(item.get("name") or "").strip()
        if not pid or not name:
            continue
        family = str(item.get("family") or "").strip()
        domains = item.get("domains") if isinstance(item.get("domains"), list) else []
        status = str(item.get("status") or "").strip()
        summary = f"[{family} | {status}] {item.get('mechanism', '')}".strip()
        use_when = f"inputs={item.get('inputs', '')} -> outputs={item.get('outputs', '')}".strip()
        sources = item.get("sources") if isinstance(item.get("sources"), list) else []
        related = [
            m.group(1)
            for s in sources
            for m in [re.search(r"\b(A\d{2}|K-[A-Z0-9-]+)\b", str(s))]
            if m
        ]
        entries[pid] = CapabilityEntry(
            id=pid,
            kind="primitive",
            title=name,
            path=rel_path,
            line=1,
            domain=" ".join(str(d) for d in domains) or family or "general",
            summary=summary,
            use_when=use_when,
            reachability="local",
            related_ids=related,
            mechanisms=str(item.get("mechanism") or ""),
            breakpoints=str(item.get("breakpoints") or ""),
            transfers=str(item.get("receiving_check") or ""),
            limit_or_action=str(item.get("receiving_check") or ""),
        )
        alias_map[pid.lower()] = pid
        alias_map[name.lower()] = pid


def validate_primitives_registry(root: Path, findings: list[DiagnosticFinding]) -> int:
    """Validate Knowledge/Crucible_Primitives.json schema and return primitive count."""
    prim_file = root / "Knowledge" / "Crucible_Primitives.json"
    if not prim_file.is_file():
        return 0
    try:
        payload = json.loads(prim_file.read_text(encoding="utf-8", errors="replace"))
    except json.JSONDecodeError as exc:
        findings.append(
            DiagnosticFinding(
                category="primitives",
                severity="FAIL",
                subject="Knowledge/Crucible_Primitives.json",
                detail=f"invalid JSON: {exc}",
            )
        )
        return 0

    families = set(payload.get("families") or [])
    primitives = payload.get("primitives")
    if not isinstance(primitives, list) or not primitives:
        findings.append(
            DiagnosticFinding(
                category="primitives",
                severity="FAIL",
                subject="Knowledge/Crucible_Primitives.json",
                detail="missing or empty 'primitives' list",
            )
        )
        return 0

    seen_ids: set[str] = set()
    errors: list[str] = []
    for idx, item in enumerate(primitives):
        if not isinstance(item, dict):
            errors.append(f"entry[{idx}] is not an object")
            continue
        pid = str(item.get("id") or f"entry[{idx}]")
        if pid in seen_ids:
            errors.append(f"duplicate id '{pid}'")
        seen_ids.add(pid)
        for key in PRIMITIVE_REQUIRED_KEYS:
            val = item.get(key)
            if not val:
                errors.append(f"{pid} missing/empty '{key}'")
        if families and item.get("family") not in families:
            errors.append(f"{pid} unknown family '{item.get('family')}'")
        if item.get("status") not in PRIMITIVE_VALID_STATUSES:
            errors.append(f"{pid} invalid status '{item.get('status')}'")

    if errors:
        findings.append(
            DiagnosticFinding(
                category="primitives",
                severity="FAIL",
                subject="Knowledge/Crucible_Primitives.json",
                detail="; ".join(errors[:5]),
            )
        )
    else:
        findings.append(
            DiagnosticFinding(
                category="primitives",
                severity="PASS",
                subject="Knowledge/Crucible_Primitives.json",
                detail=f"{len(primitives)} atomic primitives validated across {len(families)} families",
            )
        )
    return len(primitives)


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
    _index_primitives(root, entries, alias_map)
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


@dataclass(frozen=True)
class ForgeBrief:
    """In-RAM prior-art, lesson, project-home, and falsifiable verification synthesis for building new systems."""

    problem: str
    abstained: bool
    reason: str
    build_ms: float
    existing_projects: list[dict[str, Any]]
    prior_systems: list[dict[str, Any]]
    governing_lessons: list[dict[str, Any]]
    procedures_and_roles: list[dict[str, Any]]
    verification_requirements: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _score_entries(
    index: CapabilityIndex,
    q_tokens: list[str],
    *,
    min_score: float = 1.5,
    include_deep_fields: bool = False,
) -> list[RouteMatch]:
    doc_tokens_map: dict[str, tuple[set[str], set[str], set[str]]] = {}
    df: dict[str, int] = {}
    for eid, entry in index.entries.items():
        title_toks = set(_tokenize(f"{entry.id} {entry.title}"))
        use_toks = set(_tokenize(f"{entry.use_when} {entry.domain} {entry.kind}"))
        body_source = (
            f"{entry.summary} {entry.mechanisms} {entry.breakpoints} {entry.transfers} {entry.limit_or_action}"
            if include_deep_fields
            else entry.summary
        )
        body_toks = set(_tokenize(body_source))
        doc_tokens_map[eid] = (title_toks, use_toks, body_toks)
        for tok in title_toks | use_toks | body_toks:
            df[tok] = df.get(tok, 0) + 1

    n_docs = max(1, len(index.entries))
    q_unique = set(q_tokens)
    scored: list[RouteMatch] = []
    for eid, entry in index.entries.items():
        title_toks, use_toks, body_toks = doc_tokens_map[eid]
        score = 0.0
        hit_tokens: list[str] = []
        for qtok in q_unique:
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
    return scored


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

    scored = _score_entries(index, q_tokens, min_score=min_score, include_deep_fields=False)
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


def _build_verification_requirements(matched_ids: set[str]) -> list[str]:
    reqs = [
        "[TQ-01..TQ-05] Enforce real assertions (no assert True / x == x), no unconditional skips, "
        "no hardcoded user paths or session UUIDs, live execution tests, and at least one negative/failure-path test."
    ]
    if matched_ids & {"A09", "K-ARCH-01"}:
        reqs.append(
            "[K-ARCH-01 / A09] Add a resume fixture where a prerequisite step FAILED and assert downstream steps "
            "do not execute or report COMPLETED."
        )
    if matched_ids & {"A04", "A06", "K-ARCH-02"}:
        reqs.append(
            "[K-ARCH-02 / A04 / A06] Run a counterfactual baseline comparison and an out-of-domain abstention probe; "
            "record neutral results honestly."
        )
    if matched_ids & {"A06", "K-SIDECAR-01"}:
        reqs.append(
            "[K-SIDECAR-01 / A06] Add a schema-key mismatch / zero-row silent-loss regression test and verify source "
            "identity is preserved across views."
        )
    if matched_ids & {"A02", "A03", "A10", "K-ARCH-03"}:
        reqs.append(
            "[K-ARCH-03 / A02 / A03 / A10] Bind receipts and pass claims to exact revision, cwd, and executed test "
            "output; reject cross-operation replay."
        )
    if matched_ids & {"A07", "K-STORY-01"}:
        reqs.append(
            "[K-STORY-01 / A07] Verify outputs trace to verified source transcripts/locators and explicitly mark "
            "missing or unverified items."
        )
    if matched_ids & {"WOS-GRAPH", "K-GRAPH-01"}:
        reqs.append(
            "[K-GRAPH-01] Distinguish verified blocking edges (-->) from advisory or unverified links (-.->)."
        )
    return reqs


def forge_brief(
    index: CapabilityIndex,
    problem: str,
    *,
    top_k: int = 4,
    min_score: float = 1.5,
) -> ForgeBrief:
    """Synthesize prior systems, failure breakpoints, governing lessons, existing homes, and test floors in RAM."""
    q_tokens = _tokenize(problem)
    if not problem.strip() or not q_tokens:
        return ForgeBrief(
            problem=problem,
            abstained=True,
            reason="Empty or non-domain problem statement; apply TQ-01..TQ-05 baseline checks.",
            build_ms=round(index.build_ms, 2),
            existing_projects=[],
            prior_systems=[],
            governing_lessons=[],
            procedures_and_roles=[],
            verification_requirements=_build_verification_requirements(set()),
        )

    scored = _score_entries(index, q_tokens, min_score=min_score, include_deep_fields=True)
    existing_projects: list[dict[str, Any]] = []
    prior_systems: list[dict[str, Any]] = []
    governing_lessons: list[dict[str, Any]] = []
    procedures_and_roles: list[dict[str, Any]] = []

    for m in scored:
        e = m.entry
        sc = round(m.score, 3)
        if e.kind == "project" and len(existing_projects) < top_k:
            existing_projects.append(
                {
                    "id": e.id,
                    "title": e.title,
                    "path": e.path,
                    "line": e.line,
                    "score": sc,
                    "matched_via": m.matched_via,
                    "summary": e.summary,
                    "next_point": e.limit_or_action,
                }
            )
        elif e.kind == "exhibit" and len(prior_systems) < top_k:
            prior_systems.append(
                {
                    "id": e.id,
                    "title": e.title,
                    "path": e.path,
                    "score": sc,
                    "matched_via": m.matched_via,
                    "mechanisms": e.mechanisms,
                    "breakpoints": e.breakpoints,
                    "transfers": e.transfers,
                }
            )
        elif e.kind == "knowledge" and len(governing_lessons) < top_k:
            governing_lessons.append(
                {
                    "id": e.id,
                    "title": e.title,
                    "path": e.path,
                    "line": e.line,
                    "score": sc,
                    "matched_via": m.matched_via,
                    "summary": e.summary,
                    "use_when": e.use_when,
                    "limit_or_action": e.limit_or_action,
                }
            )
        elif e.kind in ("procedure", "role", "skill", "doc") and len(procedures_and_roles) < top_k:
            procedures_and_roles.append(
                {
                    "id": e.id,
                    "kind": e.kind,
                    "title": e.title,
                    "path": e.path,
                    "line": e.line,
                    "score": sc,
                    "matched_via": m.matched_via,
                    "summary": e.summary,
                }
            )

    seen_lessons = {item["id"] for item in governing_lessons}
    for ex_item in prior_systems:
        ex_entry = index.entries.get(ex_item["id"])
        if ex_entry is None:
            continue
        for rel_id in ex_entry.related_ids:
            if rel_id in seen_lessons or rel_id not in index.entries:
                continue
            k_entry = index.entries[rel_id]
            if k_entry.kind != "knowledge":
                continue
            seen_lessons.add(rel_id)
            governing_lessons.append(
                {
                    "id": k_entry.id,
                    "title": k_entry.title,
                    "path": k_entry.path,
                    "line": k_entry.line,
                    "score": ex_item["score"],
                    "matched_via": f"linked_from:{ex_item['id']}",
                    "summary": k_entry.summary,
                    "use_when": k_entry.use_when,
                    "limit_or_action": k_entry.limit_or_action,
                }
            )

    abstained = not (existing_projects or prior_systems or governing_lessons or procedures_and_roles)
    matched_ids = (
        {p["id"] for p in existing_projects}
        | {p["id"] for p in prior_systems}
        | {k["id"] for k in governing_lessons}
        | {r["id"] for r in procedures_and_roles}
    )
    reason = (
        f"No Crucible project, exhibit, lesson, or procedure reached threshold ({min_score}); abstaining cleanly while keeping universal verification floor."
        if abstained
        else f"Synthesized {len(existing_projects)} project(s), {len(prior_systems)} exhibit(s), {len(governing_lessons)} lesson(s), and {len(procedures_and_roles)} procedure/role(s) in {index.build_ms:.1f}ms."
    )
    return ForgeBrief(
        problem=problem,
        abstained=abstained,
        reason=reason,
        build_ms=round(index.build_ms, 2),
        existing_projects=existing_projects,
        prior_systems=prior_systems,
        governing_lessons=governing_lessons,
        procedures_and_roles=procedures_and_roles,
        verification_requirements=_build_verification_requirements(matched_ids),
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
        "PreToolUse": json.dumps(
            {
                "conversationId": "doctor-probe",
                "workspacePaths": [str(cwd)],
                "toolCall": {"name": "read_file", "args": {"Path": str(cwd / "README.md")}},
            }
        ),
        "Stop": json.dumps({"terminationReason": "USER_CANCELED", "executionNum": 0}),
    }
    if event_name not in probe_payloads:
        return True, "path exists (skipped live execution for PostToolUse)"
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
    primitive_count = validate_primitives_registry(root, findings)

    metrics: dict[str, Any] = {
        "index_build_ms": round(index.build_ms, 2),
        "indexed_total": len(index.entries),
        "indexed_counts": index.counts_by_kind,
        "primitives_validated": primitive_count,
        "skill_frontmatter_bytes": index.skill_frontmatter_bytes,
        **hook_metrics,
        **link_metrics,
        **storage_metrics,
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


def _format_forge_text(brief: ForgeBrief) -> str:
    lines = [
        f"Crucible Forge Brief ({'ABSTAINED' if brief.abstained else 'GROUNDED'} in {brief.build_ms}ms)",
        f"Problem: {brief.problem}",
        f"Status: {brief.reason}",
    ]
    if brief.existing_projects:
        lines.append("\n1. Existing Project Homes (anti-duplication check):")
        for p in brief.existing_projects:
            lines.append(f"  - {p['id']}: {p['title']} (score={p['score']}, {p['path']}:{p['line']})")
            if p["next_point"]:
                lines.append(f"    Next point: {p['next_point']}")
    if brief.prior_systems:
        lines.append("\n2. Prior Systems & Known Breakpoints (Archaeology A01..A10):")
        for s in brief.prior_systems:
            lines.append(f"  - {s['id']}: {s['title']} (score={s['score']}, {s['path']})")
            if s["breakpoints"]:
                lines.append(f"    Breakpoint: {s['breakpoints'][:220]}")
            if s["transfers"]:
                lines.append(f"    Carry forward: {s['transfers'][:220]}")
    if brief.governing_lessons:
        lines.append("\n3. Governing Knowledge Lessons (K-*):")
        for k in brief.governing_lessons:
            lines.append(f"  - {k['id']} ({k['matched_via']}): {k['title']} ({k['path']}:{k['line']})")
            if k["limit_or_action"]:
                lines.append(f"    Limit/Action: {k['limit_or_action']}")
    if brief.procedures_and_roles:
        lines.append("\n4. Local Procedures, Roles & Skills:")
        for r in brief.procedures_and_roles:
            lines.append(f"  - {r['id']} ({r['kind']}, score={r['score']}): {r['title']} ({r['path']}:{r['line']})")
    lines.append("\n5. Mandatory Verification Requirements:")
    for req in brief.verification_requirements:
        lines.append(f"  - {req}")
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


MAX_MELT_SCAN_REPOS = 5
MAX_SAMPLE_PATHS = 20
MAX_README_EXCERPT_CHARS = 280
MAX_STDOUT_BYTES_PER_REPO = 1200
STUB_DISK_KB_THRESHOLD = 5

ACTIVE_HUB_REPOS = frozenset({"crucible-domain", "antigravity-config", "work-operating-system"})

IGNORED_TREE_DIRS = frozenset(
    {
        "node_modules",
        ".git",
        "dist",
        "build",
        ".venv",
        "venv",
        "__pycache__",
        ".next",
        "target",
        "vendor",
        ".pytest_cache",
        ".mypy_cache",
    }
)

ASSET_OR_BINARY_EXTS = (
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".svg",
    ".ico",
    ".mp4",
    ".mov",
    ".avi",
    ".mkv",
    ".wav",
    ".mp3",
    ".flac",
    ".zip",
    ".tar",
    ".gz",
    ".7z",
    ".db",
    ".sqlite",
    ".sqlite3",
    ".pdf",
    ".woff",
    ".woff2",
    ".ttf",
    ".eot",
    ".pyc",
    ".exe",
    ".dll",
    ".so",
    ".dylib",
    ".bin",
)

CODE_EXTS = (
    ".py",
    ".ts",
    ".tsx",
    ".js",
    ".jsx",
    ".rs",
    ".go",
    ".sh",
    ".ps1",
    ".sql",
    ".html",
    ".css",
    ".c",
    ".cpp",
    ".h",
    ".java",
    ".rb",
)

MANIFEST_FILENAMES = frozenset(
    {
        "pyproject.toml",
        "requirements.txt",
        "setup.py",
        "package.json",
        "cargo.toml",
        "go.mod",
        "dockerfile",
        "docker-compose.yml",
        "makefile",
    }
)

ENTRYPOINT_BASENAMES = frozenset(
    {
        "main.py",
        "cli.py",
        "app.py",
        "server.py",
        "index.py",
        "index.ts",
        "index.tsx",
        "index.js",
        "main.ts",
        "main.rs",
        "lib.rs",
        "skill.md",
        "hooks.json",
    }
)

MONTH_NAME_TO_NUM = {
    "january": "01",
    "february": "02",
    "march": "03",
    "april": "04",
    "may": "05",
    "june": "06",
    "july": "07",
    "august": "08",
    "september": "09",
    "october": "10",
    "november": "11",
    "december": "12",
}


def _discover_melted_exhibits(root: Path) -> tuple[dict[str, dict[str, str]], str]:
    """Return mapping of lowercase repo slug -> exhibit metadata and intake ISO date."""
    arch_dir = root / "Knowledge" / "Repository Archaeology"
    exhibit_date = "2026-11-15"
    index_md = arch_dir / "00-Exhibit_Index.md"
    if index_md.is_file():
        head_text = index_md.read_text(encoding="utf-8", errors="replace")[:600]
        m_date = re.search(
            r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s*(\d{4})\b",
            head_text,
            re.IGNORECASE,
        )
        if m_date:
            month_num = MONTH_NAME_TO_NUM[m_date.group(1).lower()]
            day_num = f"{int(m_date.group(2)):02d}"
            exhibit_date = f"{m_date.group(3)}-{month_num}-{day_num}"

    melted: dict[str, dict[str, str]] = {}
    if not arch_dir.is_dir():
        return melted, exhibit_date

    for md_file in sorted(arch_dir.glob("*.md")):
        if md_file.name.startswith("00-"):
            continue
        m_name = re.match(r"^(\d{2})-(.+)\.md$", md_file.name)
        if not m_name:
            continue
        ex_id = f"A{m_name.group(1)}"
        slug = m_name.group(2).strip().lower()
        rel_path = md_file.relative_to(root).as_posix()
        melted[slug] = {
            "exhibit_id": ex_id,
            "slug": slug,
            "path": rel_path,
            "exhibit_date": exhibit_date,
        }
    return melted, exhibit_date


def _discover_registered_github_repos(root: Path) -> set[str]:
    """Return lowercase GitHub repo names listed in Project/Project_Register.md."""
    reg_file = root / "Project" / "Project_Register.md"
    if not reg_file.is_file():
        return set()
    text = reg_file.read_text(encoding="utf-8", errors="replace")
    found: set[str] = set()
    for match in re.finditer(r"https://github\.com/[^/\s)]+/([^/\s)#]+)", text):
        found.add(match.group(1).strip().lower())
    return found


def fetch_github_repos(owner: str = "guarani-ux", timeout_sec: int = 15) -> list[dict[str, Any]]:
    """Fetch repository inventory via read-only `gh repo list`."""
    proc = subprocess.run(
        [
            "gh",
            "repo",
            "list",
            owner,
            "--limit",
            "200",
            "--json",
            "name,description,isPrivate,isArchived,pushedAt,primaryLanguage,diskUsage",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_sec,
        check=False,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "gh repo list failed").strip()
        raise RuntimeError(f"gh repo list failed (rc={proc.returncode}): {err[:240]}")
    data = json.loads(proc.stdout or "[]")
    if not isinstance(data, list):
        raise RuntimeError("gh repo list did not return a JSON array")
    return data


def compute_melt_diff(
    root: Path,
    repos_data: list[dict[str, Any]],
) -> dict[str, Any]:
    """Deterministically subtract already-melted exhibits and hubs from GitHub inventory."""
    melted_map, exhibit_date = _discover_melted_exhibits(root)
    registered = _discover_registered_github_repos(root)

    melted: list[dict[str, Any]] = []
    stale_melted: list[dict[str, Any]] = []
    active_hubs: list[dict[str, Any]] = []
    unmelted: list[dict[str, Any]] = []
    skip_stubs: list[dict[str, Any]] = []

    sorted_repos = sorted(
        repos_data,
        key=lambda r: (str(r.get("pushedAt") or ""), str(r.get("name") or "").lower()),
        reverse=True,
    )

    for raw in sorted_repos:
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        norm = name.lower()
        pushed_at = str(raw.get("pushedAt") or "")[:10]
        disk_kb = int(raw.get("diskUsage") or 0)
        is_archived = bool(raw.get("isArchived"))
        is_private = bool(raw.get("isPrivate"))
        lang_obj = raw.get("primaryLanguage")
        language = str(lang_obj.get("name") or "-") if isinstance(lang_obj, dict) else "-"
        description = str(raw.get("description") or "").strip()[:160]
        in_register = norm in registered

        base_row: dict[str, Any] = {
            "name": name,
            "pushed_date": pushed_at,
            "language": language,
            "disk_kb": disk_kb,
            "visibility": "archived" if is_archived else ("private" if is_private else "public"),
            "in_project_register": in_register,
            "description": description,
        }

        if norm in melted_map:
            ex = melted_map[norm]
            is_stale = bool(pushed_at and pushed_at > ex["exhibit_date"])
            status = "STALE_MELTED" if is_stale else "MELTED"
            row = {
                **base_row,
                "status": status,
                "exhibit_id": ex["exhibit_id"],
                "exhibit_path": ex["path"],
                "exhibit_date": ex["exhibit_date"],
            }
            if is_stale:
                stale_melted.append(row)
            else:
                melted.append(row)
        elif norm in ACTIVE_HUB_REPOS:
            active_hubs.append({**base_row, "status": "ACTIVE_HUB"})
        elif is_archived or disk_kb <= STUB_DISK_KB_THRESHOLD:
            reason = "archived" if is_archived else f"disk_kb={disk_kb}<={STUB_DISK_KB_THRESHOLD}"
            skip_stubs.append({**base_row, "status": "SKIP_STUB", "skip_reason": reason})
        else:
            unmelted.append({**base_row, "status": "UNMELTED"})

    melted.sort(key=lambda r: str(r.get("exhibit_id") or ""))
    stale_melted.sort(key=lambda r: str(r.get("exhibit_id") or ""))

    return {
        "root": str(root.resolve()),
        "exhibit_baseline_date": exhibit_date,
        "counts": {
            "total_github": len(sorted_repos),
            "melted": len(melted),
            "stale_melted": len(stale_melted),
            "active_hub": len(active_hubs),
            "unmelted": len(unmelted),
            "skip_stub": len(skip_stubs),
            "unregistered_on_github": sum(
                1 for r in (unmelted + skip_stubs + active_hubs) if not r["in_project_register"]
            ),
        },
        "stale_melted": stale_melted,
        "melted": melted,
        "active_hub": active_hubs,
        "unmelted": unmelted,
        "skip_stub": skip_stubs,
    }


def _format_melt_diff_text(report: dict[str, Any]) -> str:
    c = report["counts"]
    lines = [
        f"Crucible Melt Diff (baseline={report['exhibit_baseline_date']})",
        (
            f"GitHub Total: {c['total_github']} | Melted: {c['melted']} | Stale Melted: {c['stale_melted']} | "
            f"Active Hub: {c['active_hub']} | Unmelted Queue: {c['unmelted']} | Auto-Skip Stubs: {c['skip_stub']}"
        ),
    ]
    if report["stale_melted"]:
        lines.append("\n[STALE_MELTED] Pushed after exhibit date (re-verify changes):")
        for r in report["stale_melted"]:
            lines.append(
                f"  - {r['exhibit_id']} {r['name']} (pushed={r['pushed_date']} > {r['exhibit_date']}, {r['disk_kb']}KB)"
            )
    lines.append(f"\n[UNMELTED] High-signal candidates ({len(report['unmelted'])}):")
    for idx, r in enumerate(report["unmelted"], 1):
        reg_tag = "" if r["in_project_register"] else " [NEW_ON_GITHUB]"
        desc = f" — {r['description']}" if r["description"] else ""
        lines.append(
            f"  {idx:2d}. {r['name']:26s} | {r['pushed_date']} | {r['language']:10s} | {r['disk_kb']:7d}KB{reg_tag}{desc}"
        )
    if report["skip_stub"]:
        stub_names = ", ".join(f"{r['name']}({r['disk_kb']}KB)" for r in report["skip_stub"])
        lines.append(f"\n[SKIP_STUB] ({len(report['skip_stub'])}): {stub_names}")
    return "\n".join(lines)


def _clean_readme_excerpt(readme_text: str) -> str:
    """Return a compact, single-line excerpt <= MAX_README_EXCERPT_CHARS without dumping raw markdown."""
    kept: list[str] = []
    for raw_line in readme_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("```") or line.startswith("![") or line.startswith("<"):
            continue
        line = re.sub(r"^#+\s*", "", line).strip()
        if line:
            kept.append(line)
        if sum(len(x) for x in kept) >= MAX_README_EXCERPT_CHARS:
            break
    joined = " · ".join(kept)
    return joined[:MAX_README_EXCERPT_CHARS]


def _is_test_path(rel_path: str) -> bool:
    norm = rel_path.replace("\\", "/").lower()
    base = norm.rsplit("/", 1)[-1]
    return (
        "/tests/" in f"/{norm}"
        or "/test/" in f"/{norm}"
        or base.startswith("test_")
        or base.endswith(("_test.py", ".test.ts", ".test.tsx", ".spec.ts", ".spec.js"))
    )


def analyze_repo_tree_payload(
    repo_name: str,
    tree_payload: dict[str, Any],
    readme_text: str = "",
) -> dict[str, Any]:
    """Deterministically extract a bounded structural Ore Card from a GitHub git/trees payload."""
    if tree_payload.get("error_status") == 409 or tree_payload.get("empty_repo"):
        return {
            "repo": repo_name,
            "triage_verdict": "EMPTY_REPO",
            "reason": "Repository has an empty Git tree (0 commits/blobs).",
            "total_blobs": 0,
            "code_files": 0,
            "test_files": 0,
            "doc_files": 0,
            "ignored_or_asset_files": 0,
            "top_dirs": [],
            "manifests": [],
            "entrypoints": [],
            "sample_paths": [],
            "readme_excerpt": "",
        }

    if tree_payload.get("error"):
        return {
            "repo": repo_name,
            "triage_verdict": "ERROR",
            "reason": str(tree_payload.get("error"))[:220],
            "total_blobs": 0,
            "code_files": 0,
            "test_files": 0,
            "doc_files": 0,
            "ignored_or_asset_files": 0,
            "top_dirs": [],
            "manifests": [],
            "entrypoints": [],
            "sample_paths": [],
            "readme_excerpt": "",
        }

    raw_tree = tree_payload.get("tree")
    if not isinstance(raw_tree, list):
        raw_tree = []

    total_blobs = 0
    code_files = 0
    test_files = 0
    doc_files = 0
    ignored_or_asset_files = 0
    top_dirs_set: set[str] = set()
    manifests: list[str] = []
    entrypoints: list[str] = []
    sample_paths: list[str] = []

    for item in raw_tree:
        if not isinstance(item, dict) or item.get("type") != "blob":
            continue
        path_str = str(item.get("path") or "").strip()
        if not path_str:
            continue
        total_blobs += 1
        parts = path_str.split("/")
        if len(parts) > 1:
            top_dirs_set.add(parts[0])

        lower_parts = [p.lower() for p in parts]
        base_lower = lower_parts[-1]

        if any(p in IGNORED_TREE_DIRS for p in lower_parts[:-1]) or base_lower.endswith(ASSET_OR_BINARY_EXTS):
            ignored_or_asset_files += 1
            continue

        if base_lower in MANIFEST_FILENAMES and path_str not in manifests and len(manifests) < 8:
            manifests.append(path_str)

        if (
            base_lower in ENTRYPOINT_BASENAMES
            or (len(parts) <= 3 and base_lower.endswith((".py", ".ts", ".rs")) and not _is_test_path(path_str))
        ) and len(entrypoints) < 10:
            entrypoints.append(path_str)

        if _is_test_path(path_str):
            test_files += 1
        elif base_lower.endswith(CODE_EXTS):
            code_files += 1
        elif base_lower.endswith((".md", ".txt", ".rst")):
            doc_files += 1

        if len(sample_paths) < MAX_SAMPLE_PATHS:
            sample_paths.append(path_str)

    has_skill_md = any(p.lower().endswith("skill.md") for p in entrypoints + sample_paths)
    if total_blobs == 0:
        verdict = "EMPTY_REPO"
        reason = "No blob entries found in repository tree."
    elif code_files == 0 and test_files == 0 and not has_skill_md:
        verdict = "SKIP_ASSET_OR_STUB"
        reason = f"0 code/test files across {total_blobs} blobs (docs={doc_files}, assets/ignored={ignored_or_asset_files})."
    else:
        verdict = "MELT_READY"
        reason = (
            f"{code_files} code file(s), {test_files} test file(s), "
            f"{len(manifests)} manifest(s), {len(entrypoints)} entrypoint(s)."
        )

    return {
        "repo": repo_name,
        "triage_verdict": verdict,
        "reason": reason,
        "truncated_tree": bool(tree_payload.get("truncated")),
        "total_blobs": total_blobs,
        "code_files": code_files,
        "test_files": test_files,
        "doc_files": doc_files,
        "ignored_or_asset_files": ignored_or_asset_files,
        "top_dirs": sorted(top_dirs_set)[:8],
        "manifests": manifests,
        "entrypoints": entrypoints,
        "sample_paths": sample_paths,
        "readme_excerpt": _clean_readme_excerpt(readme_text),
    }


def _fetch_repo_tree_and_readme(owner: str, repo: str, timeout_sec: int = 15) -> tuple[dict[str, Any], str]:
    """Perform at most 2 read-only `gh api` calls (tree + readme) without cloning."""
    tree_proc = subprocess.run(
        ["gh", "api", f"repos/{owner}/{repo}/git/trees/HEAD?recursive=1"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_sec,
        check=False,
    )
    if tree_proc.returncode != 0:
        err_text = (tree_proc.stderr or tree_proc.stdout or "").strip()
        if "409" in err_text or "Git Repository is empty" in err_text:
            return {"error_status": 409, "empty_repo": True}, ""
        return {"error": f"gh api tree failed (rc={tree_proc.returncode}): {err_text[:180]}"}, ""

    try:
        tree_data = json.loads(tree_proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        return {"error": f"invalid tree JSON: {exc}"}, ""

    readme_proc = subprocess.run(
        ["gh", "api", f"repos/{owner}/{repo}/readme", "--jq", ".content"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_sec,
        check=False,
    )
    readme_text = ""
    if readme_proc.returncode == 0 and readme_proc.stdout.strip():
        import base64

        try:
            readme_text = base64.b64decode(readme_proc.stdout.strip()).decode("utf-8", errors="replace")
        except (ValueError, OSError) as exc:
            readme_text = f"[readme decode warning: {exc}]"

    return (tree_data if isinstance(tree_data, dict) else {"error": "unexpected tree payload"}), readme_text


def run_melt_scan(
    repos: list[str],
    *,
    owner: str = "guarani-ux",
    fixtures: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Scan 1..MAX_MELT_SCAN_REPOS repositories without cloning and return bounded Ore Cards."""
    cleaned = [r.strip() for r in repos if r.strip()]
    if not cleaned:
        raise ValueError("melt-scan requires at least 1 repository name.")
    if len(cleaned) > MAX_MELT_SCAN_REPOS:
        raise ValueError(
            f"melt-scan batch cap exceeded: got {len(cleaned)} repos, max is {MAX_MELT_SCAN_REPOS} per call "
            "to prevent token burn and rate-limit exhaustion."
        )

    results: list[dict[str, Any]] = []
    for repo_name in cleaned:
        if fixtures is not None:
            fix = fixtures.get(repo_name) or fixtures.get(repo_name.lower())
            if fix is None:
                card = analyze_repo_tree_payload(repo_name, {"error": f"No offline fixture for '{repo_name}'"})
            else:
                card = analyze_repo_tree_payload(
                    repo_name,
                    fix.get("tree_payload", fix),
                    str(fix.get("readme_text") or ""),
                )
        else:
            tree_payload, readme_text = _fetch_repo_tree_and_readme(owner, repo_name)
            card = analyze_repo_tree_payload(repo_name, tree_payload, readme_text)
        results.append(card)

    return {
        "owner": owner,
        "scanned_count": len(results),
        "max_batch_cap": MAX_MELT_SCAN_REPOS,
        "results": results,
    }


def _format_melt_scan_text(scan_report: dict[str, Any]) -> str:
    header = (
        f"Crucible Melt Scan ({scan_report['scanned_count']}/{scan_report['max_batch_cap']} repos, "
        f"cap<={MAX_STDOUT_BYTES_PER_REPO}B/repo)"
    )
    blocks: list[str] = [header]
    for item in scan_report["results"]:
        lines = [
            f"\n[{item['triage_verdict']}] {item['repo']} — {item['reason']}",
            (
                f"  Counts: blobs={item['total_blobs']} | code={item['code_files']} | "
                f"tests={item['test_files']} | docs={item['doc_files']} | assets/ignored={item['ignored_or_asset_files']}"
            ),
        ]
        if item["top_dirs"]:
            lines.append(f"  Top dirs: {', '.join(item['top_dirs'])}")
        if item["manifests"]:
            lines.append(f"  Manifests: {', '.join(item['manifests'])}")
        if item["entrypoints"]:
            lines.append(f"  Entrypoints: {', '.join(item['entrypoints'][:8])}")
        if item["readme_excerpt"]:
            lines.append(f"  README: {item['readme_excerpt']}")
        block = "\n".join(lines)
        if len(block.encode("utf-8")) > MAX_STDOUT_BYTES_PER_REPO:
            block = block.encode("utf-8")[: MAX_STDOUT_BYTES_PER_REPO - 3].decode("utf-8", errors="ignore") + "..."
        blocks.append(block)
    return "\n".join(blocks)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Crucible Domain in-RAM index, router, forge, and doctor.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_route = sub.add_parser("route", help="Resolve an ID or task query to local capabilities in RAM.")
    p_route.add_argument("query", nargs="+")
    p_route.add_argument("--top", type=int, default=5)
    p_route.add_argument("--json", action="store_true")
    p_route.add_argument("--no-global", action="store_true")

    p_forge = sub.add_parser("forge", help="Synthesize prior systems, breakpoints, lessons, and test requirements in RAM.")
    p_forge.add_argument("problem", nargs="+")
    p_forge.add_argument("--top", type=int, default=4)
    p_forge.add_argument("--json", action="store_true")
    p_forge.add_argument("--no-global", action="store_true")

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

    if args.cmd == "forge":
        idx = build_index(args.root, global_config_dir=global_dir)
        brief = forge_brief(idx, " ".join(args.problem), top_k=args.top)
        print(json.dumps(brief.to_dict(), indent=2, ensure_ascii=False) if args.json else _format_forge_text(brief))
        return 0

    report = run_doctor(args.root, global_config_dir=global_dir, execute_hooks=not args.skip_exec)
    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False) if args.json else _format_doctor_text(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
