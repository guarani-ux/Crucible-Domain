#!/usr/bin/env python3
"""Component 2: Deterministic 3-Axis Root Probes & Red-Capable Test-Validity Proof.

Implements mechanical Gate 1 probes for the 3 Root Axes of Institutional Sensemaking & Action Design:
  - Axis I:   Epistemic & Strategic Integrity (sources, 2027-2030 charter, stewardship, trade-offs)
  - Axis II:  Cognitive & Rhetorical Force (hooks, tension/counterpoint, A/B/C story, 4-platform divergence)
  - Axis III: Operational & Portfolio Executability (WPM/clock math, tables, owned holds, measurable action)

Also runs `verify_test_validity()` against every red-capable counterexample in `.agents/bench/axis_contracts.yaml`
to prove that each probe can genuinely turn RED on subtle failures without false positives on golden docs.
"""

from __future__ import annotations

import itertools
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .doc_flow_engine import (
    GOLDEN_SPECIMENS,
    OrganizationCharter,
    UNAUTHORIZED_RELEASE_RE,
    _jaccard_overlap,
    evaluate_document_flow,
    evaluate_stakeholder_board,
    load_organization_charter,
    parse_document_ast,
)

DEFAULT_CONTRACTS_REL = Path(".agents") / "bench" / "axis_contracts.yaml"
DEFAULT_ONTOLOGY_REL = Path(".agents") / "bench" / "sensemaking_ontology.yaml"

PATRONIZING_PHRASE_RE = re.compile(
    r"\b(needy patrons?|less fortunate|underprivileged charity|poor citizens?|charity handout)\b",
    re.IGNORECASE,
)
PLATFORM_KEYS = ("youtube", "instagram", "linkedin", "facebook", "newsletter")


@dataclass
class RootAxisReport:
    form_id: str
    axis_1_integrity: float
    axis_2_rhetorical_force: float
    axis_3_executability: float
    min_axis_score: float
    weakest_axis: str
    passed: bool
    failed_probes: list[str] = field(default_factory=list)
    probe_details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_axis_contracts(repo_root: Path) -> dict[str, Any]:
    """Load explicit WHAT/HOW/WHY contracts and red-capable counterexamples from YAML."""
    path = Path(repo_root) / DEFAULT_CONTRACTS_REL
    if not path.is_file():
        return {"axes": {}}
    import yaml  # type: ignore

    raw = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or {}
    return raw if isinstance(raw, dict) else {"axes": {}}


def _extract_platform_sections(text: str) -> dict[str, str]:
    """Extract body text under platform-named headings (YouTube, Instagram, LinkedIn, Facebook, Newsletter)."""
    ast = parse_document_ast(text)
    found: dict[str, str] = {}
    for sec in ast.sections:
        low_h = sec.heading.lower()
        for pk in PLATFORM_KEYS:
            if re.search(rf"\b{pk}\b", low_h) and sec.body.strip():
                found[pk] = sec.body.strip()
                break
    return found


