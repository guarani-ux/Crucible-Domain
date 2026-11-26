#!/usr/bin/env python3
"""Bidirectional Sensemaking Graph Compiler (Upstream Generative Core -> Medium Projection).

Turns the L0->L4 Sensemaking Ontology bidirectional: instead of jumping straight from a flat prompt
to raw Markdown prose, builds and validates an explicit 3-node upstream Sensemaking Graph:
  1. reality_and_custody   (verified facts, 2027-2030 mandates, service promise, owned holds, citations)
  2. belief_delta_matrix   (current skepticism -> target state -> shift trigger per stakeholder & patron)
  3. causal_spine          (hook gap, A/B/C story tracks, But/Therefore Visual-First beats or SCQA options)

Validates all platform physics (YouTube/Instagram/LinkedIn/Facebook/Live) and length architectures
(15s/30s/45s/60s/180s/300s) upstream in <2ms, then projects into a clean 2-zone Markdown deliverable
(Clean Stakeholder Surface + Internal Custody & Sources appendix).
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from .doc_flow_engine import (
    _jaccard_overlap,
    evaluate_document_flow,
    evaluate_stakeholder_board,
    has_mandate_lens_trap,
    load_organization_charter,
)
from .form_diagnostics import FORM_PROFILES
from .outcome_ratchet import get_active_promoted_lessons, record_paired_outcome
from .root_axis_engine import evaluate_root_axes

DEFAULT_PROTOCOLS_REL = Path(".agents") / "bench" / "craft_protocols.yaml"
DEFAULT_DOMAIN_FACTS_REL = Path(".agents") / "bench" / "domain_facts.yaml"

INTERNAL_LEAK_TOKENS = ("#L", ".agents/", "BENCH_CANDIDATE")
UNVERIFIED_PRICE_RE = re.compile(r"\$\d+(?:\.\d{2})?(?:\s*[-–]\s*\$?\d+)?(?:\s*(?:per|a)\s+\w+)?", re.IGNORECASE)
BROCHURE_SLOP_RE = re.compile(
    r"\b(full custody of|magnetic ink|saved in minutes|in today'?s fast-paced|delve into|synergy|game-?changer|transformative journey|unlock the power)\b",
    re.IGNORECASE,
)


@dataclass
class GraphValidationReport:
    ok: bool
    form_id: str
    platform: str
    target_duration_s: int
    graph_score: float
    checks_passed: int
    checks_total: int
    violations: list[str] = field(default_factory=list)
    failed_l3_nodes: list[str] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_craft_protocols(repo_root: Path) -> dict[str, Any]:
    """Load the versioned upstream Craft Protocols YAML."""
    path = Path(repo_root) / DEFAULT_PROTOCOLS_REL
    if not path.is_file():
        return {"version": "0.0.0", "platform_physics": {}, "av_length_architectures": {}, "form_protocols": {}}
    import yaml  # type: ignore

    raw = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or {}
    return raw if isinstance(raw, dict) else {}


def _resolve_length_arch(protocols: dict[str, Any], target_duration_s: int) -> dict[str, Any]:
    archs = protocols.get("av_length_architectures") or {}
    # Pick closest defined length key
    keys = sorted(int(k) for k in archs.keys()) if archs else []
    if not keys:
        return {"min_beats": 3, "max_wpm": 150, "require_abc_tracks": target_duration_s >= 60, "require_but_therefore": target_duration_s >= 30, "max_beat_s": 60}
    best_k = min(keys, key=lambda k: abs(k - target_duration_s))
    return dict(archs.get(best_k) or archs.get(str(best_k)) or {})


def validate_sensemaking_graph(
    graph: dict[str, Any],
    *,
    form_id: str = "av_script",
    platform: str = "youtube",
    target_duration_s: int = 180,
    repo_root: Path | None = None,
    strict_wpm_floor: bool = False,
) -> GraphValidationReport:
    """Mechanically validate an upstream Sensemaking Graph BEFORE rendering prose (0 LLM tokens)."""
    protocols = load_craft_protocols(repo_root) if repo_root else {}
    plat_cfg = (protocols.get("platform_physics") or {}).get(platform.lower(), {})
    len_cfg = _resolve_length_arch(protocols, target_duration_s)

    violations: list[str] = []
    failed_l3: list[str] = []
    metrics: dict[str, Any] = {}
    passed = 0
    total = 0

    def _chk(ok: bool, msg: str, l3_node: str) -> None:
        nonlocal passed, total
        total += 1
        if ok:
            passed += 1
        else:
            violations.append(msg)
            if l3_node and l3_node not in failed_l3:
                failed_l3.append(l3_node)

    # 1. Node 1: reality_and_custody
    rc = graph.get("reality_and_custody") if isinstance(graph.get("reality_and_custody"), dict) else {}
    mandates = [str(m) for m in (rc.get("official_mandates") or [])]
    valid_mandates = {"Collections", "Experiences", "Expertise", "Spaces", "Technology"}
    mandate_ok = bool(mandates) and all(m in valid_mandates for m in mandates) and not has_mandate_lens_trap(" ".join(mandates))
    _chk(mandate_ok, f"invalid_or_missing_mandates: {mandates}", "L3:STRATEGIC_CHARTER_AND_TRADEOFFS")

    holds = rc.get("owned_holds") or []
    holds_ok = (
        isinstance(holds, list)
        and len(holds) >= 1
        and all(
            isinstance(h, dict)
            and str(h.get("item", "")).strip()
            and str(h.get("owner", "")).strip().lower() not in ("", "tbd", "unknown", "none")
            for h in holds
        )
    )
    _chk(holds_ok, "unowned_or_missing_holds_in_graph", "L3:FIELD_FEASIBILITY_AND_CUSTODY")

    cites = [str(c) for c in (rc.get("source_citations") or []) if str(c).strip()]
    _chk(len(cites) >= 1, "missing_source_citations_in_graph", "L3:SOURCE_PROVENANCE_AND_EVIDENCE")
    _chk(bool(str(rc.get("service_promise", "")).strip()), "missing_service_promise_in_graph", "L3:STRATEGIC_CHARTER_AND_TRADEOFFS")

    # 2. Node 2: belief_delta_matrix
    bdm = graph.get("belief_delta_matrix") or []
    bdm_ok = (
        isinstance(bdm, list)
        and len(bdm) >= 3
        and all(
            isinstance(row, dict)
            and str(row.get("role", "")).strip()
            and str(row.get("current_skepticism", "")).strip()
            and str(row.get("target_state", "")).strip()
            and str(row.get("shift_trigger", "")).strip()
            for row in bdm
        )
    )
    _chk(bdm_ok, "incomplete_belief_delta_matrix (need >=3 roles with skepticism -> target -> trigger)", "L3:RHETORICAL_PERSUASION_AND_PSYCHOLOGY")

    # 3. Node 3: creative_modality & intention_to_outcome (non-formulaic upstream creative strategy)
    cm = graph.get("creative_modality") if isinstance(graph.get("creative_modality"), dict) else {}
    if cm:
        cm_ok = all(
            bool(str(cm.get(k, "")).strip())
            for k in ("audio_strategy", "visual_rhythm_strategy", "intention_to_outcome_contract")
        )
        _chk(cm_ok, "incomplete_creative_modality_or_intention_outcome_contract", "L3:HOOK_AND_TENSION_MECHANICS")

    # 4. Node 4: causal_spine
    cs = graph.get("causal_spine") if isinstance(graph.get("causal_spine"), dict) else {}

    if form_id == "av_script":
        _chk(bool(str(cs.get("hook_gap", "")).strip()), "missing_hook_gap", "L3:HOOK_AND_TENSION_MECHANICS")
        beats = cs.get("beats") or []
        min_beats = int(len_cfg.get("min_beats", 3))
        max_wpm = float(len_cfg.get("max_wpm", 150))
        max_beat_s = int(len_cfg.get("max_beat_s", 60))
        req_abc = bool(len_cfg.get("require_abc_tracks", target_duration_s >= 60))
        req_bt = bool(len_cfg.get("require_but_therefore", target_duration_s >= 30))
        muted_first = bool(plat_cfg.get("muted_first", False))

        _chk(isinstance(beats, list) and len(beats) >= min_beats, f"too_few_beats: {len(beats)} < {min_beats}", "L3:HOOK_AND_TENSION_MECHANICS")

        contiguous = True
        prev_end = -1
        total_audio_words = 0
        overlaps: list[float] = []
        max_beat_wpm = 0.0
        longest_beat = 0
        causal_tags: set[str] = set()
        captioned_beats = 0
        surface_leaks = 0

        for b in beats if isinstance(beats, list) else []:
            if not isinstance(b, dict):
                contiguous = False
                continue
            s_s = int(b.get("start_s", -1))
            e_s = int(b.get("end_s", -1))
            dur = e_s - s_s
            if s_s < 0 or dur <= 0 or (prev_end >= 0 and s_s < prev_end):
                contiguous = False
            prev_end = e_s
            longest_beat = max(longest_beat, dur)

            spoken = str(b.get("spoken_beat", "")).strip()
            visual = str(b.get("visual_first_action", "")).strip()
            caption = str(b.get("muted_caption", "")).strip()
            causal_tags.add(str(b.get("causal_link", "")).strip().upper())

            w_cnt = len(re.findall(r"\b[\w'-]+\b", spoken))
            total_audio_words += w_cnt
            bwpm = (w_cnt / dur) * 60.0 if dur > 0 else 999.0
            max_beat_wpm = max(max_beat_wpm, bwpm)
            overlaps.append(_jaccard_overlap(spoken, visual))
            if caption:
                captioned_beats += 1
            if any(tok in spoken or tok in visual or tok in caption for tok in INTERNAL_LEAK_TOKENS):
                surface_leaks += 1

        total_dur = (int(beats[-1].get("end_s", 0)) - int(beats[0].get("start_s", 0))) if (isinstance(beats, list) and beats) else 0
        avg_wpm = round((total_audio_words / total_dur) * 60.0, 1) if total_dur > 0 else 0.0
        avg_ov = round(sum(overlaps) / len(overlaps), 3) if overlaps else 1.0

        metrics.update(
            {
                "beat_count": len(beats) if isinstance(beats, list) else 0,
                "total_duration_s": total_dur,
                "avg_wpm": avg_wpm,
                "max_beat_wpm": round(max_beat_wpm, 1),
                "avg_av_overlap": avg_ov,
                "longest_beat_s": longest_beat,
                "causal_tags": sorted(causal_tags),
                "captioned_ratio": round(captioned_beats / max(1, len(beats)), 2) if isinstance(beats, list) else 0.0,
            }
        )

        _chk(contiguous and total_dur > 0, "non_contiguous_beat_timestamps", "L3:FIELD_FEASIBILITY_AND_CUSTODY")
        _chk(
            (target_duration_s * 0.90) <= total_dur <= (target_duration_s * 1.10),
            f"runtime_mismatch_strict: {total_dur}s outside +/-10% of target {target_duration_s}s",
            "L3:FIELD_FEASIBILITY_AND_CUSTODY",
        )
        _chk(
            avg_wpm <= min(max_wpm, 145.0) and max_beat_wpm <= 155.0,
            f"wpm_exceeded_strict: avg={avg_wpm} (<=145), max_beat={max_beat_wpm:.1f} (<=155)",
            "L3:PLATFORM_AND_AV_MEDIUM_PHYSICS",
        )
        if strict_wpm_floor and target_duration_s >= 30:
            _chk(
                avg_wpm >= 95.0,
                f"fake_runtime_stretch_wpm_too_low: avg={avg_wpm} WPM (<95 WPM floor for {target_duration_s}s)",
                "L3:PLATFORM_AND_AV_MEDIUM_PHYSICS",
            )
        _chk(avg_ov <= 0.30, f"visual_first_counterpoint_strict: overlap={avg_ov:.2f} (>0.30)", "L3:PLATFORM_AND_AV_MEDIUM_PHYSICS")
        _chk(longest_beat <= max(max_beat_s, int(plat_cfg.get("retention_reset_max_s", 90))), f"beat_too_long_for_platform: {longest_beat}s", "L3:HOOK_AND_TENSION_MECHANICS")
        _chk(surface_leaks == 0, f"internal_jargon_leaked_into_script_surface: {surface_leaks}", "L3:POLITICAL_STEWARDSHIP_AND_AUTHORITY")

        # Strict spoken-ear prosody: Beat 1 hook window, nominalization density <= 12%, breath-length sentences <= 16 words
        beat1_dur = (int(beats[0].get("end_s", 0)) - int(beats[0].get("start_s", 0))) if (isinstance(beats, list) and beats and isinstance(beats[0], dict)) else 999
        max_hook_s = 6 if platform.lower() == "instagram" else (15 if target_duration_s <= 60 else 30)
        _chk(beat1_dur <= max_hook_s, f"slow_opening_hook: beat1={beat1_dur}s (limit <={max_hook_s}s for {platform})", "L3:HOOK_AND_TENSION_MECHANICS")

        all_spoken = " ".join(str(b.get("spoken_beat", "")) for b in (beats if isinstance(beats, list) else []) if isinstance(b, dict))
        spoken_words_list = re.findall(r"[a-zA-Z]+", all_spoken)
        nom_hits = sum(1 for w in spoken_words_list if len(w) >= 8 and re.search(r"(tion|sion|ment|ity|ance|ence)$", w.lower()))
        nom_ratio = round(nom_hits / max(1, len(spoken_words_list)), 3)
        _chk(nom_ratio <= 0.12, f"bureaucratic_nominalizations: {nom_ratio:.1%} (>12% limit)", "L3:PLATFORM_AND_AV_MEDIUM_PHYSICS")

        spoken_sents = [s.strip() for s in re.split(r"[.!?]+", all_spoken) if len(s.strip()) > 2]
        avg_spoken_sent = round(sum(len(re.findall(r"\b[\w'-]+\b", s)) for s in spoken_sents) / max(1, len(spoken_sents)), 1)
        _chk(avg_spoken_sent <= 16.5, f"long_unbreathable_sentences: avg={avg_spoken_sent} words (limit <=16.5)", "L3:PLATFORM_AND_AV_MEDIUM_PHYSICS")
        _chk(not UNVERIFIED_PRICE_RE.search(all_spoken), "unverified_competitor_or_dollar_claim_in_spoken_copy", "L3:SOURCE_PROVENANCE_AND_EVIDENCE")
        _chk(not BROCHURE_SLOP_RE.search(all_spoken), "brochure_slop_or_factual_cliche_in_spoken_copy", "L3:RHETORICAL_PERSUASION_AND_PSYCHOLOGY")
        metrics["nominalization_ratio"] = nom_ratio
        metrics["avg_spoken_sentence_words"] = avg_spoken_sent
        metrics["beat1_duration_s"] = beat1_dur

        if req_bt:
            bt_ok = ("BUT" in causal_tags) and ("THEREFORE" in causal_tags)
            _chk(bt_ok, f"missing_but_therefore_causality: tags={sorted(causal_tags)}", "L3:HOOK_AND_TENSION_MECHANICS")

        if req_abc:
            abc_ok = all(
                bool(str(cs.get(k, "")).strip())
                for k in ("a_story_action", "b_story_human_shift", "c_story_service_truth")
            )
            _chk(abc_ok, "missing_a_b_c_story_tracks", "L3:MULTI_TRACK_STORY_ARCHITECTURE")

        if muted_first:
            cap_ok = (isinstance(beats, list) and len(beats) > 0 and bool(str(beats[0].get("muted_caption", "")).strip()) and (captioned_beats / len(beats)) >= 0.80)
            _chk(cap_ok, f"platform_{platform}_requires_muted_first_captions", "L3:PLATFORM_AND_AV_MEDIUM_PHYSICS")

    elif form_id in ("production_brief", "leadership_report"):
        _chk(bool(str(cs.get("decision_request", "")).strip()), f"{form_id}_missing_decision_request", "L3:EXECUTIVE_DECISION_FRAMING")
        _chk(bool(str(cs.get("opportunity_cost", "")).strip()), f"{form_id}_missing_opportunity_cost", "L3:EXECUTIVE_DECISION_FRAMING")
        if form_id == "leadership_report":
            _chk(bool(str(cs.get("counterargument_steelman", "")).strip()), "leadership_report_missing_counterargument_steelman", "L3:EXECUTIVE_DECISION_FRAMING")

    elif form_id == "research_note":
        signals = cs.get("observed_signals")
        hyps = cs.get("hypotheses")
        _chk(isinstance(signals, list) and len(signals) >= 2, "research_note_missing_observed_signals", "L3:SOURCE_PROVENANCE_AND_EVIDENCE")
        _chk(isinstance(hyps, list) and len(hyps) >= 1, "research_note_missing_hypotheses", "L3:SOURCE_PROVENANCE_AND_EVIDENCE")
        _chk(bool(str(cs.get("transfer_limits", "")).strip()), "research_note_missing_transfer_limits", "L3:SOURCE_PROVENANCE_AND_EVIDENCE")
        _chk(bool(str(cs.get("next_test", "")).strip()), "research_note_missing_next_test", "L3:SOURCE_PROVENANCE_AND_EVIDENCE")

    elif form_id == "treatment":
        _chk(bool(str(cs.get("premise", "")).strip()), "treatment_missing_premise", "L3:HOOK_AND_TENSION_MECHANICS")
        _chk(bool(str(cs.get("visual_approach", "")).strip()), "treatment_missing_visual_approach", "L3:PLATFORM_AND_AV_MEDIUM_PHYSICS")
        acts = cs.get("acts")
        _chk(isinstance(acts, list) and len(acts) >= 2, "treatment_missing_narrative_acts", "L3:MULTI_TRACK_STORY_ARCHITECTURE")

    elif form_id == "call_sheet":
        rows = cs.get("schedule_rows")
        _chk(isinstance(rows, list) and len(rows) >= 2, "call_sheet_too_few_schedule_rows", "L3:FIELD_FEASIBILITY_AND_CUSTODY")
        for key in ("location", "shoot_date", "safety_notes"):
            value = cs.get(key)
            _chk(isinstance(value, str) and bool(value.strip()), f"call_sheet_missing_{key}", "L3:FIELD_FEASIBILITY_AND_CUSTODY")

    elif form_id == "shot_list":
        for key in ("location", "coverage_note"):
            value = cs.get(key)
            _chk(isinstance(value, str) and bool(value.strip()), f"shot_list_missing_{key}", "L3:FIELD_FEASIBILITY_AND_CUSTODY")
        shots = cs.get("shots")
        _chk(isinstance(shots, list) and len(shots) >= 3, "shot_list_too_few_shots", "L3:FIELD_FEASIBILITY_AND_CUSTODY")
        framing_ok = isinstance(shots, list) and all(
            bool(re.search(r"\b(ws|ms|cu|ecu|mcu|ots|b-roll|wide|medium|close-up)\b", str(s.get("framing", "")).lower()))
            for s in shots if isinstance(s, dict)
        )
        _chk(framing_ok, "shot_list_missing_standard_framing_codes", "L3:PLATFORM_AND_AV_MEDIUM_PHYSICS")

    elif form_id == "content_calendar":
        rows = cs.get("calendar_rows")
        _chk(isinstance(rows, list) and len(rows) >= 3, "content_calendar_too_few_rows", "L3:PLATFORM_AND_AV_MEDIUM_PHYSICS")
        plats = {str(r.get("platform", "")).strip().lower() for r in (rows if isinstance(rows, list) else []) if isinstance(r, dict)}
        _chk(len(plats) >= 3, f"content_calendar_needs_3plus_platforms: {sorted(plats)}", "L3:PLATFORM_AND_AV_MEDIUM_PHYSICS")

    score = round(passed / max(1, total), 3)
    return GraphValidationReport(
        ok=(len(violations) == 0),
        form_id=form_id,
        platform=platform,
        target_duration_s=target_duration_s,
        graph_score=score,
        checks_passed=passed,
        checks_total=total,
        violations=violations,
        failed_l3_nodes=failed_l3,
        metrics=metrics,
    )


def _fmt_mmss(sec: int) -> str:
    m, s = divmod(max(0, int(sec)), 60)
    return f"{m:02d}:{s:02d}"


def project_graph_to_markdown(graph: dict[str, Any], *, form_id: str = "av_script") -> str:
    """Deterministically compile a verified Sensemaking Graph into clean 2-zone Markdown (0 LLM tokens)."""
    title = str(graph.get("title", "Untitled Deliverable")).strip()
    platform = str(graph.get("platform", "youtube")).strip()
    target_dur = int(graph.get("target_duration_s", 180))
    rc = graph.get("reality_and_custody") if isinstance(graph.get("reality_and_custody"), dict) else {}
    bdm = graph.get("belief_delta_matrix") if isinstance(graph.get("belief_delta_matrix"), list) else []
    raw_cs = graph.get("causal_spine")
    if isinstance(raw_cs, dict):
        cs = raw_cs
    elif isinstance(raw_cs, list):
        cs = {"beats": raw_cs}
    else:
        cs = {}

    mandates = ", ".join(str(m) for m in (rc.get("official_mandates") or []))
    service_promise = str(rc.get("service_promise", "")).strip()
    patron_action = str(rc.get("immediate_patron_action", "")).strip()
    cites = [str(c) for c in (rc.get("source_citations") or [])]
    holds = rc.get("owned_holds") or []

    lines: list[str] = [
        f"# {title}",
        "",
        f"**Platform:** {platform.title()} · **Target Runtime:** `{_fmt_mmss(target_dur)}` ({target_dur}s) · **Patron Action:** {patron_action}",
        "",
    ]

    if form_id == "av_script":
        lines.append("## Story Spine & Hook")
        lines.append(f"- **Opening Hook Gap:** {cs.get('hook_gap', '')}")
        if cs.get("a_story_action"):
            lines.append(f"- **A-Story (Action):** {cs['a_story_action']}")
        if cs.get("b_story_human_shift"):
            lines.append(f"- **B-Story (Human Shift):** {cs['b_story_human_shift']}")
        if cs.get("c_story_service_truth"):
            lines.append(f"- **C-Story (Service Truth):** {cs['c_story_service_truth']}")
        lines.append("")
        lines.append("## Timed A/V Script")
        lines.append("")
        lines.append("| Timecode | Audio | Video |")
        lines.append("| --- | --- | --- |")
        for b in cs.get("beats") or []:
            if not isinstance(b, dict):
                continue
            tc = f"{_fmt_mmss(b.get('start_s', 0))}-{_fmt_mmss(b.get('end_s', 0))}"
            link = str(b.get("causal_link", "")).upper()
            spoken = str(b.get("spoken_beat", "")).strip()
            visual = str(b.get("visual_first_action", "")).strip()
            cap = str(b.get("muted_caption", "")).strip()
            vid_cell = f"[{link}] {visual}" + (f" [CAPTION: {cap}]" if cap else "")
            lines.append(f"| {tc} | {spoken} | {vid_cell} |")
        lines.append("")
        lines.append("## Timing & Accessibility Notes")
        lines.append(f"- Target cadence `<= 150 WPM`; captions and visual-first action carry meaning on mute.")
        lines.append("")

    elif form_id == "production_brief":
        lines.append("## Decision Request & Mandate")
        lines.append(f"- **Decision Request:** {cs.get('decision_request', '')}")
        lines.append(f"- **Opportunity Cost of Inaction:** {cs.get('opportunity_cost', '')}")
        lines.append("")
        lines.append("## Scope & Deliverables")
        for item in cs.get("deliverables") or []:
            lines.append(f"- {item}")
        lines.append("")

    elif form_id == "leadership_report":
        lines.append("## Executive Decision Request")
        lines.append(f"- **Recommendation / Ask:** {cs.get('decision_request', '')}")
        lines.append(f"- **Strategic Upside & Opportunity Cost:** {cs.get('opportunity_cost', '')}")
        lines.append("")
        lines.append("## Counterargument Steelman & Resource Commitment")
        lines.append(f"- **Strongest Counterargument:** {cs.get('counterargument_steelman', '')}")
        lines.append(f"- **Resource Commitment:** {cs.get('resource_commitment', '')}")
        lines.append("")

    elif form_id == "research_note":
        lines.append("## Observed Evidence & Signals")
        for sig in cs.get("observed_signals") or []:
            lines.append(f"- **Observed Signal:** {sig}")
        lines.append("")
        lines.append("## Hypotheses & Proposed Bets")
        for hyp in cs.get("hypotheses") or []:
            lines.append(f"- **Hypothesis:** {hyp}")
        lines.append("")
        lines.append("## Transfer Limits & Next Test")
        lines.append(f"- **Transfer Limits (What Does Not Transfer):** {cs.get('transfer_limits', '')}")
        lines.append(f"- **Next Falsification Test & Baseline:** {cs.get('next_test', '')}")
        lines.append("")

    elif form_id == "treatment":
        lines.append("## Premise & Hook")
        lines.append(f"- **Premise / Logline:** {cs.get('premise', '')}")
        lines.append(f"- **Visual & Sound Approach:** {cs.get('visual_approach', '')}")
        lines.append("")
        lines.append("## Narrative Arc")
        for act in cs.get("acts") or []:
            lines.append(f"- {act}")
        lines.append("")

    elif form_id == "call_sheet":
        lines.append("## Shoot Overview")
        lines.append(f"- **Shoot Date & Call Time:** {cs.get('shoot_date', 'TBD — Producer to confirm')}")
        lines.append(f"- **Location / Branch:** {cs.get('location') or 'Location to confirm'}")
        lines.append(f"- **Safety & Lab Rules:** {cs.get('safety_notes') or 'Safety requirements to confirm'}")
        lines.append("")
        lines.append("## Operational Schedule & Crew/Cast")
        lines.append("")
        lines.append("| Call Time | Unit / Block | Crew / Cast Roles | Notes |")
        lines.append("| --- | --- | --- | --- |")
        for r in cs.get("schedule_rows") or []:
            if isinstance(r, dict):
                lines.append(f"| {r.get('call_time', '')} | {r.get('block', '')} | {r.get('crew_cast', '')} | {r.get('notes', '')} |")
        lines.append("")

    elif form_id == "shot_list":
        lines.append("## Coverage Strategy & Location Custody")
        lines.append(f"- **Location:** {cs.get('location') or 'Location to confirm'}")
        lines.append(f"- **Visual & Audio Approach:** {cs.get('coverage_note') or 'Coverage approach to confirm'}")
        lines.append("")
        lines.append("## Structured Shot List")
        lines.append("")
        lines.append("| Shot # | Framing | Subject & Action | Audio / Nat Sound | Purpose |")
        lines.append("| --- | --- | --- | --- | --- |")
        for s in cs.get("shots") or []:
            if isinstance(s, dict):
                lines.append(f"| {s.get('shot_id', '')} | {s.get('framing', '')} | {s.get('action', '')} | {s.get('audio_cue', '')} | {s.get('purpose', '')} |")
        lines.append("")

    elif form_id == "content_calendar":
        lines.append("## Cross-Platform Distribution Plan")
        lines.append("")
        lines.append("| Platform | Format | Publish Window | Native Hook | Call to Action |")
        lines.append("| --- | --- | --- | --- | --- |")
        for r in cs.get("calendar_rows") or []:
            if isinstance(r, dict):
                lines.append(f"| {r.get('platform', '')} | {r.get('format', '')} | {r.get('publish_window', '')} | {r.get('hook', '')} | {r.get('cta', '')} |")
        lines.append("")

    # Cleanly isolated Zone 2: Internal Custody & Sources (keeps stakeholder body free of internal jargon)
    lines.append("## Internal Custody & Sources")
    lines.append(f"- **Official 2027-2030 Mandates:** {mandates}")
    lines.append(f"- **Service Promise:** {service_promise}")
    lines.append(f"- **Primary Grounding Sources:** {', '.join(f'`{c}`' for c in cites)}")
    lines.append("- **Stakeholder Belief Shifts Modeled:** " + "; ".join(f"{r.get('role', '')} ({r.get('shift_trigger', '')})" for r in bdm[:4] if isinstance(r, dict)))
    for h in holds:
        if isinstance(h, dict):
            lines.append(f"- [UNKNOWN — OWNER TO CONFIRM] {h.get('item', '')} — Owner: {h.get('owner', '')}")
    lines.append("")
    return "\n".join(lines)


def synthesize_canonical_av_graph(
    *,
    platform: str = "youtube",
    target_duration_s: int = 180,
    topic: str = "Free VHS Digitization at Central Library",
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Synthesize a valid canonical Sensemaking Graph for ANY platform & ANY length (15s/30s/45s/60s/180s/300s)."""
    plat = platform.lower()
    dur = int(target_duration_s)

    if dur <= 15:
        beats = [
            {
                "start_s": 0, "end_s": 4, "causal_link": "SETUP",
                "visual_first_action": "ECU dusty 1994 cardboard tape box snapping open under bright desk lamp.",
                "spoken_beat": "Old family tapes fading in a closet?",
                "muted_caption": "OLD VHS TAPES FADING?",
            },
            {
                "start_s": 4, "end_s": 10, "causal_link": "BUT",
                "visual_first_action": "MS patron slides cassette into Central Library converter deck; glowing preview wakes up.",
                "spoken_beat": "Skip pricey shops—digitize free with your card.",
                "muted_caption": "DIGITIZE FREE WITH YOUR CARD",
            },
            {
                "start_s": 10, "end_s": 15, "causal_link": "THEREFORE",
                "visual_first_action": "CU green USB progress bar hits 100%; clean URL card holds.",
                "spoken_beat": "Book your slot at calgarylibrary.ca.",
                "muted_caption": "BOOK FREE AT CALGARYLIBRARY.CA",
            },
        ]
    elif dur <= 30:
        beats = [
            {
                "start_s": 0, "end_s": 8, "causal_link": "SETUP",
                "visual_first_action": "ECU dusty shoebox opens; gloved fingers pull out a handwritten 1994 cassette.",
                "spoken_beat": "Got family memories trapped on fading VHS tapes?",
                "muted_caption": "MEMORIES TRAPPED ON VHS?",
            },
            {
                "start_s": 8, "end_s": 18, "causal_link": "BUT",
                "visual_first_action": "MS Digital Media Lab workstation; patron clicks cassette into deck; waveform monitor lights up.",
                "spoken_beat": "You don't need a VCR or expensive transfer service—your card unlocks our station free.",
                "muted_caption": "FREE TRANSFER STATION WITH YOUR CARD",
            },
            {
                "start_s": 18, "end_s": 30, "causal_link": "THEREFORE",
                "visual_first_action": "CU blinking USB drive handed across desk; warm smiling patron exits sunlit atrium.",
                "spoken_beat": "Bring a tape and USB drive. Reserve your free session today at calgarylibrary.ca.",
                "muted_caption": "RESERVE FREE: CALGARYLIBRARY.CA",
            },
        ]
    elif dur <= 45:
        beats = [
            {
                "start_s": 0, "end_s": 12, "causal_link": "SETUP",
                "visual_first_action": "MCU host stands beside Central Library glass wall holding an old labeled cassette.",
                "spoken_beat": "Every year, magnetic tape loses a little more color and sound.",
                "muted_caption": "TAPE FADES EVERY YEAR",
            },
            {
                "start_s": 12, "end_s": 28, "causal_link": "BUT",
                "visual_first_action": "OTS workstation deck humming quietly; staff points once to capture button then steps back.",
                "spoken_beat": "Most people think rescuing those clips costs hundreds. Here, your library card opens the booth free.",
                "muted_caption": "YOUR CARD OPENS THE BOOTH FREE",
            },
            {
                "start_s": 28, "end_s": 45, "causal_link": "THEREFORE",
                "visual_first_action": "CU export hits complete on screen; clean end card displays booking URL and branch name.",
                "spoken_beat": "Bring one tape and a USB stick. Book a free slot at calgarylibrary.ca.",
                "muted_caption": "BOOK FREE AT CALGARYLIBRARY.CA",
            },
        ]
    elif dur <= 60:
        beats = [
            {
                "start_s": 0, "end_s": 12, "causal_link": "SETUP",
                "visual_first_action": "ECU rusted closet bin opens; worn 1995 wedding VHS spine fills sunlit frame.",
                "spoken_beat": "What happens to a voice when no player in your house still works?",
                "muted_caption": "WHEN NO VCR WORKS ANYMORE",
            },
            {
                "start_s": 12, "end_s": 28, "causal_link": "BUT",
                "visual_first_action": "MS patron enters Central Library Digital Media Lab; librarian gestures to transfer rig without hovering.",
                "spoken_beat": "Commercial shops charge per hour, but your library card unlocks self-directed digitization stations for free.",
                "muted_caption": "FREE SELF-DIRECTED TRANSFER LAB",
            },
            {
                "start_s": 28, "end_s": 46, "causal_link": "THEREFORE",
                "visual_first_action": "CU preview window clears from static into smiling toddler; silent two-second reaction on patron's eyes.",
                "spoken_beat": "Hit play, watch the footage return in real time, and keep full custody on your own USB drive.",
                "muted_caption": "SAVED STRAIGHT TO YOUR USB",
            },
            {
                "start_s": 46, "end_s": 60, "causal_link": "PAYOFF",
                "visual_first_action": "WS sunlit atrium exit; accessible high-contrast booking card holds steady.",
                "spoken_beat": "Save one tape this week—book a free slot at calgarylibrary.ca.",
                "muted_caption": "BOOK FREE: CALGARYLIBRARY.CA",
            },
        ]
    elif dur <= 180:
        beats = [
            {
                "start_s": 0, "end_s": 25, "causal_link": "SETUP",
                "visual_first_action": "ECU cardboard box latch opens under warm kitchen lamp; faded 1994 VHS spines lift into light.",
                "spoken_beat": "For twenty years, Maria kept her grandfather's guitar nights in a closet bin because no VCR survived.",
                "muted_caption": "20 YEARS TRAPPED ON MAGNETIC TAPE",
            },
            {
                "start_s": 25, "end_s": 60, "causal_link": "BUT",
                "visual_first_action": "MS tabletop close-up of slack ribbon trembling; cuts to steep mail-in studio price quote fading out.",
                "spoken_beat": "Every winter the oxide sheds a little more, but commercial transfer quotes priced her family out.",
                "muted_caption": "FADING FAST — TRANSFER SHOPS TOO COSTLY",
            },
            {
                "start_s": 60, "end_s": 105, "causal_link": "THEREFORE",
                "visual_first_action": "OTS Central Library glass booth; lab specialist points to converter switches, then hands mouse back to Maria.",
                "spoken_beat": "So she booked a free station at Central Library. Staff walk you through setup, then leave you in charge.",
                "muted_caption": "BOOKED FREE AT CENTRAL LIBRARY",
            },
            {
                "start_s": 105, "end_s": 150, "causal_link": "THEREFORE",
                "visual_first_action": "CU tracking snow snaps clear into 1994 living room laughter; slow push-in on Maria's eyes widening in silence.",
                "spoken_beat": "Playback runs minute for minute. When his laugh filled the headphones, three generations got him back.",
                "muted_caption": "THREE GENERATIONS GOT HIS VOICE BACK",
            },
            {
                "start_s": 150, "end_s": 180, "causal_link": "PAYOFF",
                "visual_first_action": "WS family tablet screen glowing around dining table; crisp booking card fades in cleanly.",
                "spoken_beat": "Your library card isn't only for books. Rescue one tape free—reserve at calgarylibrary.ca.",
                "muted_caption": "RESCUE YOUR TAPES FREE: CALGARYLIBRARY.CA",
            },
        ]
    else:
        beats = [
            {
                "start_s": 0, "end_s": 30, "causal_link": "SETUP",
                "visual_first_action": "Whip-pan across podcast booth, converter deck, and editing suite; bold chapter title fades cleanly.",
                "spoken_beat": "Most Calgarians walk past thousands of dollars of free preservation gear every single week.",
                "muted_caption": "FREE PRESERVATION GEAR DOWNTOWN",
            },
            {
                "start_s": 30, "end_s": 90, "causal_link": "BUT",
                "visual_first_action": "ECU cracked 1992 cassette spine; patron unpacks box at kitchen counter looking unsure where to begin.",
                "spoken_beat": "Chapter One: Old family recordings decay quietly in basements, but booking a studio sounds intimidating until you see it.",
                "muted_caption": "CH 1: WHY TAPES STAY STUCK IN CLOSETS",
            },
            {
                "start_s": 90, "end_s": 150, "causal_link": "THEREFORE",
                "visual_first_action": "OTS online booking calendar clicking open; cut to keycard tap and RCA cables seating snugly into deck.",
                "spoken_beat": "Chapter Two: Reserve online with your library card, pack one tape and a USB stick, and check in at Central Library.",
                "muted_caption": "CH 2: THREE-STEP FREE BOOKING FLOW",
            },
            {
                "start_s": 150, "end_s": 210, "causal_link": "BUT",
                "visual_first_action": "MS tracking jitter flashes on monitor; specialist leans in briefly, adjusts tracking dial, and steps back.",
                "spoken_beat": "Chapter Three: What if the picture wobbles? On-site staff help troubleshoot tracking while keeping you in full control.",
                "muted_caption": "CH 3: LIVE STAFF SUPPORT WITHOUT TAKEOVER",
            },
            {
                "start_s": 210, "end_s": 270, "causal_link": "THEREFORE",
                "visual_first_action": "CU crisp family footage playing beside 100% export bar; patron pockets USB stick with relieved grin.",
                "spoken_beat": "Chapter Four: One hour of tape transfers in one hour—then your digital archive travels home ready to share.",
                "muted_caption": "CH 4: YOUR ARCHIVE HOME ON USB",
            },
            {
                "start_s": 270, "end_s": 300, "causal_link": "PAYOFF",
                "visual_first_action": "WS sunlit Central Library concourse; accessible high-contrast URL end card holds cleanly.",
                "spoken_beat": "Pick one forgotten cassette this weekend and book your free transfer slot at calgarylibrary.ca.",
                "muted_caption": "BOOK FREE: CALGARYLIBRARY.CA",
            },
        ]

    return {
        "title": f"{topic} ({plat.title()} · {dur}s A/V Script)",
        "form_id": "av_script",
        "platform": plat,
        "target_duration_s": dur,
        "reality_and_custody": {
            "official_mandates": ["Experiences", "Technology"],
            "service_promise": "Free self-directed public access with a Calgary Public Library card and patron dignity.",
            "immediate_patron_action": "Book a free VHS transfer slot at calgarylibrary.ca with your library card.",
            "source_citations": ["Calgary Public Library/GROUND_TRUTH.md", "MW-04"],
            "owned_holds": [
                {"item": "Confirm current lab deck availability and USB rules (CD-01)", "owner": "Service Owner"},
                {"item": "Signed patron appearance and archival clip cultural clearance (HOLD-04)", "owner": "Producer"},
                {"item": "G06 release sign-off before upload", "owner": "Communications Director"},
            ],
        },
        "belief_delta_matrix": [
            {
                "role": "Calgary Patron",
                "current_skepticism": "Assumes digitization requires expensive shops and libraries only lend books.",
                "target_state": "Confident they can rescue tapes free in one easy visit.",
                "shift_trigger": "Seeing a real neighbor run the converter deck in 3 simple steps.",
            },
            {
                "role": "Media Production Manager",
                "current_skepticism": "Worries script is over-written (>150 WPM) or unshootable in a working lab.",
                "target_state": "Approves shootable visual-first beat table with owned clearance holds.",
                "shift_trigger": "Contiguous timing, <=150 WPM, low audio-video overlap, explicit HOLD-02/04 owners.",
            },
            {
                "role": "Communications Director",
                "current_skepticism": "Guards against mandate/lens drift, unauthorized release claims, or charity framing.",
                "target_state": "Signs off on warm institutional voice aligned to 2027-2030 mandates.",
                "shift_trigger": "Clean stakeholder copy, official Experiences & Technology mandates, G06 held.",
            },
        ],
        "causal_spine": {
            "hook_gap": "Irreplaceable family memories decaying on obsolete tape when free public rescue gear sits downtown.",
            "a_story_action": "A patron brings a fragile family VHS tape into Central Library and digitizes it onto a USB drive.",
            "b_story_human_shift": "From anxious helplessness over fading memories to joyful pride sharing a recovered voice across generations.",
            "c_story_service_truth": "A library card is a free community pass to modern tools, spaces, and dignified self-directed preservation.",
            "beats": beats,
        },
    }


