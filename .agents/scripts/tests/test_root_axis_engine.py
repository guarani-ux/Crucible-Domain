#!/usr/bin/env python3
"""Tests for the L0->L4 Sensemaking Ontology, 3-Axis Root Probes, Red-Capable Validity, and Controlled A/B Outcome Ratchet."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = ROOT / ".agents" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from crucible.judgment_panel import parse_judge_response  # noqa: E402
from crucible.outcome_ratchet import (  # noqa: E402
    build_outcome_matrix,
    get_active_promoted_lessons,
    record_paired_outcome,
)
from crucible.root_axis_engine import (  # noqa: E402
    evaluate_root_axes,
    validate_ontology_closure,
    verify_test_validity,
)


def test_l0_to_l4_ontology_tree_closure_and_red_capable_test_validity(tmp_path: Path) -> None:
    ont = validate_ontology_closure(ROOT)
    assert ont["ok"] is True, ont.get("errors")
    assert ont["l0_count"] == 1
    assert ont["l1_count"] == 3
    assert ont["l2_count"] == 5
    assert ont["l3_count"] == 12
    assert ont["l4_count"] == 36
    assert len(ont["forms_covered"]) == 8

    # Negative check: missing ontology file fails cleanly
    missing_ont = validate_ontology_closure(tmp_path)
    assert missing_ont["ok"] is False
    assert any("missing" in err for err in missing_ont["errors"])

    val = verify_test_validity(ROOT)
    assert val["ok"] is True, val
    assert val["counterexamples_caught"] == val["counterexamples_total"]
    assert val["counterexamples_total"] >= 5
    assert val["golden_passed"] == val["golden_total"]


def test_four_platform_copy_paste_fails_axis2_and_native_adaptation_passes() -> None:
    recycled = (
        "# Q1 Rollout\n\n"
        "Goal: Drive immediate patron action (`Calgary Public Library/GROUND_TRUTH.md`).\n\n"
        "## YouTube\nBring old family VHS tapes to Central Library and digitize them for free with your card.\n"
        "## Instagram\nBring old family VHS tapes to Central Library and digitize them for free with your card.\n"
        "## LinkedIn\nBring old family VHS tapes to Central Library and digitize them for free with your card.\n"
        "## Facebook\nBring old family VHS tapes to Central Library and digitize them for free with your card.\n\n"
        "| Week | Channel | Deliverable | Owner | Status |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| W1 | YouTube | Ep1 | Producer | Hold |\n"
        "| W1 | Instagram | Reel | Digital Marketing | Draft |\n"
        "| W1 | LinkedIn | Post | Communications | Draft |\n"
    )
    bad = evaluate_root_axes(recycled, "content_calendar", repo_root=ROOT)
    assert not bad.passed
    assert "platform_native_divergence" in bad.failed_probes

    native = (
        "# Q1 Rollout\n\n"
        "Goal: Drive immediate patron action (`Calgary Public Library/GROUND_TRUTH.md`).\n\n"
        "## YouTube\nTitle: Rescue 1990s Home Movies Before Magnetic Tape Decays. 5-minute studio walkthrough with chapter resets and booking link in description.\n"
        "## Instagram\nMuted 15s vertical Reel: bold kinetic captions on a crumbling cassette box, quick whip-cut to glowing USB transfer bar, save-for-weekend CTA.\n"
        "## LinkedIn\nHow public libraries lower creative barriers for local entrepreneurs and civic storytellers through shared digital preservation infrastructure under our 2027-2030 Technology mandate.\n"
        "## Facebook\nCalgary neighbors: got a closet full of wedding or hockey VHS tapes? Drop by Central Library with your card—free transfer station open all week.\n\n"
        "| Week | Channel | Deliverable | Owner | Status |\n"
        "| --- | --- | --- | --- | --- |\n"
        "| W1 | YouTube | Ep1 Master | Producer | Hold: G06 — Owner: Producer |\n"
        "| W1 | Instagram | 15s Reel | Digital Marketing | Draft |\n"
        "| W1 | LinkedIn | Civic Post | Communications | Draft |\n"
    )
    good = evaluate_root_axes(native, "content_calendar", repo_root=ROOT)
    assert good.passed is True
    assert good.axis_2_rhetorical_force == 1.0


def test_gate2_non_masking_axis_invariant_blocks_single_weak_axis() -> None:
    masked = parse_judge_response(
        json.dumps(
            {
                "verdict": "SIGN_OFF",
                "judgment_score": 0.90,
                "axis_scores": {
                    "axis_1_integrity": 0.96,
                    "axis_2_rhetorical_force": 0.70,
                    "axis_3_executability": 0.95,
                },
                "weakest_engine": "attention_tension_and_narrative_architecture",
                "org_voice_flags": [],
            }
        )
    )
    assert masked.verdict == "REVISE"
    assert not masked.ok


def test_controlled_ab_outcome_ratchet_promotes_proven_gain_and_quarantines_regression(tmp_path: Path) -> None:
    ev1 = record_paired_outcome(
        tmp_path,
        form_id="av_script",
        use_case_id="3m-patron-story-mini-doc",
        axis_scores={"axis_1_integrity": 0.90, "axis_2_rhetorical_force": 0.62, "axis_3_executability": 0.88},
        verdict="REVISE",
        weakest_engine="attention_tension_and_narrative_architecture",
        proposed_lesson="Weave B-story human emotional turn before minute 2.",
    )
    assert ev1["action"] == "STAGED_CANDIDATE"
    active_during = get_active_promoted_lessons(tmp_path, "av_script")
    assert any("TESTING CANDIDATE" in s for s in active_during)

    ev2 = record_paired_outcome(
        tmp_path,
        form_id="av_script",
        use_case_id="3m-patron-story-mini-doc",
        axis_scores={"axis_1_integrity": 0.91, "axis_2_rhetorical_force": 0.88, "axis_3_executability": 0.89},
        verdict="SIGN_OFF",
        weakest_engine="",
    )
    assert ev2["action"] == "PROMOTED"
    assert "Weave B-story human emotional turn before minute 2." in get_active_promoted_lessons(tmp_path, "av_script")

    record_paired_outcome(
        tmp_path,
        form_id="production_brief",
        use_case_id="ep01-preflight-brief",
        axis_scores={"axis_1_integrity": 0.88, "axis_2_rhetorical_force": 0.65, "axis_3_executability": 0.86},
        verdict="REVISE",
        proposed_lesson="Drop citations to sound punchier.",
    )
    ev_bad = record_paired_outcome(
        tmp_path,
        form_id="production_brief",
        use_case_id="ep01-preflight-brief",
        axis_scores={"axis_1_integrity": 0.55, "axis_2_rhetorical_force": 0.80, "axis_3_executability": 0.86},
        verdict="REVISE",
    )
    assert ev_bad["action"] == "QUARANTINED"
    assert "Drop citations to sound punchier." not in get_active_promoted_lessons(tmp_path, "production_brief")

    mat = build_outcome_matrix(tmp_path)
    assert mat["total_promoted_lessons"] == 1
    assert mat["total_quarantined_lessons"] == 1


def test_cli_bench_test_validity_and_inspect_end_to_end() -> None:
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "crucible_gate.py"), "bench", "test-validity", "--json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["ok"] is True
    assert data["ontology"]["l4_count"] == 36
    assert data["counterexamples_caught"] == data["counterexamples_total"]
