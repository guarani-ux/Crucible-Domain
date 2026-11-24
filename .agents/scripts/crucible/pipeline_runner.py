#!/usr/bin/env python3
"""End-to-End 8-Stage Project Pipeline Runner & Cross-Document Parity Auditor.

Executes all 8 document types in real production dependency order for ONE defined
project and scope:
  1. research_note -> 2. treatment -> 3. production_brief -> 4. av_script ->
  5. shot_list -> 6. call_sheet -> 7. content_calendar -> 8. leadership_report

Each stage inherits compact digests of all prior stages, clears Gate 1 (Flow AST +
6-Role Board + 3-Axis Probes + Blind Holdouts) and optionally Gate 2 (Non-masking
3-Axis Adversarial Judgment + Paired A/B Outcome Ratchet), and finishes with a
deterministic Cross-Document Parity Audit across the entire 8-file package.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from .doc_flow_engine import (
    GOLDEN_SPECIMENS,
    MANDATE_LENS_TRAP_RE,
    UNAUTHORIZED_RELEASE_RE,
    evaluate_document_flow,
    evaluate_stakeholder_board,
    parse_document_ast,
)
from .form_diagnostics import FORM_PROFILES, diagnose_form_deliverable
from .judgment_panel import load_judgment_lessons, run_adversarial_judgment
from .lever_control import load_lever_registry, pull_lever
from .outcome_ratchet import get_active_promoted_lessons, record_paired_outcome
from .root_axis_engine import evaluate_root_axes
from .workload_bench import _build_agy_worker_prompt, _call_worker, _default_agy_worker, WorkloadProject

DEFAULT_PIPELINES_REL = Path(".agents") / "bench" / "pipelines.yaml"
DEFAULT_PIPELINE_TEL_REL = Path(".agents") / "bench_pipeline_telemetry.jsonl"


@dataclass
class StageResult:
    stage: int
    form_id: str
    filename: str
    gate: str
    passed: bool
    gate1_ok: bool
    gate2_verdict: str
    rubric_score: float
    flow_score: float
    board_score: float
    axis_scores: dict[str, float]
    blocking_roles: list[str]
    failed_probes: list[str]
    levers_pulled: list[str]
    retries_used: int
    elapsed_ms: float
    output_path: str
    error_summary: str = ""


@dataclass
class ParityReport:
    ok: bool
    checks_passed: int
    checks_total: int
    parity_score: float
    message_carry_score: float = 0.0
    cold_receiver_score: float = 0.0
    cold_receiver_rating: str = "BLOCKED"  # RUNNABLE_STANDALONE | NEEDS_CLARIFICATION | BLOCKED
    missing_outsider_info: list[str] = field(default_factory=list)
    violations: list[str] = field(default_factory=list)
    details: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_pipeline_manifest(repo_root: Path, manifest_path: Path | None = None) -> dict[str, Any]:
    """Load end-to-end pipeline stage order and project scopes from YAML."""
    path = manifest_path or (Path(repo_root) / DEFAULT_PIPELINES_REL)
    if not path.is_file():
        raise FileNotFoundError(f"Pipeline manifest not found: {path}")
    import yaml  # type: ignore

    raw = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or {}
    if not isinstance(raw, dict) or not raw.get("stage_order") or not raw.get("projects"):
        raise ValueError(f"Invalid pipeline manifest: {path}")
    return raw


def _summarize_upstream(stage_texts: dict[str, str], *, max_chars_each: int = 700) -> str:
    """Build a compact upstream context digest so stage k stays anchored to stages 1..k-1."""
    if not stage_texts:
        return ""
    parts = ["=== UPSTREAM CONTROLLING ARTIFACTS (YOU MUST STAY CONSISTENT WITH THESE) ==="]
    for fid, txt in stage_texts.items():
        snippet = txt.strip()[:max_chars_each]
        parts.append(f"--- Upstream [{fid}] ---\n{snippet}")
    return "\n\n".join(parts) + "\n"


def _synthesize_offline_stage(project_cfg: dict[str, Any], form_id: str) -> str:
    """Produce a coherent offline stage artifact tailored to project_cfg (0 LLM tokens, for dry-run & parity testing)."""
    title = project_cfg["title"]
    loc = project_cfg.get("primary_location", "Central Library")
    mandates = ", ".join(project_cfg.get("official_mandates", ["Experiences", "Technology"]))
    action = project_cfg.get("immediate_patron_action", "Book a free slot at calgarylibrary.ca.")
    dur = int(project_cfg.get("target_duration_s", 180))

    if form_id == "av_script":
        if dur >= 240:
            base = GOLDEN_SPECIMENS["av_script_5m"]["text"]
        elif dur >= 120:
            base = GOLDEN_SPECIMENS["av_script_3m"]["text"]
        elif dur >= 50:
            base = GOLDEN_SPECIMENS["av_script_1m"]["text"]
        else:
            base = GOLDEN_SPECIMENS["av_script_30s"]["text"]
        return (
            f"# A/V Script — {title}\n\n"
            f"Location: {loc} | Mandates: {mandates} | Patron Action: {action}\n"
            + "\n".join(base.splitlines()[2:])
            + "\n"
        )

    if form_id == "content_calendar":
        return (
            f"# 4-Platform Content Plan — {title}\n\n"
            f"Grounded in `Calgary Public Library/GROUND_TRUTH.md` under official 2027-2030 {mandates} mandates.\n"
            f"Goal: {action}\n\n"
            "## YouTube\n"
            f"Search-and-browse hero episode from {loc} with chapter retention resets and direct booking link in description.\n\n"
            "## Instagram\n"
            "Muted 15s vertical Reel: fast visual pattern interrupt, bold kinetic captions, save-for-weekend callout.\n\n"
            "## LinkedIn\n"
            f"Civic innovation note explaining how public library infrastructure under {mandates} lowers barriers for Calgarians.\n\n"
            "## Facebook\n"
            f"Neighborhood community post inviting Calgary families to visit {loc} this week with their free library card.\n\n"
            "## Newsletter\n"
            f"Warm plain-language feature blurb linking straight to {action}\n\n"
            "| Week | Channel | Deliverable | Owner | Status |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| Week 1 | YouTube | Master Episode | Producer | Hold: G06 pending — Owner: Communications Director |\n"
            "| Week 1 | Instagram | 15s Cutdown Reel | Digital Marketing | Draft (CHG-01 dependent) |\n"
            "| Week 2 | LinkedIn | Civic Insight Post | Communications | Pre-flight |\n"
            "| Week 2 | Facebook | Local Branch Post | Digital Marketing | Pre-flight |\n"
        )

    if form_id == "call_sheet":
        return (
            f"# Call Sheet — {title}\n\n"
            f"Date: 2026-12-03 | Location: {loc} | Call Time: 08:30\n"
            f"Mandates: {mandates} | Source: `Calgary Public Library/GROUND_TRUTH.md`\n\n"
            "| Role | Name | Call Time | Notes |\n"
            "| --- | --- | --- | --- |\n"
            f"| Director | [UNKNOWN — OWNER TO CONFIRM] | 08:30 | Owner: Media Production Manager ({loc}) |\n"
            "| Host | [UNKNOWN — OWNER TO CONFIRM] | 09:00 | Owner: Producer |\n"
            "| Camera Op | Assigned Crew | 08:30 | Bring lavalier + B-roll kit |\n"
        )

    if form_id == "shot_list":
        return (
            f"# Shot List — {title}\n\n"
            f"Location: {loc} | Mandates: {mandates}\n\n"
            "| Shot | Framing | Priority | Subject / Action | Duration |\n"
            "| --- | --- | --- | --- | --- |\n"
            f"| 01 | WS | Essential | Exterior & entry into {loc}, morning light | 00:05 |\n"
            "| 02 | MS | Essential | Host & patron set up at station | 00:08 |\n"
            "| 03 | CU | Essential | Hands interacting with gear; reaction cutaway | 00:06 |\n"
        )

    base = GOLDEN_SPECIMENS[form_id]["text"]
    return (
        f"# {form_id.replace('_', ' ').title()} — {title}\n"
        + "\n".join(base.splitlines()[1:])
        + f"\n\n> Scope Anchor: Location `{loc}` | Official 2027-2030 Mandates: {mandates} | Action: {action}\n"
    )


def audit_pipeline_parity(
    stage_texts: dict[str, str],
    project_cfg: dict[str, Any],
    *,
    repo_root: Path | None = None,
) -> ParityReport:
    """Deterministic Cross-Document Parity Audit across all 8 documents of one project (0 LLM tokens)."""
    violations: list[str] = []
    details: dict[str, Any] = {}
    checks_passed = 0
    checks_total = 0

    def _chk(ok: bool, msg: str) -> None:
        nonlocal checks_passed, checks_total
        checks_total += 1
        if ok:
            checks_passed += 1
        else:
            violations.append(msg)

    # 1. All 8 document types present
    expected_forms = [
        "research_note",
        "treatment",
        "production_brief",
        "av_script",
        "shot_list",
        "call_sheet",
        "content_calendar",
        "leadership_report",
    ]
    missing = [f for f in expected_forms if not stage_texts.get(f, "").strip()]
    _chk(len(missing) == 0, f"incomplete_pipeline_package: missing {missing}")

    # 2. Zero mandate-lens confusion or unauthorized G06/Asana claims across ANY document in the chain
    lens_leaks = [f for f, txt in stage_texts.items() if MANDATE_LENS_TRAP_RE.search(txt)]
    _chk(len(lens_leaks) == 0, f"mandate_lens_leak_across_chain: {lens_leaks}")

    unauth_leaks = [f for f, txt in stage_texts.items() if UNAUTHORIZED_RELEASE_RE.search(txt)]
    _chk(len(unauth_leaks) == 0, f"unauthorized_release_claim_in_chain: {unauth_leaks}")

    # 3. Official 2027-2030 mandate continuity across strategic docs
    req_mandates = [str(m) for m in project_cfg.get("official_mandates", [])]
    mandate_missing_in: list[str] = []
    for fid in ("production_brief", "av_script", "leadership_report"):
        txt = stage_texts.get(fid, "")
        if req_mandates and not any(re.search(rf"\b{re.escape(m)}\b", txt) for m in req_mandates):
            mandate_missing_in.append(fid)
    _chk(
        len(mandate_missing_in) == 0,
        f"mandate_continuity_break: required {req_mandates} missing in {mandate_missing_in}",
    )

    # 4. Runtime parity: av_script timecodes match declared target_duration_s (+/-20%)
    target_dur = int(project_cfg.get("target_duration_s", 0))
    av_txt = stage_texts.get("av_script", "")
    av_ast = parse_document_ast(av_txt)
    if target_dur > 0 and av_ast.timecode_beats:
        actual_dur = av_ast.timecode_beats[-1].end_s - av_ast.timecode_beats[0].start_s
        dur_ok = (target_dur * 0.80) <= actual_dur <= (target_dur * 1.20)
        details["runtime_parity"] = {"target_s": target_dur, "actual_s": actual_dur}
        _chk(dur_ok, f"runtime_parity_mismatch: av_script={actual_dur}s vs project target={target_dur}s")
    elif target_dur > 0:
        _chk(False, "runtime_parity_mismatch: av_script missing contiguous timecode beats")

    # 5. Location & cast/role parity between production ops docs (shot_list / call_sheet)
    primary_loc = str(project_cfg.get("primary_location", "")).strip()
    loc_key_tokens = [t.lower() for t in re.findall(r"[A-Za-z]{4,}", primary_loc) if t.lower() not in ("library", "branch")][:2]
    if loc_key_tokens:
        cs_low = stage_texts.get("call_sheet", "").lower()
        sl_low = stage_texts.get("shot_list", "").lower()
        loc_ok = any(tok in cs_low for tok in loc_key_tokens) and any(tok in sl_low for tok in loc_key_tokens)
        _chk(loc_ok, f"location_parity_break: '{primary_loc}' not reflected across both shot_list and call_sheet")

    # 6. Hold custody continuity: open holds in production_brief stay acknowledged in leadership_report
    pb_ast = parse_document_ast(stage_texts.get("production_brief", ""))
    lr_ast = parse_document_ast(stage_texts.get("leadership_report", ""))
    holds_ok = (pb_ast.hold_count == 0) or (lr_ast.hold_count >= 1 and lr_ast.holds_with_owner >= 1)
    _chk(
        holds_ok,
        f"hold_custody_dropped: production_brief has {pb_ast.hold_count} hold(s), leadership_report has {lr_ast.hold_count} ({lr_ast.holds_with_owner} owned)",
    )

    # 7. 4-Platform native divergence in content_calendar
    cc_txt = stage_texts.get("content_calendar", "")
    cc_axes = evaluate_root_axes(cc_txt, "content_calendar", repo_root=repo_root)
    plat_ok = "platform_native_divergence" not in cc_axes.failed_probes
    details["content_calendar_axes"] = cc_axes.to_dict()
    _chk(plat_ok, "platform_copy_paste_detected_in_content_calendar")

    # 8. Message Carry-Through Rating (does the project's core patron action & theme survive across stages?)
    action_tokens = {
        t
        for t in re.findall(r"[a-z]{4,}", str(project_cfg.get("immediate_patron_action", "")).lower())
        if t not in ("with", "from", "that", "this", "your", "free", "book", "slot", "library")
    } | {m.lower() for m in req_mandates}
    carry_stages = ("research_note", "treatment", "production_brief", "av_script", "content_calendar", "leadership_report")
    carried_count = 0
    dropped_stages: list[str] = []
    for fid in carry_stages:
        txt_low = stage_texts.get(fid, "").lower()
        if txt_low and (not action_tokens or any(tok in txt_low for tok in action_tokens)):
            carried_count += 1
        else:
            dropped_stages.append(fid)
    message_carry_score = round(carried_count / len(carry_stages), 3)
    details["message_carry"] = {"carried_stages": carried_count, "total_stages": len(carry_stages), "dropped_stages": dropped_stages}
    _chk(message_carry_score >= 0.80, f"message_carry_drop: core theme/mandate dropped in {dropped_stages}")

    # 9. Cold-Receiver Standalone Executability Rating (can an outsider run the whole project from these 8 docs alone?)
    missing_outsider_info: list[str] = []
    outsider_pillars: list[tuple[str, bool, str]] = [
        (
            "who_owns_holds",
            pb_ast.hold_count >= 1
            and pb_ast.holds_with_owner == pb_ast.hold_count
            and lr_ast.holds_with_owner >= 1,
            "Named accountable owners missing on open holds (production_brief / leadership_report)",
        ),
        (
            "what_specs_and_runtime",
            bool(av_ast.timecode_beats)
            and len(parse_document_ast(stage_texts.get("shot_list", "")).tables) >= 1
            and len(parse_document_ast(stage_texts.get("production_brief", "")).tables) >= 1,
            "Deliverables specs table, timed A/V beats, or shot list table missing",
        ),
        (
            "where_and_when_capture",
            bool(re.search(r"\b(call time|date)\b", stage_texts.get("call_sheet", ""), re.IGNORECASE))
            and bool(re.search(r"\b(location|branch|central)\b", stage_texts.get("call_sheet", ""), re.IGNORECASE)),
            "Call sheet missing concrete date, call time, or shoot location",
        ),
        (
            "how_rollout_and_g06_hold",
            plat_ok
            and bool(re.search(r"\b(g06|hold|pending|ch-04|chg-01)\b", cc_txt, re.IGNORECASE)),
            "Content calendar missing 4-platform native copy or explicit G06/CH-04 release hold",
        ),
        (
            "why_evidence_and_decision",
            len(parse_document_ast(stage_texts.get("research_note", "")).citations) >= 1
            and bool(re.search(r"\b(decision|recommend|approve)\b", stage_texts.get("leadership_report", "")[:400], re.IGNORECASE)),
            "Research source citations or top-of-page executive decision missing",
        ),
    ]
    outsider_passed = 0
    for _key, ok_p, gap_msg in outsider_pillars:
        if ok_p:
            outsider_passed += 1
        else:
            missing_outsider_info.append(gap_msg)
    cold_receiver_score = round(outsider_passed / len(outsider_pillars), 3)
    if cold_receiver_score >= 0.99 and len(violations) == 0:
        cold_receiver_rating = "RUNNABLE_STANDALONE"
    elif cold_receiver_score >= 0.60:
        cold_receiver_rating = "NEEDS_CLARIFICATION"
    else:
        cold_receiver_rating = "BLOCKED"
    _chk(
        cold_receiver_score >= 0.80,
        f"cold_receiver_not_standalone: outsider missing {missing_outsider_info[:2]}",
    )

    score = round(checks_passed / max(1, checks_total), 3)
    return ParityReport(
        ok=(len(violations) == 0),
        checks_passed=checks_passed,
        checks_total=checks_total,
        parity_score=score,
        message_carry_score=message_carry_score,
        cold_receiver_score=cold_receiver_score,
        cold_receiver_rating=cold_receiver_rating,
        missing_outsider_info=missing_outsider_info,
        violations=violations,
        details=details,
    )


def run_end_to_end_pipeline(
    repo_root: Path,
    *,
    project_id: str | None = None,
    mode: str = "agy_live",
    enable_judgment_gate: bool = True,
    max_retries: int = 1,
    timeout_s: float = 180.0,
    progress_fn: Callable[[str], None] | None = None,
    agy_worker_fn: Callable[..., tuple[bool, str]] | None = None,
    judge_worker_fn: Callable[..., tuple[bool, str]] | None = None,
    manifest_path: Path | None = None,
) -> dict[str, Any]:
    """Run all 8 document types in dependency order for ONE defined project and scope."""
    t0 = time.perf_counter()
    root = Path(repo_root).resolve()
    manifest = load_pipeline_manifest(root, manifest_path=manifest_path)
    projects = manifest["projects"]
    if project_id:
        matches = [p for p in projects if p["id"] == project_id]
        if not matches:
            raise ValueError(f"Unknown pipeline project '{project_id}'. Available: {[p['id'] for p in projects]}")
        project_cfg = matches[0]
    else:
        project_cfg = projects[0]

    run_stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    run_id = f"pipe_{run_stamp}_{hashlib.sha256(str(time.time_ns()).encode()).hexdigest()[:6]}"
    out_dir = root / ".agents" / "bench_runs" / f"{run_id}_{project_cfg['id']}"
    out_dir.mkdir(parents=True, exist_ok=True)

    worker = agy_worker_fn or _default_agy_worker
    j_worker = judge_worker_fn or worker
    target_dur = int(project_cfg.get("target_duration_s", 180))
    stage_texts: dict[str, str] = {}
    stage_results: list[StageResult] = []
    quota_hit = False

    def _emit(msg: str) -> None:
        if progress_fn is not None:
            progress_fn(msg)

    _emit(
        f"Crucible End-to-End 8-Stage Pipeline START: project={project_cfg['id']} | "
        f"runtime={target_dur}s | mode={mode} | gate2={enable_judgment_gate and mode != 'offline'}"
    )

    for st in manifest["stage_order"]:
        stage_num = int(st["stage"])
        form_id = str(st["form_id"])
        filename = str(st["filename"])
        gate_label = str(st["gate"])
        role_focus = str(st["role_focus"])
        t_st = time.perf_counter()

        if quota_hit:
            stage_results.append(
                StageResult(
                    stage=stage_num,
                    form_id=form_id,
                    filename=filename,
                    gate=gate_label,
                    passed=False,
                    gate1_ok=False,
                    gate2_verdict="SKIPPED",
                    rubric_score=0.0,
                    flow_score=0.0,
                    board_score=0.0,
                    axis_scores={},
                    blocking_roles=[],
                    failed_probes=[],
                    levers_pulled=[],
                    retries_used=0,
                    elapsed_ms=0.0,
                    output_path="",
                    error_summary="skipped after HTTP 429 quota circuit breaker",
                )
            )
            continue

        _emit(f"  [Stage {stage_num}/8 | {gate_label}] START {form_id} ({filename}) ...")

        eff_dur = target_dur if form_id == "av_script" else None
        max_attempts = 1 if mode == "offline" else (1 + max(0, max_retries))
        retries_used = 0
        feedback_suffix = ""
        levers_pulled: list[str] = []
        candidate_text = ""
        gate1_ok = False
        gate2_verdict = "OFFLINE_SKIPPED" if mode == "offline" else ("SKIPPED" if not enable_judgment_gate else "PENDING")
        err_summary = ""
        rubric_score = 0.0
        flow_score = 0.0
        board_score = 0.0
        axis_scores: dict[str, float] = {}
        blocking_roles: list[str] = []
        failed_probes: list[str] = []

        for attempt in range(max_attempts):
            if attempt > 0:
                retries_used += 1
                _emit(f"    -> repair retry ({attempt}/{max_attempts - 1}) for {form_id}...")

            if mode == "offline":
                ok_gen = True
                candidate_text = _synthesize_offline_stage(project_cfg, form_id)
            else:
                upstream_digest = _summarize_upstream(stage_texts)
                proj_obj = WorkloadProject(
                    id=f"{project_cfg['id']}:{form_id}",
                    domain=str(project_cfg.get("domain", "cpl_research")),
                    mode="agy_live",
                    form=form_id,
                    intent=(
                        f"Project: {project_cfg['title']}\n"
                        f"Scope: {project_cfg['scope_summary']}\n"
                        f"Primary Location: {project_cfg.get('primary_location', '')}\n"
                        f"Official 2027-2030 Mandates: {', '.join(project_cfg.get('official_mandates', []))}\n"
                        f"Target A/V Runtime: {target_dur}s\n"
                        f"Immediate Patron Action: {project_cfg.get('immediate_patron_action', '')}\n"
                        f"Stage {stage_num}/8 ({gate_label}) Focus: {role_focus}"
                    ),
                    deliverable=filename,
                )
                ratchet_lessons = get_active_promoted_lessons(root, form_id) or load_judgment_lessons(root, form_id)
                base_prompt = _build_agy_worker_prompt(
                    proj_obj,
                    form_id=form_id,
                    judgment_lessons=ratchet_lessons,
                )
                full_prompt = base_prompt + "\n" + upstream_digest + feedback_suffix
                effort = "high" if attempt > 0 else "medium"
                ok_gen, candidate_text = _call_worker(worker, full_prompt, root, timeout_s, effort)

            if not ok_gen:
                low_err = candidate_text.lower()
                if "resource_exhausted" in low_err or "code 429" in low_err or "quota reached" in low_err:
                    quota_hit = True
                    err_summary = f"quota_exhausted: {candidate_text[:160]}"
                    _emit("  [CIRCUIT BREAKER] Cloud quota exhausted (HTTP 429). Stopping pipeline cleanly.")
                    break
                err_summary = candidate_text[:200]
                feedback_suffix = "\nPrevious attempt failed to produce Markdown; emit clean Markdown only.\n"
                continue

            # Gate 1: Rubric + Flow AST + 6-Role Board + 3-Axis Root Probes
            diag = diagnose_form_deliverable(
                candidate_text,
                form_id,
                repo_root=root,
                strict_cpl_mandates=str(project_cfg.get("domain", "")).startswith("cpl"),
            )
            fe = evaluate_document_flow(candidate_text, form_id, target_duration_s=eff_dur)
            bd = evaluate_stakeholder_board(
                candidate_text, form_id, flow_eval=fe, target_duration_s=eff_dur, repo_root=root
            )
            ax = evaluate_root_axes(candidate_text, form_id, target_duration_s=eff_dur, repo_root=root)

            rubric_score = diag.overall_score
            flow_score = fe.flow_score
            board_score = bd.board_score
            blocking_roles = list(bd.blocking_roles)
            failed_probes = list(ax.failed_probes)
            axis_scores = {
                "axis_1_integrity": ax.axis_1_integrity,
                "axis_2_rhetorical_force": ax.axis_2_rhetorical_force,
                "axis_3_executability": ax.axis_3_executability,
            }
            gate1_ok = fe.passed and bd.buy_in_ready and ax.passed

            if not gate1_ok:
                rec_levers = list(dict.fromkeys(fe.recommended_levers + bd.recommended_levers))
                reg = load_lever_registry(root)
                for lv in rec_levers[:2]:
                    if lv in reg:
                        pull_lever(root, lv, form_id=form_id, reason=f"pipeline:{project_cfg['id']}:s{stage_num}")
                        if lv not in levers_pulled:
                            levers_pulled.append(lv)
                err_summary = f"Gate 1 failed: blocking_roles={blocking_roles}, probes={failed_probes}, violations={fe.violations[:2]}"
                feedback_suffix = f"\nMANDATORY REPAIR: {err_summary}. Apply levers {rec_levers[:3]}.\n"
                continue

            # Gate 2: Independent Adversarial 3-Axis Judgment Panel + Paired A/B Ratchet
            if mode != "offline" and enable_judgment_gate:
                _emit(f"    -> Gate 2 adversarial 3-axis judgment ({form_id})...")
                jv = run_adversarial_judgment(
                    candidate_text,
                    form_id,
                    repo_root=root,
                    worker_fn=j_worker,
                    timeout_s=min(90.0, timeout_s),
                    use_case_intent=role_focus,
                    persist_lesson=True,
                )
                gate2_verdict = jv.verdict
                if jv.verdict == "UNAVAILABLE":
                    low_j = jv.raw_error.lower()
                    if "resource_exhausted" in low_j or "code 429" in low_j or "quota reached" in low_j:
                        quota_hit = True
                        err_summary = f"quota_exhausted: {jv.raw_error[:160]}"
                        break
                    err_summary = f"Gate 2 unavailable: {jv.raw_error[:160]}"
                    continue

                axis_scores = dict(jv.axis_scores)
                record_paired_outcome(
                    root,
                    form_id=form_id,
                    use_case_id=project_cfg["id"],
                    axis_scores=jv.axis_scores,
                    verdict=jv.verdict,
                    weakest_engine=jv.weakest_engine,
                    proposed_lesson=jv.reusable_judgment_lesson,
                )
                if not jv.ok:
                    err_summary = (
                        f"Gate 2 {jv.verdict} (j={jv.judgment_score:.2f} axes={jv.axis_scores}): "
                        f"objection='{jv.top_executive_objection[:100]}' | fix='{jv.actionable_fix[:100]}'"
                    )
                    feedback_suffix = f"\nMANDATORY GATE 2 REPAIR: {err_summary}. Cut: {jv.required_cut}\n"
                    continue
                err_summary = ""
                break
            else:
                err_summary = ""
                break

        stage_passed = gate1_ok and (mode == "offline" or (not enable_judgment_gate) or gate2_verdict == "SIGN_OFF")
        out_file = out_dir / filename
        out_rel = ""
        if candidate_text:
            out_file.write_text(candidate_text, encoding="utf-8", newline="\n")
            stage_texts[form_id] = candidate_text
            out_rel = str(out_file.relative_to(root) if out_file.is_relative_to(root) else out_file).replace("\\", "/")

        st_ms = round((time.perf_counter() - t_st) * 1000.0, 2)
        sr = StageResult(
            stage=stage_num,
            form_id=form_id,
            filename=filename,
            gate=gate_label,
            passed=stage_passed,
            gate1_ok=gate1_ok,
            gate2_verdict=gate2_verdict,
            rubric_score=rubric_score,
            flow_score=flow_score,
            board_score=board_score,
            axis_scores=axis_scores,
            blocking_roles=blocking_roles,
            failed_probes=failed_probes,
            levers_pulled=levers_pulled,
            retries_used=retries_used,
            elapsed_ms=st_ms,
            output_path=out_rel,
            error_summary=err_summary,
        )
        stage_results.append(sr)
        _emit(
            f"  [Stage {stage_num}/8] {form_id:<18} {'PASS' if sr.passed else 'FAIL'} in {st_ms / 1000.0:.1f}s | "
            f"flow={flow_score:.2f} board={board_score:.2f} gate2={gate2_verdict} -> {out_rel}"
            + (f" ({err_summary[:100]})" if err_summary else "")
        )

    parity = audit_pipeline_parity(stage_texts, project_cfg, repo_root=root)
    stages_passed = sum(1 for s in stage_results if s.passed)
    overall_ok = (stages_passed == len(stage_results)) and parity.ok and (not quota_hit)
    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)

    result = {
        "ok": overall_ok,
        "run_id": run_id,
        "project_id": project_cfg["id"],
        "project_title": project_cfg["title"],
        "mode": mode,
        "quota_exhausted": quota_hit,
        "elapsed_ms": elapsed_ms,
        "output_dir": str(out_dir.relative_to(root) if out_dir.is_relative_to(root) else out_dir).replace("\\", "/"),
        "stages_passed": stages_passed,
        "stages_total": len(stage_results),
        "parity": parity.to_dict(),
        "stages": [asdict(s) for s in stage_results],
    }

    tel_path = root / DEFAULT_PIPELINE_TEL_REL
    tel_path.parent.mkdir(parents=True, exist_ok=True)
    with tel_path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(
            json.dumps(
                {
                    "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                    "run_id": run_id,
                    "project_id": project_cfg["id"],
                    "mode": mode,
                    "ok": overall_ok,
                    "stages_passed": stages_passed,
                    "stages_total": len(stage_results),
                    "parity_score": parity.parity_score,
                    "parity_violations": parity.violations,
                    "elapsed_ms": elapsed_ms,
                },
                ensure_ascii=False,
            )
            + "\n"
        )
    return result