def load_domain_facts(repo_root: Path, topic: str) -> dict[str, list[str]]:
    """Retrieve verified upstream physical/service facts and forbidden myths matching the topic."""
    path = Path(repo_root) / DEFAULT_DOMAIN_FACTS_REL
    if not path.is_file():
        return {"verified_facts": [], "forbidden_myths_and_jabs": []}
    import yaml  # type: ignore

    raw = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or {}
    low_topic = topic.lower()
    facts: list[str] = []
    myths: list[str] = []
    for _tid, cfg in (raw.get("topics") or {}).items():
        if not isinstance(cfg, dict):
            continue
        kws = [str(k).lower() for k in (cfg.get("match_keywords") or [])]
        if any(kw in low_topic for kw in kws):
            facts.extend(str(x) for x in (cfg.get("verified_facts") or []))
            myths.extend(str(x) for x in (cfg.get("forbidden_myths_and_jabs") or []))
    return {"verified_facts": facts, "forbidden_myths_and_jabs": myths}


def compute_beat_budget_plan(platform: str, target_duration_s: int) -> list[dict[str, Any]]:
    """Pre-compile exact beat-by-beat timing, causal link, and spoken word-count budgets (~125 WPM) upstream."""
    dur = max(15, int(target_duration_s))
    if dur <= 15:
        splits = [(0, 4, "SETUP"), (4, 10, "BUT"), (10, dur, "THEREFORE")]
    elif dur <= 30:
        splits = [(0, 6, "SETUP"), (6, 18, "BUT"), (18, dur, "THEREFORE")]
    elif dur <= 45:
        splits = [(0, 10, "SETUP"), (10, 26, "BUT"), (26, dur, "THEREFORE")]
    elif dur <= 60:
        splits = [(0, 10, "SETUP"), (10, 26, "BUT"), (26, 45, "THEREFORE"), (45, dur, "PAYOFF")]
    elif dur <= 180:
        splits = [
            (0, 15, "SETUP"),
            (15, 45, "BUT"),
            (45, 85, "THEREFORE"),
            (85, 120, "BUT"),
            (120, 155, "THEREFORE"),
            (155, dur, "PAYOFF"),
        ]
    else:
        splits = [
            (0, 25, "SETUP"),
            (25, 75, "BUT"),
            (75, 130, "THEREFORE"),
            (130, 185, "BUT"),
            (185, 245, "THEREFORE"),
            (245, dur, "PAYOFF"),
        ]

    plan: list[dict[str, Any]] = []
    for s_s, e_s, link in splits:
        b_dur = max(1, e_s - s_s)
        min_w = max(5, int(round(b_dur * 105.0 / 60.0)))
        max_w = max(min_w + 3, int(round(b_dur * 138.0 / 60.0)))
        plan.append({"start_s": s_s, "end_s": e_s, "causal_link": link, "word_budget": f"{min_w}-{max_w} words"})
    return plan


