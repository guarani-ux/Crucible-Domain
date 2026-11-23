"""In-RAM prior-art, primitive stack, and verification synthesizer (`forge`)."""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from .models import (
    FORGE_DOMAINS,
    FORGE_MEDIA_CUES,
    FORGE_MEDIA_OVERRIDE_CUES,
    FORGE_SYSTEMS_CUES,
    FORGE_WORLDBUILDING_CUES,
    FORGE_WRITING_CUES,
    MEDIA_AGENCY_ID_PREFIXES,
    CapabilityIndex,
    ForgeBrief,
)
from .router import _score_entries, _tokenize


def _forge_cue_tokens(problem: str) -> set[str]:
    normalized = re.sub(r"\ba/v\b", "av", problem.lower())
    return set(_tokenize(normalized))


def _infer_forge_domain(problem: str, explicit_domain: str | None = None) -> str:
    """Infer target Crucible domain scope from explicit override or strong problem cues."""
    if explicit_domain is not None:
        cleaned = explicit_domain.strip().lower()
        if cleaned in FORGE_DOMAINS:
            return cleaned

    tokens = _forge_cue_tokens(problem)
    if not tokens:
        return "general"

    has_media = bool(tokens & FORGE_MEDIA_CUES)
    has_world = bool(tokens & FORGE_WORLDBUILDING_CUES)
    systems_hits = tokens & FORGE_SYSTEMS_CUES
    writing_hits = tokens & FORGE_WRITING_CUES

    if "resume" in tokens:
        if (systems_hits - {"resume"}) and not (writing_hits - {"resume"}):
            writing_hits = writing_hits - {"resume"}
        elif (writing_hits - {"resume"}) and not (systems_hits - {"resume"}):
            systems_hits = systems_hits - {"resume"}

    has_systems = bool(systems_hits)
    has_writing = bool(writing_hits)

    if has_systems and not (has_media or has_writing or has_world):
        return "systems"
    if has_media and not (has_systems or has_world):
        if not has_writing or bool(tokens & FORGE_MEDIA_OVERRIDE_CUES):
            return "media"
    if has_writing and not (has_media or has_systems or has_world):
        return "writing"
    if has_world and not (has_media or has_systems or has_writing):
        return "worldbuilding"
    return "general"


