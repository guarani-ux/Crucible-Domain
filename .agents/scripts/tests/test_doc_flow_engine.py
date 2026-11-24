#!/usr/bin/env python3
"""Offline tests for Document Flow AST, 6-Role Stakeholder Buy-In Board, Organization Charter, and Mutation Fuzzer."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = ROOT / ".agents" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from crucible.doc_flow_engine import (  # noqa: E402
    GOLDEN_SPECIMENS,
    OrganizationCharter,
    evaluate_document_flow,
    evaluate_stakeholder_board,
    load_organization_charter,
    parse_document_ast,
    run_offline_fuzz_suite,
)
from crucible.form_diagnostics import diagnose_form_deliverable  # noqa: E402


def test_ast_parses_sections_tables_timecodes_and_unowned_holds() -> None:
    text = GOLDEN_SPECIMENS["av_script_5m"]["text"]
    ast = parse_document_ast(text)
    assert len(ast.timecode_beats) == 6
    assert ast.timecode_beats[-1].end_s == 300
    assert all(b.av_overlap < 0.45 for b in ast.timecode_beats)
    assert ast.hold_count == 1
    assert ast.holds_with_owner == 1

    unowned = text.replace("— Owner: Director", "")
    ast_unowned = parse_document_ast(unowned)
    assert ast_unowned.hold_count == 1
    assert ast_unowned.holds_with_owner == 0


def test_av_counterpoint_collapse_and_vision_2040_kpi_misuse_blocked() -> None:
    good_3m = GOLDEN_SPECIMENS["av_script_3m"]["text"]
    res_good = evaluate_document_flow(good_3m, "av_script", target_duration_s=180)
    assert res_good.passed is True
    assert res_good.flow_score == 1.0

    dup_lines = []
    for ln in good_3m.splitlines():
        if ln.startswith("| 0"):
            parts = [p.strip() for p in ln.strip("|").split("|")]
            dup_lines.append(f"| {parts[0]} | {parts[1]} | {parts[1]} |")
        else:
            dup_lines.append(ln)
    res_dup = evaluate_document_flow("\n".join(dup_lines), "av_script", target_duration_s=180)
    assert not res_dup.passed
    assert any("av_counterpoint_collapse" in v for v in res_dup.violations)
    assert "av_counterpoint_cap:0.35" in res_dup.recommended_levers

    bad_kpi = GOLDEN_SPECIMENS["leadership_report"]["text"] + "\nOur single-video KPI target is three in four Calgarians.\n"
    board = evaluate_stakeholder_board(bad_kpi, "leadership_report", repo_root=ROOT)
    assert not board.buy_in_ready
    assert "ceo" in board.blocking_roles
    assert board.charter_alignment["vision_kpi_misuse"] is True


def test_stale_prior_plan_and_mandate_lens_confusion_blocked_by_six_roles(tmp_path: Path) -> None:
    brief = GOLDEN_SPECIMENS["production_brief"]["text"]
    clean_board = evaluate_stakeholder_board(brief, "production_brief", repo_root=ROOT)
    assert clean_board.buy_in_ready is True
    assert len(clean_board.role_reviews) == 6
    assert clean_board.blocking_roles == []

    bad_brief = (
        brief
        + "\nThis fulfills the official 2027-2030 mandates of Grow and Books & Reading."
        + "\nIt also follows our current strategic plan, Everyone Belongs at the Library (2023-2026)."
    )
    bad_board = evaluate_stakeholder_board(bad_brief, "production_brief", repo_root=ROOT)
    assert not bad_board.buy_in_ready
    assert "communications_director" in bad_board.blocking_roles
    assert "ceo" in bad_board.blocking_roles
    assert bad_board.charter_alignment["stale_prior_plan_trap"] is True
    assert bad_board.charter_alignment["lens_as_mandate_trap"] is True

    bad_file = tmp_path / "bad_brief.md"
    bad_file.write_text(bad_brief, encoding="utf-8")
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "crucible_gate.py"), "bench", "audit", str(bad_file), "production_brief"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 1
    assert "BLOCKED" in proc.stdout


def test_portable_organization_charter_loads_yaml_for_any_org(tmp_path: Path) -> None:
    cpl_charter = load_organization_charter(repo_root=ROOT)
    assert cpl_charter.org_name == "Calgary Public Library"
    assert "2027-2030" in cpl_charter.strategic_plan_name
    assert set(cpl_charter.official_mandates) == {"Collections", "Experiences", "Expertise", "Spaces", "Technology"}

    custom_yaml = tmp_path / "org_charter.yaml"
    custom_yaml.write_text(
        "org_name: Civic Transit Authority\n"
        "strategic_plan_name: Mobility 2035\n"
        "mission: Move riders safely and reliably.\n"
        "vision_north_star: Zero-emission fleet by 2035.\n"
        "official_mandates:\n"
        "  - Reliability\n"
        "  - Safety\n"
        "values:\n"
        "  - Punctuality\n"
        "commitments:\n"
        "  - Accessibility\n"
        "service_promises:\n"
        "  - on-time arrival\n",
        encoding="utf-8",
    )
    loaded = load_organization_charter(charter_path=custom_yaml)
    assert isinstance(loaded, OrganizationCharter)
    assert loaded.org_name == "Civic Transit Authority"
    assert loaded.official_mandates == ("Reliability", "Safety")

    report = (
        "# Transit Executive Summary\n\n"
        "## Decision\n"
        "Recommend approving Q2 Reliability and Safety pilot for riders delivering on-time arrival.\n\n"
        "## Evidence\n"
        "Grounded in `transit_audit.md`.\n\n"
        "## Open Holds\n"
        "- [UNKNOWN — OWNER TO CONFIRM] Fleet depot slot — Owner: Operations Manager\n"
    )
    board = evaluate_stakeholder_board(report, "leadership_report", charter=loaded)
    assert board.buy_in_ready is True
    assert "Reliability" in board.charter_alignment["matched_mandates"]


def test_offline_fuzz_suite_achieves_full_kill_rate_and_integrates_with_diagnostics() -> None:
    fuzz = run_offline_fuzz_suite(rounds=2, seed=7)
    assert fuzz["ok"] is True
    assert fuzz["golden_passed"] == fuzz["golden_total"]
    assert fuzz["mutants_killed"] == fuzz["mutants_total"]
    assert fuzz["kill_rate"] == 1.0
    assert all(count > 0 for count in fuzz["role_blocks_by_role"].values())

    diag = diagnose_form_deliverable(
        GOLDEN_SPECIMENS["research_note"]["text"],
        "research_note",
        repo_root=ROOT,
        strict_cpl_mandates=True,
    )
    assert diag.flow_score == 1.0
    assert diag.board_score >= 0.90
    assert diag.blocking_roles == []


def test_whitebox_40_feature_ml_scorer_trains_and_explains_pass_vs_fail(tmp_path: Path) -> None:
    from crucible.doc_ml_scorer import (
        FEATURE_NAMES,
        append_human_label,
        extract_document_features,
        score_document_ml,
        train_whitebox_model,
    )

    feats, _ = extract_document_features(
        GOLDEN_SPECIMENS["production_brief"]["text"], "production_brief", repo_root=ROOT
    )
    assert len(feats) == 40
    assert tuple(feats.keys()) == FEATURE_NAMES

    # Col-2 timecode format (`| Beat | 00:00-00:10 | Audio | Video |`) parses cleanly
    col2_script = (
        "| Beat | Time | Audio | Video |\n"
        "| --- | --- | --- | --- |\n"
        "| 1 | 00:00-00:15 | Welcome to the library studio. | WS glass booth door swings open. |\n"
        "| 2 | 00:15-00:30 | Bring your card to book free time. | CU keycard taps kiosk reader. |\n"
    )
    ast_col2 = parse_document_ast(col2_script)
    assert len(ast_col2.timecode_beats) == 2
    assert ast_col2.timecode_beats[-1].end_s == 30

    # Train in isolated tmp_path repo root so we don't mutate workspace human_labels
    train_res = train_whitebox_model(tmp_path, save=True)
    assert train_res["ok"] is True
    assert train_res["feature_count"] == 40
    assert train_res["holdout_accuracy"] >= 0.90

    good_score = score_document_ml(
        GOLDEN_SPECIMENS["leadership_report"]["text"], "leadership_report", repo_root=tmp_path
    )
    assert good_score["verdict"] == "PASS"
    assert good_score["buy_in_probability"] >= 0.70

    bad_text = (
        GOLDEN_SPECIMENS["leadership_report"]["text"]
        + "\nApproved for release and Asana updated. Fulfills official 2027-2030 mandates of Grow.\n"
    )
    bad_score = score_document_ml(bad_text, "leadership_report", repo_root=tmp_path)
    assert bad_score["verdict"] == "FAIL"
    assert bad_score["buy_in_probability"] < good_score["buy_in_probability"]
    assert len(bad_score["top_negative_drivers"]) > 0

    # Human label ingestion + invalid verdict rejection
    sample_doc = tmp_path / "sample.md"
    sample_doc.write_text(GOLDEN_SPECIMENS["treatment"]["text"], encoding="utf-8")
    row = append_human_label(tmp_path, sample_doc, "treatment", "pass", note="strong arc")
    assert row["label"] == 1
    retrain = train_whitebox_model(tmp_path, save=True)
    assert retrain["human_label_count"] == 1

    try:
        append_human_label(tmp_path, sample_doc, "treatment", "maybe")
        raise AssertionError("Expected ValueError for invalid verdict")
    except ValueError:
        pass


def test_lever_registry_pull_and_steering_packet(tmp_path: Path) -> None:
    import json
    import shutil
    from crucible.lever_control import build_steering_packet, load_lever_registry, pull_lever

    reg = load_lever_registry(ROOT)
    assert "hold_owner_policy:require_named_owner" in reg
    assert "mandate_boundary_guard" in reg

    # Copy levers.yaml + org_charter.yaml into tmp_path for isolated test
    bench_dir = tmp_path / ".agents" / "bench"
    bench_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / ".agents" / "bench" / "levers.yaml", bench_dir / "levers.yaml")
    shutil.copy(ROOT / ".agents" / "bench" / "org_charter.yaml", bench_dir / "org_charter.yaml")

    # Seed one failing brief in tmp_path/.agents/bench_runs/
    run_doc = tmp_path / ".agents" / "bench_runs" / "r01" / "cpl-brief" / "brief.md"
    run_doc.parent.mkdir(parents=True, exist_ok=True)
    run_doc.write_text("# Brief\n\nSome background text.\n- [UNKNOWN — OWNER TO CONFIRM] Slot pending\n", encoding="utf-8")

    pkt = build_steering_packet(tmp_path, auto_apply=True)
    assert pkt["ok"] is True
    assert pkt["docs_scanned"] == 1
    assert pkt["buy_in_ready"] == 0
    assert "OFFLINE STEERING PACKET" in pkt["compact_steering_brief"]
    assert len(pkt["applied_levers"]) >= 1

    policies = json.loads((tmp_path / ".agents" / "ml_learned_policies.json").read_text(encoding="utf-8"))
    assert "production_brief" in policies
    assert len(policies["production_brief"]["active_levers"]) >= 1

    # Unknown lever raises ValueError
    try:
        pull_lever(tmp_path, "nonexistent_lever")
        raise AssertionError("Expected ValueError for unknown lever")
    except ValueError:
        pass


def test_non_redundant_trial_loop_tracks_rubric_and_drr(tmp_path: Path) -> None:
    import shutil
    from crucible.lever_control import run_offline_trial_loop

    bench_dir = tmp_path / ".agents" / "bench"
    bench_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy(ROOT / ".agents" / "bench" / "levers.yaml", bench_dir / "levers.yaml")
    shutil.copy(ROOT / ".agents" / "bench" / "org_charter.yaml", bench_dir / "org_charter.yaml")

    r1 = run_offline_trial_loop(tmp_path, rounds=3, batch_size=12, reset=True)
    assert r1["ok"] is True
    assert r1["total_trials_ever"] == sum(rr["trials"] for rr in r1["rounds"])
    assert len(r1["rubric_adjustments_by_form"]) >= 1

    # Running again without reset advances strictly to unseen trials (zero redundancy)
    r2 = run_offline_trial_loop(tmp_path, rounds=10, batch_size=12, reset=False)
    assert r2["ok"] is True
    assert r2["total_trials_ever"] >= r1["total_trials_ever"]
    assert r2["stopped_reason"] in ("diminishing_returns_reached", "rounds_completed", "frontier_exhausted")