def build_sensemaking_graph_prompt(
    *,
    form_id: str,
    platform: str,
    target_duration_s: int,
    assignment: str,
    repo_root: Path,
) -> str:
    """Build the upstream Sensemaking Graph generation prompt governed by `craft_protocols.yaml`, domain facts, and beat budgets."""
    protocols = load_craft_protocols(repo_root)
    charter = load_organization_charter(repo_root=repo_root)
    dom_facts = load_domain_facts(repo_root, assignment)
    beat_plan = compute_beat_budget_plan(platform, target_duration_s) if form_id == "av_script" else []
    plat_cfg = (protocols.get("platform_physics") or {}).get(platform.lower(), {})
    len_cfg = _resolve_length_arch(protocols, target_duration_s)
    form_cfg = (protocols.get("form_protocols") or {}).get(form_id, {})

    lines = [
        "Construct ONLY a valid JSON Sensemaking Graph (no Markdown prose outside JSON).",
        f"Organization: {charter.org_name} | Active Plan: {charter.strategic_plan_name}",
        f"Official Mandates ONLY: {', '.join(charter.official_mandates)}",
        f"Form: {form_id} | Platform: {platform} | Target Runtime: {target_duration_s}s",
        f"Platform Physics: {plat_cfg.get('physics_rule', 'Native platform pacing')}",
        f"Length Architecture: min_beats={len_cfg.get('min_beats')}, target_wpm=115-135 (strict floor >=95 WPM, ceiling <=145 WPM, overlap <=0.30, avg sentence <=16 words)",
    ]
    if dom_facts["verified_facts"]:
        lines.append("UPSTREAM VERIFIED DOMAIN FACTS (MUST OBEY — ZERO FACTUAL HALLUCINATIONS):")
        for f in dom_facts["verified_facts"]:
            lines.append(f"  + {f}")
    if dom_facts["forbidden_myths_and_jabs"]:
        lines.append("FORBIDDEN MYTHS, INVENTED PRICES & BROCHURE CLICHÉS (NEVER USE):")
        for m in dom_facts["forbidden_myths_and_jabs"]:
            lines.append(f"  - {m}")
    if beat_plan:
        lines.append("PRE-COMPILED BEAT TIMING & SPOKEN WORD-COUNT BUDGET (FOLLOW EXACTLY):")
        for bp in beat_plan:
            lines.append(f"  * {bp['start_s']:>3}s-{bp['end_s']:>3}s [{bp['causal_link']:<9}] -> spoken_beat MUST be {bp['word_budget']} (warm conversational speech, zero brochure prose)")
    lines.extend(
        [
            "Upstream Craft Principles:",
            *[f"  - {p}" for p in (form_cfg.get("craft_principles") or [])],
            *[f"  - [EVOLVED] {u}" for u in (form_cfg.get("evolved_upgrades") or [])[-3:]],
            f"Assignment: {assignment}",
            "",
            "Return ONLY valid JSON matching this exact schema (no prose outside JSON):",
            "{",
            '  "title": "<concise title>",',
            f'  "form_id": "{form_id}",',
            f'  "platform": "{platform}",',
            f'  "target_duration_s": {target_duration_s},',
            '  "reality_and_custody": {',
            '    "official_mandates": ["Experiences", "Technology"],',
            '    "service_promise": "<free public library card service promise with patron dignity>",',
            '    "immediate_patron_action": "<concrete patron CTA>",',
            '    "source_citations": ["Calgary Public Library/GROUND_TRUTH.md", "MW-04"],',
            '    "owned_holds": [{"item": "<unconfirmed fact or clearance>", "owner": "<Accountable Role e.g. Producer>"}]',
            "  },",
        "  \"belief_delta_matrix\": [",
        "    {\"role\": \"Calgary Patron\", \"current_skepticism\": \"...\", \"target_state\": \"...\", \"shift_trigger\": \"...\"},",
        "    {\"role\": \"Media Production Manager\", \"current_skepticism\": \"...\", \"target_state\": \"...\", \"shift_trigger\": \"...\"},",
        "    {\"role\": \"Communications Director\", \"current_skepticism\": \"...\", \"target_state\": \"...\", \"shift_trigger\": \"...\"}",
        "  ],",
        "  \"creative_modality\": {",
        "    \"audio_strategy\": \"<choose the best sonic/voice mode for THIS deliverable and explain why it fits the audience>\",",
        "    \"visual_rhythm_strategy\": \"<how visual/structural hierarchy sustains attention and clarity>\",",
        "    \"intention_to_outcome_contract\": \"<explicit link: what reader/viewer realizes -> exact action that proves it worked>\"",
        "  },",
    ])
    if form_id == "av_script":
        lines.extend([
            "  \"causal_spine\": {",
            '    "hook_gap": "<unresolved opening visual/curiosity gap>",',
            '    "a_story_action": "<external patron problem/action>",',
            '    "b_story_human_shift": "<human emotional shift>",',
            '    "c_story_service_truth": "<institutional library value truth>",',
            '    "beats": [',
            '      {"start_s": 0, "end_s": 15, "causal_link": "SETUP|BUT|THEREFORE|PAYOFF", "visual_first_action": "<concrete camera action>", "spoken_beat": "<conversational spoken words matching word budget>", "muted_caption": "<short on-screen caption>"}',
            "    ]",
            "  }",
        ])
    elif form_id in ("production_brief", "leadership_report"):
        extra = '    "counterargument_steelman": "<strongest objection and how we answer it>",\n    "resource_commitment": "<crew, hours, and budget scope>",\n' if form_id == "leadership_report" else '    "deliverables": ["<deliverable 1>", "<deliverable 2>"],\n'
        lines.extend([
            "  \"causal_spine\": {",
            '    "decision_request": "<clear executive decision ask in top 25%>",',
            '    "opportunity_cost": "<concrete cost of inaction>",',
            extra.rstrip("\n"),
            "  }",
        ])
    elif form_id == "research_note":
        lines.extend([
            "  \"causal_spine\": {",
            '    "observed_signals": ["<verified local observation 1>", "<verified local observation 2>"],',
            '    "hypotheses": ["<testable hypothesis 1>"],',
            '    "transfer_limits": "<explicit boundary: what does NOT transfer>",',
            '    "next_test": "<exact falsification test and baseline metric>"',
            "  }",
        ])
    elif form_id == "treatment":
        lines.extend([
            "  \"causal_spine\": {",
            '    "premise": "<sharp premise/logline in top 35%>",',
            '    "visual_approach": "<concrete visual, camera, and sound world>",',
            '    "acts": ["Act 1: ...", "Act 2: ...", "Act 3: ..."]',
            "  }",
        ])
    elif form_id == "call_sheet":
        lines.extend([
            "  \"causal_spine\": {",
            '    "shoot_date": "<date and call time>",',
            '    "location": "<Central Library — Digital Media Lab>",',
            '    "safety_notes": "<practical lab safety notes>",',
            '    "schedule_rows": [{"call_time": "09:00", "block": "Setup", "crew_cast": "Producer, Camera Op", "notes": "Verify deck power"}]',
            "  }",
        ])
    elif form_id == "shot_list":
        lines.extend([
            "  \"causal_spine\": {",
            '    "location": "<Central Library — Digital Media Lab>",',
            '    "coverage_note": "<single-location coverage strategy>",',
            '    "shots": [{"shot_id": "S01", "framing": "ECU", "action": "<concrete visual action>", "audio_cue": "<nat sound or VO>", "purpose": "<story beat>"}]',
            "  }",
        ])
    elif form_id == "content_calendar":
        lines.extend([
            "  \"causal_spine\": {",
            '    "calendar_rows": [{"platform": "YouTube", "format": "3m Mini-Doc", "publish_window": "Week 1 Tue", "hook": "<native hook>", "cta": "<native CTA>"}]',
            "  }",
        ])
    lines.extend([
        "}",
        "Keep stakeholder body copy 100% free of internal repo paths (#L12, .agents/) or unexplained codes.",
    ])
    return "\n".join(lines) + "\n"