def evaluate_root_axes(
    text: str,
    form_id: str,
    *,
    target_duration_s: int | None = None,
    repo_root: Path | None = None,
    charter: OrganizationCharter | None = None,
) -> RootAxisReport:
    """Evaluate a document deterministically across the 3 Root Axes (0 LLM tokens)."""
    active_charter = charter or load_organization_charter(repo_root=repo_root)
    ast = parse_document_ast(text)
    fe = evaluate_document_flow(text, form_id, target_duration_s=target_duration_s)
    bd = evaluate_stakeholder_board(
        text,
        form_id,
        flow_eval=fe,
        target_duration_s=target_duration_s,
        charter=active_charter,
        repo_root=repo_root,
    )
    ca = bd.charter_alignment
    lower = text.lower()
    failed_probes: list[str] = []
    details: dict[str, Any] = {}

    # ------------------------------------------------------------------
    # AXIS I: Epistemic & Strategic Integrity
    # ------------------------------------------------------------------
    a1_checks: list[tuple[str, bool]] = []
    cite_ok = (len(ast.citations) >= 1) if form_id in ("production_brief", "leadership_report", "research_note") else True
    charter_clean = (
        not ca.get("lens_as_mandate_trap", False)
        and not ca.get("stale_prior_plan_trap", False)
        and not ca.get("vision_kpi_misuse", False)
    )
    source_charter_ok = cite_ok and charter_clean
    a1_checks.append(("source_and_charter_integrity", source_charter_ok))

    has_patronizing = bool(PATRONIZING_PHRASE_RE.search(text))
    has_unauth = bool(UNAUTHORIZED_RELEASE_RE.search(text))
    hold_owner_ok = float(fe.features.get("hold_owner_ratio", 1.0)) >= 0.75
    steward_ok = (not has_patronizing) and (not has_unauth) and hold_owner_ok
    a1_checks.append(("stewardship_boundary", steward_ok))

    order_ok = not any(v.startswith("evidence_order_inverted") for v in fe.violations)
    a1_checks.append(("epistemic_order", order_ok))

    a1_score = round(sum(1 for _, ok in a1_checks if ok) / len(a1_checks), 3)
    for name, ok in a1_checks:
        if not ok:
            failed_probes.append(name)
    details["axis_1"] = {
        "citations": len(ast.citations),
        "charter_clean": charter_clean,
        "patronizing_detected": has_patronizing,
        "unauthorized_release": has_unauth,
        "hold_owner_ratio": fe.features.get("hold_owner_ratio", 1.0),
    }

    # ------------------------------------------------------------------
    # AXIS II: Cognitive & Rhetorical Force
    # ------------------------------------------------------------------
    a2_checks: list[tuple[str, bool]] = []
    if form_id == "av_script":
        avg_ov = float(fe.features.get("avg_av_overlap", 0.0))
        max_beat = int(fe.features.get("max_beat_duration_s", 0))
        counterpoint_ok = avg_ov <= 0.45
        pacing_ok = (max_beat <= 90) if (target_duration_s is not None and target_duration_s >= 120) else True
        # Long-form A/B/C story presence heuristic (external task + human shift + library/service truth)
        if target_duration_s is not None and target_duration_s >= 120:
            has_human = bool(re.search(r"\b(patron|family|maria|host|kid|kids|grandfather|calgarians|people|someone|she|he|they)\b", lower))
            has_service = bool(re.search(r"\b(library|card|free|studio|station|specialist|booth|archive|book|reserve)\b", lower))
            abc_ok = has_human and has_service and len(ast.timecode_beats) >= 4
        else:
            abc_ok = len(ast.timecode_beats) >= 2
        a2_checks.append(("narrative_tension_and_counterpoint", counterpoint_ok and pacing_ok and abc_ok))
        details["av_narrative"] = {"avg_overlap": avg_ov, "max_beat_s": max_beat, "abc_ok": abc_ok}
    elif form_id in ("production_brief", "leadership_report"):
        dec_ok = not any(v.startswith("buried_decision") for v in fe.violations)
        a2_checks.append(("priority_hierarchy_decision_first", dec_ok))
    elif form_id == "treatment":
        prem_ok = not any(v.startswith("buried_premise") or v.startswith("missing_visual") for v in fe.violations)
        a2_checks.append(("narrative_tension_and_counterpoint", prem_ok))
    else:
        a2_checks.append(("structural_hook_clarity", True))

    # 4-Platform Native Divergence Check (YouTube / Instagram / LinkedIn / Facebook / Newsletter)
    plat_secs = _extract_platform_sections(text)
    max_plat_overlap = 0.0
    worst_pair = ""
    if len(plat_secs) >= 2:
        for (p1, t1), (p2, t2) in itertools.combinations(plat_secs.items(), 2):
            ov = _jaccard_overlap(t1, t2)
            if ov > max_plat_overlap:
                max_plat_overlap = ov
                worst_pair = f"{p1}_vs_{p2}"
        plat_ok = max_plat_overlap <= 0.55
        a2_checks.append(("platform_native_divergence", plat_ok))
        details["platform_divergence"] = {
            "platforms_found": sorted(plat_secs.keys()),
            "max_pairwise_overlap": max_plat_overlap,
            "worst_pair": worst_pair,
        }

    slop_ok = ast.slop_hits == 0
    a2_checks.append(("rhetoric_zero_slop", slop_ok))
    a2_score = round(sum(1 for _, ok in a2_checks if ok) / len(a2_checks), 3)
    for name, ok in a2_checks:
        if not ok:
            failed_probes.append(name)

    # ------------------------------------------------------------------
    # AXIS III: Operational & Portfolio Executability
    # ------------------------------------------------------------------
    a3_checks: list[tuple[str, bool]] = []
    if form_id == "av_script":
        timing_ok = (
            bool(fe.features.get("timecode_contiguous", False))
            and float(fe.features.get("avg_wpm", 999.0)) <= 155.0
            and float(fe.features.get("max_beat_wpm", 999.0)) <= 175.0
            and not any(v.startswith("duration_mismatch") for v in fe.violations)
        )
        a3_checks.append(("physical_timing_and_wpm", timing_ok))
        details["av_timing"] = {
            "contiguous": fe.features.get("timecode_contiguous", False),
            "avg_wpm": fe.features.get("avg_wpm", 0.0),
            "max_beat_wpm": fe.features.get("max_beat_wpm", 0.0),
            "total_duration_s": fe.features.get("total_duration_s", 0),
        }
    elif form_id in ("call_sheet", "shot_list", "content_calendar"):
        op_ok = fe.passed
        a3_checks.append(("operational_table_executability", op_ok))
    else:
        exec_ok = bd.buy_in_ready
        a3_checks.append(("stakeholder_executability", exec_ok))

    # Cold-receiver hold ownership check
    a3_checks.append(("owned_holds_actionable", hold_owner_ok))
    a3_score = round(sum(1 for _, ok in a3_checks if ok) / len(a3_checks), 3)
    for name, ok in a3_checks:
        if not ok:
            failed_probes.append(name)

    axes_map = {
        "axis_1_integrity": a1_score,
        "axis_2_rhetorical_force": a2_score,
        "axis_3_executability": a3_score,
    }
    weakest_axis = min(axes_map, key=lambda k: axes_map[k])
    min_axis = axes_map[weakest_axis]

    return RootAxisReport(
        form_id=form_id,
        axis_1_integrity=a1_score,
        axis_2_rhetorical_force=a2_score,
        axis_3_executability=a3_score,
        min_axis_score=min_axis,
        weakest_axis=weakest_axis,
        passed=(len(failed_probes) == 0),
        failed_probes=failed_probes,
        probe_details=details,
    )


