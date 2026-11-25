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


def test_end_to_end_8_stage_pipeline_and_cross_document_cold_receiver_parity(tmp_path: Path) -> None:
    import shutil
    from crucible.pipeline_runner import audit_pipeline_parity, load_pipeline_manifest, run_end_to_end_pipeline

    # Isolate repo_root in tmp_path with required YAML configs
    bench_dir = tmp_path / ".agents" / "bench"
    bench_dir.mkdir(parents=True, exist_ok=True)
    for fname in ("pipelines.yaml", "org_charter.yaml", "levers.yaml", "judgment_rubrics.yaml", "axis_contracts.yaml"):
        shutil.copy(ROOT / ".agents" / "bench" / fname, bench_dir / fname)

    res = run_end_to_end_pipeline(tmp_path, project_id="cpl-ycd-ep01-vhs-3m", mode="offline")
    assert res["ok"] is True, res
    assert res["stages_passed"] == 8
    assert res["stages_total"] == 8
    assert [s["form_id"] for s in res["stages"]] == [
        "research_note",
        "treatment",
        "production_brief",
        "av_script",
        "shot_list",
        "call_sheet",
        "content_calendar",
        "leadership_report",
    ]
    par = res["parity"]
    assert par["ok"] is True
    assert par["parity_score"] == 1.0
    assert par["message_carry_score"] == 1.0
    assert par["cold_receiver_score"] == 1.0
    assert par["cold_receiver_rating"] == "RUNNABLE_STANDALONE"

    # Negative cross-document parity check: drop holds in leadership_report + break runtime + inject unauthorized release
    manifest = load_pipeline_manifest(tmp_path)
    proj_cfg = manifest["projects"][0]
    out_dir = tmp_path / res["output_dir"]
    stage_texts = {s["form_id"]: (out_dir / s["filename"]).read_text(encoding="utf-8") for s in res["stages"]}
    stage_texts["leadership_report"] = "# Memo\nApproved for release today.\n"
    stage_texts["av_script"] = "# Script\n| Timecode | Audio | Video |\n| --- | --- | --- |\n| 00:00-00:15 | Short line. | WS branch. |\n"

    bad_par = audit_pipeline_parity(stage_texts, proj_cfg, repo_root=tmp_path)
    assert not bad_par.ok
    assert bad_par.cold_receiver_rating != "RUNNABLE_STANDALONE"
    assert any("unauthorized_release" in v for v in bad_par.violations)
    assert any("runtime_parity_mismatch" in v for v in bad_par.violations)
    assert any("hold_custody_dropped" in v for v in bad_par.violations)