def _load_primitives_meta(root: Path) -> dict[str, dict[str, Any]]:
    """Load raw primitive metadata keyed by primitive ID from Knowledge/Crucible_Primitives.json."""
    prim_file = root / "Knowledge" / "Crucible_Primitives.json"
    try:
        raw_text = prim_file.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return {}
    except OSError as exc:
        print(f"warning: could not read {prim_file}: {exc}", file=sys.stderr)
        return {}

    try:
        payload = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        print(f"warning: invalid JSON in {prim_file}: {exc}", file=sys.stderr)
        return {}

    if not isinstance(payload, dict):
        return {}
    primitives = payload.get("primitives")
    if not isinstance(primitives, list):
        return {}

    meta: dict[str, dict[str, Any]] = {}
    for item in primitives:
        if not isinstance(item, dict):
            continue
        pid = str(item.get("id") or "").strip()
        if not pid:
            continue
        raw_domains = item.get("domains")
        raw_sources = item.get("sources")
        meta[pid] = {
            "id": pid,
            "name": str(item.get("name") or "").strip(),
            "family": str(item.get("family") or "").strip(),
            "domains": [str(d) for d in raw_domains] if isinstance(raw_domains, list) else [],
            "status": str(item.get("status") or "").strip(),
            "sources": [str(s) for s in raw_sources] if isinstance(raw_sources, list) else [],
            "breakpoints": str(item.get("breakpoints") or "").strip(),
            "receiving_check": str(item.get("receiving_check") or "").strip(),
        }
    return meta


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
    domain: str | None = None,
) -> ForgeBrief:
    """Synthesize atomic primitives, prior systems, breakpoints, lessons, existing homes, and test floors in RAM."""
    domain_scope = _infer_forge_domain(problem, domain)
    q_tokens = _tokenize(problem)
    if not problem.strip() or not q_tokens:
        return ForgeBrief(
            problem=problem,
            abstained=True,
            reason="Empty or non-domain problem statement; apply TQ-01..TQ-05 baseline checks.",
            build_ms=round(index.build_ms, 2),
            domain_scope=domain_scope,
            primitive_stack=[],
            existing_projects=[],
            prior_systems=[],
            governing_lessons=[],
            procedures_and_roles=[],
            verification_requirements=_build_verification_requirements(set()),
        )

    prim_meta = _load_primitives_meta(index.root)
    cue_tokens = _forge_cue_tokens(problem)
    has_ma_override = any(tok.startswith(MEDIA_AGENCY_ID_PREFIXES) for tok in q_tokens) or bool(
        cue_tokens & FORGE_MEDIA_CUES
    )

    scored = _score_entries(index, q_tokens, min_score=min_score, include_deep_fields=True)
    primitive_candidates: list[dict[str, Any]] = []
    existing_projects: list[dict[str, Any]] = []
    prior_systems: list[dict[str, Any]] = []
    governing_lessons: list[dict[str, Any]] = []
    procedures_and_roles: list[dict[str, Any]] = []

    for m in scored:
        e = m.entry
        sc = round(m.score, 3)
        if e.kind == "primitive":
            meta = prim_meta.get(e.id, {})
            prim_domains = meta.get("domains") if "domains" in meta else [d for d in e.domain.split() if d]
            primitive_candidates.append(
                {
                    "id": e.id,
                    "title": meta.get("name") or e.title,
                    "family": meta.get("family", ""),
                    "status": meta.get("status", ""),
                    "domains": list(prim_domains),
                    "sources": list(meta.get("sources") or ()),
                    "breakpoints": meta.get("breakpoints") or e.breakpoints,
                    "receiving_check": meta.get("receiving_check") or e.limit_or_action,
                    "score": sc,
                    "matched_via": m.matched_via,
                }
            )
        elif e.kind == "project" and len(existing_projects) < top_k:
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
            if (
                domain_scope == "systems"
                and e.kind in ("procedure", "role")
                and e.path.startswith("Knowledge/Media Agency/")
                and not has_ma_override
            ):
                continue
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

    if domain_scope != "general" and primitive_candidates:
        primitive_candidates.sort(
            key=lambda p: (
                not (not p["domains"] or domain_scope in p["domains"] or "general" in p["domains"]),
                -p["score"],
                p["id"],
            )
        )
    primitive_stack = primitive_candidates[:top_k]

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

    abstained = not (
        existing_projects or prior_systems or governing_lessons or procedures_and_roles or primitive_stack
    )
    matched_ids = (
        {p["id"] for p in primitive_stack}
        | {p["id"] for p in existing_projects}
        | {p["id"] for p in prior_systems}
        | {k["id"] for k in governing_lessons}
        | {r["id"] for r in procedures_and_roles}
    )
    for prim in primitive_stack:
        prim_entry = index.entries.get(prim["id"])
        if prim_entry is not None:
            matched_ids.update(prim_entry.related_ids)

    reason = (
        f"No Crucible primitive, project, exhibit, lesson, or procedure reached threshold ({min_score}); abstaining cleanly while keeping universal verification floor."
        if abstained
        else (
            f"Synthesized {len(primitive_stack)} primitive(s), {len(existing_projects)} project(s), "
            f"{len(prior_systems)} exhibit(s), {len(governing_lessons)} lesson(s), and "
            f"{len(procedures_and_roles)} procedure/role(s) [domain={domain_scope}] in {index.build_ms:.1f}ms."
        )
    )
    return ForgeBrief(
        problem=problem,
        abstained=abstained,
        reason=reason,
        build_ms=round(index.build_ms, 2),
        domain_scope=domain_scope,
        primitive_stack=primitive_stack,
        existing_projects=existing_projects,
        prior_systems=prior_systems,
        governing_lessons=governing_lessons,
        procedures_and_roles=procedures_and_roles,
        verification_requirements=_build_verification_requirements(matched_ids),
    )


def _format_forge_text(brief: ForgeBrief) -> str:
    lines = [
        f"Crucible Forge Brief ({'ABSTAINED' if brief.abstained else 'GROUNDED'} in {brief.build_ms}ms)",
        f"Problem: {brief.problem}",
        f"Status: {brief.reason}",
    ]
    if brief.primitive_stack:
        lines.append(f"\n0. Composed Atomic Primitives (domain={brief.domain_scope}):")
        for p in brief.primitive_stack:
            status = p.get("status") or "UNKNOWN"
            sources = p.get("sources") or []
            if status == "WIRED_HERE":
                status_tag = "[WIRED_HERE]"
            elif status == "EXTERNAL_PROVEN":
                first_ext = next(
                    (s for s in sources if "@" in s),
                    next(
                        (s for s in sources if not s.startswith((".agents/", "K-", "IDEAS.md"))),
                        sources[0] if sources else "external repo",
                    ),
                )
                status_tag = f"[EXTERNAL_PROVEN -> pull from {first_ext}]"
            elif status == "PROTOTYPE":
                first_src = sources[0] if sources else "prototype source"
                status_tag = f"[PROTOTYPE -> {first_src}]"
            else:
                status_tag = f"[{status}]"
            lines.append(
                f"  - {p['id']} {status_tag}: {p['title']} (family={p.get('family', '')}, score={p['score']})"
            )
            if p.get("receiving_check"):
                lines.append(f"    Receiving check: {p['receiving_check']}")
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