def validate_ontology_closure(repo_root: Path) -> dict[str, Any]:
    """Mechanically verify unbroken L0 -> L1 -> L2 -> L3 -> L4 vertical closure with zero orphans."""
    path = Path(repo_root) / DEFAULT_ONTOLOGY_REL
    if not path.is_file():
        return {"ok": False, "errors": [f"missing ontology file: {path}"]}
    import yaml  # type: ignore

    raw = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or {}
    errors: list[str] = []
    l0 = raw.get("L0_root") or {}
    l1_list = raw.get("L1_axes") or []
    l2_list = raw.get("L2_engines") or []
    l3_list = raw.get("L3_sub_disciplines") or []
    l4_list = raw.get("L4_atomic_primitives") or []

    l0_id = l0.get("id", "")
    l1_ids = {x["id"] for x in l1_list if isinstance(x, dict) and x.get("id")}
    l2_ids = {x["id"] for x in l2_list if isinstance(x, dict) and x.get("id")}
    l3_ids = {x["id"] for x in l3_list if isinstance(x, dict) and x.get("id")}
    l4_ids = {x["id"] for x in l4_list if isinstance(x, dict) and x.get("id")}

    # Verify L0 -> L1
    if set(l0.get("governs_l1") or []) != l1_ids:
        errors.append("L0 governs_l1 does not exactly match L1_axes")
    for x in l1_list:
        if x.get("parent_l0") != l0_id:
            errors.append(f"L1 orphan parent: {x.get('id')}")

    # Verify L1 -> L2
    l1_children = {cid for x in l1_list for cid in (x.get("governs_l2") or [])}
    if l1_children != l2_ids:
        errors.append("L1 governs_l2 does not exactly match L2_engines")
    for x in l2_list:
        if x.get("parent_l1") not in l1_ids:
            errors.append(f"L2 orphan parent: {x.get('id')}")

    # Verify L2 -> L3
    l2_children = {cid for x in l2_list for cid in (x.get("governs_l3") or [])}
    if l2_children != l3_ids:
        errors.append("L2 governs_l3 does not exactly match L3_sub_disciplines")
    for x in l3_list:
        if x.get("parent_l2") not in l2_ids:
            errors.append(f"L3 orphan parent: {x.get('id')}")

    # Verify L3 -> L4 (every L3 has >= 1 L4 primitive, every L4 points to a valid L3 and has probe + forms)
    covered_l3: set[str] = set()
    covered_forms: set[str] = set()
    for x in l4_list:
        p3 = x.get("parent_l3")
        if p3 not in l3_ids:
            errors.append(f"L4 orphan parent: {x.get('id')} -> {p3}")
        else:
            covered_l3.add(p3)
        if not x.get("probe") or not x.get("forms"):
            errors.append(f"L4 incomplete binding: {x.get('id')}")
        for fm in x.get("forms") or []:
            covered_forms.add(str(fm))

    uncovered_l3 = sorted(l3_ids - covered_l3)
    if uncovered_l3:
        errors.append(f"L3 sub-disciplines with zero L4 primitives: {uncovered_l3}")

    return {
        "ok": len(errors) == 0,
        "l0_count": 1 if l0_id else 0,
        "l1_count": len(l1_ids),
        "l2_count": len(l2_ids),
        "l3_count": len(l3_ids),
        "l4_count": len(l4_ids),
        "forms_covered": sorted(covered_forms),
        "errors": errors,
    }