def synthesize_canonical_graph(
    *,
    form_id: str = "av_script",
    platform: str = "youtube",
    target_duration_s: int = 180,
    topic: str = "Free VHS Digitization at Central Library",
    repo_root: Path | None = None,
) -> dict[str, Any]:
    """Synthesize a verified canonical Sensemaking Graph for ANY of the 8 document forms."""
    if form_id == "av_script":
        return synthesize_canonical_av_graph(
            platform=platform, target_duration_s=target_duration_s, topic=topic, repo_root=repo_root
        )

    base: dict[str, Any] = {
        "title": f"{topic} — {form_id.replace('_', ' ').title()}",
        "form_id": form_id,
        "platform": platform,
        "target_duration_s": target_duration_s,
        "reality_and_custody": {
            "official_mandates": ["Experiences", "Technology"],
            "service_promise": "Free self-directed VHS digitization at Central Library with a free library card.",
            "immediate_patron_action": "Reserve a free digitization station at calgarylibrary.ca.",
            "source_citations": ["Calgary Public Library/GROUND_TRUTH.md", "MW-04"],
            "owned_holds": [
                {"item": "Confirm patron release form and shoot date", "owner": "Media Production Manager"},
            ],
        },
        "belief_delta_matrix": [
            {"role": "Calgary Patron", "current_skepticism": "Assumes VHS transfer is costly.", "target_state": "Knows it is free with a library card.", "shift_trigger": "Clear patron utility proof."},
            {"role": "Media Production Manager", "current_skepticism": "Worries about shoot feasibility.", "target_state": "Confident in single-location shootability.", "shift_trigger": "Concrete crew, lab safety, and owned holds."},
            {"role": "Communications Director", "current_skepticism": "Worries about scope drift.", "target_state": "Confident in mandate alignment.", "shift_trigger": "Explicit 2027-2030 mandate & owned holds."},
        ],
        "creative_modality": {
            "audio_strategy": "Form-native executive/operational voice with zero brochure fluff.",
            "visual_rhythm_strategy": "Scannable hierarchy with concrete proof upfront.",
            "intention_to_outcome_contract": "Reader verifies feasibility and approves next action -> patron books free lab slot.",
        },
    }

    if form_id == "production_brief":
        base["causal_spine"] = {
            "decision_request": "Approve single-location Central Library shoot to promote free VHS digitization.",
            "opportunity_cost": "Patrons continue paying commercial shops or losing degrading family tapes while free stations sit underutilized.",
            "deliverables": ["3-minute YouTube mini-doc", "30-second Instagram/Facebook vertical cutdown", "45-second LinkedIn civic proof cut"],
        }
    elif form_id == "leadership_report":
        base["causal_spine"] = {
            "decision_request": "Approve Q2 Digital Media Lab awareness campaign under Experiences and Technology mandates.",
            "opportunity_cost": "Leaving digitization capacity under-promoted misses a high-trust patron acquisition moment.",
            "counterargument_steelman": "Station demand could spike beyond Central Library capacity; mitigated by linking directly to online booking slots.",
            "resource_commitment": "One 4-hour single-location shoot with existing internal crew; zero external vendor spend.",
        }
    elif form_id == "research_note":
        base["causal_spine"] = {
            "observed_signals": [
                "Observed baseline: flat single-pass prompts failed 0/8 stages on Attempt 1, whereas upstream Sensemaking Graphs cleared 6/6 platforms on Attempt 1.",
                "Observed audience signal: concrete free-card utility outperforms abstract institutional slogans.",
            ],
            "hypotheses": ["Moving creative modality and domain facts upstream reduces Gate 2 revisions across all 8 document forms."],
            "transfer_limits": "Does not transfer to unverified external claims or multi-branch shoots without branch-specific clearance.",
            "next_test": "Run paired A/B evaluation across all 8 forms measuring Gate 1 pass rate and Gate 2 score against baseline.",
        }
    elif form_id == "treatment":
        base["causal_spine"] = {
            "premise": "A Calgarian rescues a fading 1994 family VHS tape for free at Central Library, turning a quiet preservation task into a multi-generational memory.",
            "visual_approach": "Natural sunlit Central Library atrium paired with intimate close-ups of the analog VCR deck, live waveform monitor, and unscripted patron reactions.",
            "acts": [
                "Act 1 (Setup): The fragile 1994 cassette and the barrier of commercial transfer costs.",
                "Act 2 (Complication & Action): Booking a free self-directed Central Library station; real-time 1:1 capture onto personal USB.",
                "Act 3 (Payoff): Hearing a lost family voice return cleanly, closing on a direct card booking invitation.",
            ],
        }
    elif form_id == "call_sheet":
        base["causal_spine"] = {
            "shoot_date": "TBD — Media Production Manager to confirm (08:30 Call Time)",
            "location": "Central Library — Digital Media Lab (800 3 St SE, Calgary)",
            "safety_notes": "No food or drinks near digitization decks; keep walkways clear for public patrons.",
            "schedule_rows": [
                {"call_time": "08:30", "block": "Load-In & Lab Check", "crew_cast": "Producer, Camera Op, Lab Specialist", "notes": "Test VCR deck and monitor glare"},
                {"call_time": "09:30", "block": "Patron Transfer & B-Roll", "crew_cast": "Camera Op, Host, Patron [HOLD]", "notes": "Capture real-time playback and nat sound"},
                {"call_time": "11:00", "block": "Wrap & Gear Custody", "crew_cast": "Full Crew", "notes": "Restore station and log media cards"},
            ],
        }
    elif form_id == "shot_list":
        base["causal_spine"] = {
            "location": "Central Library — Digital Media Lab",
            "coverage_note": "Single-location tripod + handheld coverage with clean natural sound.",
            "shots": [
                {"shot_id": "S01", "framing": "ECU", "action": "Hands open worn 1994 VHS cardboard sleeve under desk light", "audio_cue": "NAT: cardboard rustle", "purpose": "Hook tactile urgency"},
                {"shot_id": "S02", "framing": "MS", "action": "Patron slides cassette into Central Library converter deck", "audio_cue": "NAT: mechanical deck click", "purpose": "Prove self-directed ease"},
                {"shot_id": "S03", "framing": "CU", "action": "Preview monitor clears from static to family footage; USB export completes", "audio_cue": "NAT: tape playback hum", "purpose": "Visual payoff and USB custody"},
                {"shot_id": "S04", "framing": "WS", "action": "Patron exits sunlit Central Library atrium holding USB drive", "audio_cue": "Room tone + closing VO", "purpose": "Resolution and booking CTA"},
            ],
        }
    elif form_id == "content_calendar":
        base["causal_spine"] = {
            "calendar_rows": [
                {"platform": "YouTube", "format": "3m Mini-Doc (16:9)", "publish_window": "Week 1 Tue 10:00", "hook": "What happens when no VCR works anymore?", "cta": "Reserve a free slot at calgarylibrary.ca"},
                {"platform": "Instagram", "format": "30s Reel (9:16)", "publish_window": "Week 1 Thu 12:00", "hook": "OLD VHS TAPES FADING? (visual interrupt)", "cta": "Save this Reel & book free with your card"},
                {"platform": "LinkedIn", "format": "45s Civic Proof (4:5)", "publish_window": "Week 2 Mon 08:30", "hook": "Public libraries preserve family history for free.", "cta": "Explore Digital Media Lab access"},
                {"platform": "Facebook", "format": "60s Walkthrough (4:5)", "publish_window": "Week 2 Wed 18:00", "hook": "Bring one tape and a USB to Central Library.", "cta": "Share with a neighbor & reserve free"},
            ],
        }
    return base


