"""In-RAM capability indexer and primitives schema validator for Crucible Domain."""

from __future__ import annotations

import json
import re
import time
from pathlib import Path

from .models import (
    CHATGPT_SKILL_BINDINGS,
    CORE_ENTRY_DOCS,
    DEFAULT_GLOBAL_CONFIG_DIR,
    EXHIBIT_LESSON_LINKS,
    FRONTMATTER_RE,
    MD_LINK_RE,
    PRIMITIVE_REQUIRED_KEYS,
    PRIMITIVE_VALID_STATUSES,
    PROC_HEADING_RE,
    ROLE_CARD_CODES,
    TABLE_ROW_RE,
    BindingStatus,
    CapabilityEntry,
    CapabilityIndex,
    DiagnosticFinding,
)


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
        related = tuple(
            dict.fromkeys(
                match
                for s in sources
                for match in re.findall(r"\b(A\d{2}|K-[A-Z0-9-]+|WOS-GRAPH)\b", str(s))
            )
        )
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