def verify_test_validity(repo_root: Path) -> dict[str, Any]:
    """Prove our 3-Axis tests are Red-Capable (catch every contract counterexample), ontology closed, AND clean on golden docs."""
    t0 = time.perf_counter()
    ontology = validate_ontology_closure(repo_root)
    contracts = load_axis_contracts(repo_root)
    ce_results: list[dict[str, Any]] = []
    ce_caught = 0
    ce_total = 0

    for axis_id, axis_cfg in (contracts.get("axes") or {}).items():
        for eng in axis_cfg.get("engines") or []:
            ce = eng.get("red_capable_counterexample")
            if not isinstance(ce, dict):
                continue
            ce_total += 1
            fid = str(ce["form_id"])
            expected_probe = str(ce["expected_failing_probe"])
            target_dur = ce.get("target_duration_s")
            rep = evaluate_root_axes(
                str(ce["text"]),
                fid,
                target_duration_s=target_dur,
                repo_root=repo_root,
            )
            caught = (not rep.passed) and (expected_probe in rep.failed_probes)
            if caught:
                ce_caught += 1
            ce_results.append(
                {
                    "axis_id": axis_id,
                    "engine_id": eng["id"],
                    "form_id": fid,
                    "expected_probe": expected_probe,
                    "caught": caught,
                    "failed_probes": rep.failed_probes,
                    "axis_scores": {
                        "I": rep.axis_1_integrity,
                        "II": rep.axis_2_rhetorical_force,
                        "III": rep.axis_3_executability,
                    },
                }
            )

    golden_passed = 0
    golden_failures: list[dict[str, Any]] = []
    for spec_id, spec in GOLDEN_SPECIMENS.items():
        rep = evaluate_root_axes(
            spec["text"],
            spec["form_id"],
            target_duration_s=spec.get("target_duration_s"),
            repo_root=repo_root,
        )
        if rep.passed:
            golden_passed += 1
        else:
            golden_failures.append({"specimen": spec_id, "failed_probes": rep.failed_probes})

    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
    ok = ontology["ok"] and (ce_caught == ce_total) and (golden_passed == len(GOLDEN_SPECIMENS)) and ce_total > 0
    return {
        "ok": ok,
        "elapsed_ms": elapsed_ms,
        "ontology": ontology,
        "counterexamples_caught": ce_caught,
        "counterexamples_total": ce_total,
        "golden_passed": golden_passed,
        "golden_total": len(GOLDEN_SPECIMENS),
        "counterexample_details": ce_results,
        "golden_failures": golden_failures,
    }