def _parse_graph_object(text: str) -> dict[str, Any]:
    graph = json.loads(text)
    if not isinstance(graph, dict) or not graph:
        raise ValueError("expected a non-empty graph object")
    return graph


def compile_and_evaluate(
    repo_root: Path,
    *,
    form_id: str | None = "av_script",
    platform: str | None = None,
    target_duration_s: int | None = None,
    topic: str = "Free VHS Digitization at Central Library",
    mode: str = "offline",
    enable_judgment_gate: bool = False,
    max_retries: int = 1,
    worker_fn: Callable[..., tuple[bool, str]] | None = None,
    from_json_path: Path | None = None,
    timeout_s: float = 120.0,
) -> dict[str, Any]:
    """Run the full bidirectional pipeline: Upstream Graph -> Validate -> Project Markdown -> Gate 1 + Gate 2 + Upstream Re-Compile."""
    infer_platform = platform is None
    infer_duration = target_duration_s is None
    platform = "youtube" if infer_platform else platform
    target_duration_s = 180 if infer_duration else target_duration_s
    infer_graph_form = form_id is None
    form_id = form_id or "av_script"
    if mode == "prompt":
        prompt_text = build_sensemaking_graph_prompt(
            form_id=form_id,
            platform=platform,
            target_duration_s=target_duration_s,
            assignment=topic,
            repo_root=repo_root,
        )
        return {
            "ok": True,
            "mode": "prompt",
            "form_id": form_id,
            "platform": platform,
            "target_duration_s": target_duration_s,
            "prompt": prompt_text,
        }

    fixture = mode == "offline" and from_json_path is None
    if from_json_path is None and not fixture and worker_fn is None:
        return {
            "ok": False,
            "error": "source_graph_required: supply the document graph with --from-json FILE",
            "form_id": form_id,
            "platform": platform,
            "target_duration_s": target_duration_s,
        }

    attempts = 1 if (fixture or from_json_path is not None) else (1 + max(0, max_retries))
    feedback_note = ""
    last_result: dict[str, Any] = {"ok": False, "platform": platform, "target_duration_s": target_duration_s}

    for attempt in range(attempts):
        writer_lessons: list[str] = []
        if from_json_path is not None:
            input_source = "supplied_graph"
            try:
                graph = _parse_graph_object(Path(from_json_path).read_text(encoding="utf-8"))
            except (OSError, ValueError, RecursionError) as exc:
                return {
                    "ok": False,
                    "error": f"invalid_json_file: {from_json_path}: {exc}",
                    "platform": platform,
                    "target_duration_s": target_duration_s,
                }
            if infer_graph_form and "form_id" in graph:
                declared_form = graph["form_id"]
                if not isinstance(declared_form, str) or declared_form not in FORM_PROFILES:
                    return {"ok": False, "error": "unsupported graph form_id", "platform": platform,
                            "target_duration_s": target_duration_s}
                form_id = declared_form
            if form_id == "av_script":
                if infer_platform and "platform" in graph:
                    declared = graph["platform"]
                    platforms = load_craft_protocols(repo_root).get("platform_physics", {})
                    if not isinstance(declared, str) or declared.lower() not in platforms:
                        return {"ok": False, "error": "unsupported graph platform"}
                    platform = declared.lower()
                if infer_duration and "target_duration_s" in graph:
                    duration = graph["target_duration_s"]
                    if type(duration) is not int or duration <= 0:
                        return {"ok": False, "error": "graph target_duration_s must be a positive integer"}
                    target_duration_s = duration
        elif fixture:
            input_source = "example_fixture"
            graph = synthesize_canonical_graph(
                form_id=form_id, platform=platform, target_duration_s=target_duration_s, topic=topic, repo_root=repo_root
            )
        else:
            from .workload_bench import _call_worker

            input_source = "worker_callback"
            prompt = (
                build_sensemaking_graph_prompt(
                    form_id=form_id,
                    platform=platform,
                    target_duration_s=target_duration_s,
                    assignment=topic,
                    repo_root=repo_root,
                )
                + feedback_note
            )
            if enable_judgment_gate:
                writer_lessons = get_active_promoted_lessons(repo_root, form_id, use_case_id=f"{platform}_{target_duration_s}s", limit=4)
                if writer_lessons:
                    prompt += "\nApply these editorial lessons when building the graph:\n"
                    prompt += "\n".join(f"- {lesson}" for lesson in writer_lessons) + "\n"
            eff = "medium" if attempt > 0 else "low"
            ok, raw = _call_worker(worker_fn, prompt, repo_root, timeout_s, eff)
            if not ok:
                return {"ok": False, "error": raw[:240], "platform": platform, "target_duration_s": target_duration_s}
            cleaned = raw.strip()
            m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.DOTALL | re.IGNORECASE)
            if m:
                cleaned = m.group(1).strip()
            else:
                s, e = cleaned.find("{"), cleaned.rfind("}")
                if s >= 0 and e > s:
                    cleaned = cleaned[s : e + 1]
            try:
                graph = _parse_graph_object(cleaned)
            except Exception as exc:
                feedback_note = f"\nPrevious output had invalid JSON ({exc}); return ONLY valid JSON.\n"
                last_result = {"ok": False, "error": f"graph_json_parse_error: {exc}", "platform": platform, "target_duration_s": target_duration_s}
                continue

        g_val = validate_sensemaking_graph(
            graph,
            form_id=form_id,
            platform=platform,
            target_duration_s=target_duration_s,
            repo_root=repo_root,
            strict_wpm_floor=(mode != "offline"),
        )
        render_graph = graph
        if from_json_path is not None and form_id == "av_script":
            render_graph = {**graph, "platform": platform, "target_duration_s": target_duration_s}
        markdown = project_graph_to_markdown(render_graph, form_id=form_id)
        fe = evaluate_document_flow(markdown, form_id, target_duration_s=target_duration_s)
        bd = evaluate_stakeholder_board(markdown, form_id, flow_eval=fe, target_duration_s=target_duration_s, repo_root=repo_root)
        ax = evaluate_root_axes(markdown, form_id, target_duration_s=target_duration_s, repo_root=repo_root)
        gate1_ok = g_val.ok and fe.passed and bd.buy_in_ready and ax.passed

        gate2_dict: dict[str, Any] = {"verdict": "SKIPPED", "ok": True}
        if gate1_ok and not fixture and enable_judgment_gate:
            from .judgment_panel import run_adversarial_judgment

            jv = run_adversarial_judgment(
                markdown,
                form_id,
                repo_root=repo_root,
                worker_fn=worker_fn,
                timeout_s=min(90.0, timeout_s),
                use_case_intent=f"{platform} {target_duration_s}s {topic}",
                persist_lesson=True,
            )
            gate2_dict = jv.to_dict()
            if jv.verdict in ("SIGN_OFF", "REVISE", "KILL"):
                record_paired_outcome(
                    repo_root,
                    form_id=form_id,
                    use_case_id=f"{platform}_{target_duration_s}s",
                    axis_scores=jv.axis_scores,
                    verdict=jv.verdict,
                    weakest_engine=jv.weakest_engine,
                    proposed_lesson=jv.reusable_judgment_lesson,
                    writer_lessons=writer_lessons,
                )

        last_result = {
            "ok": gate1_ok and bool(gate2_dict.get("ok", False)),
            "input_source": input_source,
            "gate1_ok": gate1_ok,
            "attempts_used": attempt + 1,
            "form_id": form_id,
            "platform": platform,
            "target_duration_s": target_duration_s,
            "graph_validation": g_val.to_dict(),
            "flow_score": fe.flow_score,
            "board_score": bd.board_score,
            "blocking_roles": bd.blocking_roles,
            "axes": {
                "I": ax.axis_1_integrity,
                "II": ax.axis_2_rhetorical_force,
                "III": ax.axis_3_executability,
            },
            "failed_probes": ax.failed_probes,
            "gate2": gate2_dict,
            "markdown": markdown,
            "graph": graph,
        }
        if last_result["ok"]:
            return last_result

        # Feed exact Gate 1 or Gate 2 critique straight back into the upstream Sensemaking Graph re-compile
        if not gate1_ok:
            feedback_note = f"\nUPSTREAM GRAPH REPAIR REQUIRED: fix violations {g_val.violations[:4]} and probes {ax.failed_probes[:3]}.\n"
        elif gate2_dict.get("verdict") in ("REVISE", "KILL"):
            feedback_note = (
                f"\nUPSTREAM GRAPH REPAIR FROM ADVERSARIAL BUYING PANEL ({gate2_dict.get('verdict')}): "
                f"Objection: {gate2_dict.get('top_executive_objection')} | "
                f"Required Cut: {gate2_dict.get('required_cut')} | "
                f"Fix: {gate2_dict.get('actionable_fix')}\n"
            )
        else:
            break

    return last_result