def test_bidirectional_sensemaking_compiler_and_cyclical_capability_evolver(tmp_path: Path) -> None:
    import shutil
    from crucible.capability_evolver import (
        MULTI_CASE_AV_MATRIX,
        attribute_failures_to_ontology,
        evolve_form_capability,
    )
    from crucible.sensemaking_compiler import (
        compile_and_evaluate,
        load_craft_protocols,
        synthesize_canonical_av_graph,
        validate_sensemaking_graph,
    )

    # 1. All 6 platform x length cases compile cleanly upstream -> downstream with zero leaks
    for plat, dur, topic in MULTI_CASE_AV_MATRIX:
        res = compile_and_evaluate(
            ROOT, form_id="av_script", platform=plat, target_duration_s=dur, topic=topic, mode="offline"
        )
        assert res["ok"] is True, (plat, dur, res)
        assert res["graph_validation"]["ok"] is True
        assert res["flow_score"] == 1.0
        assert res["axes"] == {"I": 1.0, "II": 1.0, "III": 1.0}
        body_before_appendix = res["markdown"].split("## Internal Custody & Sources")[0]
        assert "#L" not in body_before_appendix
        assert ".agents/" not in body_before_appendix

    # 2. Negative upstream graph check: flat AND_THEN beats + missing IG muted captions + #L12 leak rejected upstream
    bad_g = synthesize_canonical_av_graph(platform="instagram", target_duration_s=180, repo_root=ROOT)
    for b in bad_g["causal_spine"]["beats"]:
        b["causal_link"] = "AND_THEN"
        b["muted_caption"] = ""
    bad_g["causal_spine"]["beats"][0]["spoken_beat"] += " See GROUND_TRUTH.md#L12."
    bad_val = validate_sensemaking_graph(
        bad_g, form_id="av_script", platform="instagram", target_duration_s=180, repo_root=ROOT
    )
    assert not bad_val.ok
    assert "L3:HOOK_AND_TENSION_MECHANICS" in bad_val.failed_l3_nodes
    assert "L3:PLATFORM_AND_AV_MEDIUM_PHYSICS" in bad_val.failed_l3_nodes
    assert "L3:POLITICAL_STEWARDSHIP_AND_AUTHORITY" in bad_val.failed_l3_nodes

    # 3. Bottom-up L4 -> L3 -> L2 -> L1 -> L0 ontology attribution
    attr = attribute_failures_to_ontology(ROOT, failed_probes=["narrative_tension_and_counterpoint"])
    assert attr["ok"] is True
    assert len(attr["attributed_l3"]) >= 1
    assert attr["attributed_l3"][0]["l0_id"] == "L0:INSTITUTIONAL_SENSEMAKING_AND_ACTION_DESIGN"

    # 4. Isolated cyclical upstream promotion bumps craft_protocols.yaml version & writes golden_exemplars.json
    import yaml as _yaml

    bench_dir = tmp_path / ".agents" / "bench"
    bench_dir.mkdir(parents=True, exist_ok=True)
    for fname in ("craft_protocols.yaml", "sensemaking_ontology.yaml", "org_charter.yaml", "axis_contracts.yaml"):
        shutil.copy(ROOT / ".agents" / "bench" / fname, bench_dir / fname)
    # Reset tmp_path copy to baseline v1.0.0 so test is independent of live repo promotions
    p_copy = bench_dir / "craft_protocols.yaml"
    p_raw = _yaml.safe_load(p_copy.read_text(encoding="utf-8"))
    p_raw["version"] = "1.0.0"
    p_raw["form_protocols"]["av_script"]["evolved_upgrades"] = []
    p_copy.write_text(_yaml.safe_dump(p_raw, sort_keys=False), encoding="utf-8")

    ev = evolve_form_capability(tmp_path, form_id="av_script", apply_upgrade=True)
    assert ev["ok"] is True
    assert ev["ablation"]["cases_passed"] == 6
    assert ev["ablation"]["counterfactual_caught"] is True
    assert ev["promoted"] is True
    assert load_craft_protocols(tmp_path)["version"] == "1.0.1"
    assert (bench_dir / "golden_exemplars.json").is_file()


def test_all_8_document_types_compile_and_validate() -> None:
    from crucible.sensemaking_compiler import (
        build_sensemaking_graph_prompt,
        compile_and_evaluate,
        synthesize_canonical_graph,
        validate_sensemaking_graph,
    )

    all_forms = (
        "av_script",
        "production_brief",
        "leadership_report",
        "research_note",
        "treatment",
        "call_sheet",
        "shot_list",
        "content_calendar",
    )
    for fid in all_forms:
        res = compile_and_evaluate(
            ROOT,
            form_id=fid,
            platform="youtube",
            target_duration_s=180,
            mode="offline",
        )
        assert res["ok"] is True, f"{fid} failed: graph={res['graph_validation']['violations']} flow={res.get('flow_score')}"
        assert res["graph_validation"]["graph_score"] == 1.0, fid
        assert res["flow_score"] == 1.0, fid
        prompt = build_sensemaking_graph_prompt(
            form_id=fid, platform="youtube", target_duration_s=180, assignment="VHS Digitization", repo_root=ROOT
        )
        assert f'"form_id": "{fid}"' in prompt

    # Negative-path check: missing decision_request in leadership_report must be BLOCKED
    bad_lr = synthesize_canonical_graph(form_id="leadership_report", repo_root=ROOT)
    bad_lr["causal_spine"]["decision_request"] = ""
    bad_val = validate_sensemaking_graph(bad_lr, form_id="leadership_report", repo_root=ROOT)
    assert bad_val.ok is False
    assert any("missing_decision_request" in v for v in bad_val.violations)



