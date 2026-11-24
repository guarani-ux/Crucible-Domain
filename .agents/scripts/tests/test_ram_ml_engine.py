#!/usr/bin/env python3
"""Tests for in-RAM ML test-launch ranking and diff review (ram_ml_engine + crucible_gate CLI)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HUB_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import ram_ml_engine  # noqa: E402


def test_rank_tests_prioritizes_crucible_gate_test_on_gate_change() -> None:
    res = ram_ml_engine.rank_tests_for_changes(
        HUB_ROOT,
        changed_files=[".agents/scripts/crucible_gate.py"],
    )
    assert res["ranked_tests"], "Expected at least one test file"
    impacted_paths = [r["test_path"] for r in res["ranked_tests"] if r["tier"] == "impacted"]
    assert ".agents/scripts/tests/test_crucible_gate.py" in impacted_paths
    assert res["impacted_count"] >= 1


def test_review_changes_flags_missing_co_change_partner() -> None:
    res = ram_ml_engine.review_changes_in_ram(
        HUB_ROOT,
        changed_files=[".agents/scripts/crucible_gate.py"],
    )
    assert res["files_reviewed"] == 1
    item = res["reviewed_files"][0]
    assert item["rel_path"] == ".agents/scripts/crucible_gate.py"
    partners = [p["partner"] for p in item["missing_co_change_partners"]]
    assert ".agents/scripts/tests/test_crucible_gate.py" in partners
    assert item["review_priority"] >= 0.35


def test_crucible_gate_ml_cli_json_roundtrip() -> None:
    for sub in ("ml-rank", "ml-review"):
        proc = subprocess.run(
            [sys.executable, ".agents/scripts/crucible_gate.py", sub, "--json", ".agents/scripts/crucible_gate.py"],
            cwd=HUB_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        assert proc.returncode == 0, proc.stderr
        data = json.loads(proc.stdout)
        assert "elapsed_ms" in data


def test_negative_unmatched_file_and_invalid_cli_subcommand() -> None:
    rank_res = ram_ml_engine.rank_tests_for_changes(HUB_ROOT, changed_files=["nonexistent_doc_xyz.md"])
    assert rank_res["impacted_count"] == 0
    assert all(r["tier"] == "baseline" for r in rank_res["ranked_tests"])

    rev_res = ram_ml_engine.review_changes_in_ram(HUB_ROOT, changed_files=["nonexistent_doc_xyz.md"])
    assert rev_res["files_reviewed"] == 1
    assert rev_res["reviewed_files"][0]["max_cc"] is None
    assert rev_res["reviewed_files"][0]["missing_co_change_partners"] == []

    bad_cli = subprocess.run(
        [sys.executable, ".agents/scripts/crucible_gate.py", "ml-invalid"],
        cwd=HUB_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert bad_cli.returncode != 0


def test_transcript_extraction_and_supervised_mode(tmp_path: Path) -> None:
    brain = tmp_path / "brain"
    conv = brain / "conv-1" / ".system_generated" / "logs"
    conv.mkdir(parents=True)
    lines = [
        {
            "step_index": 1,
            "tool_calls": [{"arguments": {"Path": str(HUB_ROOT / ".agents/scripts/crucible_gate.py")}}],
            "content": "Command exited with code 1\nFAILED test_crucible_gate.py",
            "status": "ERROR",
        },
        {
            "step_index": 2,
            "tool_calls": [{"arguments": {"Path": str(HUB_ROOT / ".agents/scripts/tx_patch.py")}}],
            "content": "Command exited with code 0\n5 passed in test_tx_patch.py",
            "status": "DONE",
        },
    ]
    (conv / "transcript.jsonl").write_text("\n".join(json.dumps(x) for x in lines) + "\n", encoding="utf-8")
    out_hist = tmp_path / "ml_history.jsonl"
    ext = ram_ml_engine.extract_transcript_failures(HUB_ROOT, brain_root=brain, out_path=out_hist)
    assert ext["conversations_scanned"] == 1
    assert ext["fail_rows"] == 1
    assert ext["pass_rows"] == 1

    cur = ram_ml_engine.curate_training_dataset(
        HUB_ROOT,
        history_path=out_hist,
        out_path=tmp_path / "ml_curated.jsonl",
    )
    assert cur["curated_rows"] == 2
    assert "crucible_engine" in cur["domain_counts"]


def test_preflight_outcome_gate_realign_and_ready() -> None:
    realign = ram_ml_engine.preflight_outcome_gate(HUB_ROOT, task_text="fix", changed_files=[])
    assert realign["status"] == "REALIGNMENT_REQUIRED"
    assert "outcome_definition" in realign["missing"]

    ready = ram_ml_engine.preflight_outcome_gate(
        HUB_ROOT,
        task_text="Harden crucible_gate.py preflight checks",
        verify_cmd="pwsh -File scripts/verify_all.ps1",
        changed_files=[".agents/scripts/crucible_gate.py"],
    )
    assert ready["status"] == "READY"
    assert len(ready["carry_through_plan"]) == 3
    assert ".agents/scripts/tests/test_crucible_gate.py" in ready["impacted_tests"]


def test_held_out_cv_and_changed_symbols_and_hot_daemon() -> None:
    import ram_ml_daemon

    rank = ram_ml_engine.rank_tests_for_changes(HUB_ROOT, changed_files=[".agents/scripts/crucible_gate.py"])
    if rank["model_mode"] == "supervised_logistic":
        ho = rank["held_out_metrics"]
        assert ho is not None
        assert 0.0 <= ho["precision"] <= 1.0
        assert 0.0 <= ho["recall"] <= 1.0
        assert 0.0 <= ho["f1"] <= 1.0

    syms = ram_ml_engine.extract_changed_symbols(HUB_ROOT, [".agents/scripts/ram_ml_engine.py"])
    assert ".agents/scripts/ram_ml_engine.py" in syms
    assert len(syms[".agents/scripts/ram_ml_engine.py"]) >= 1

    # Start persistent localhost daemon, verify hot roundtrip, and cleanly stop
    started = ram_ml_daemon.start_daemon_background(HUB_ROOT)
    assert started.get("ok"), started
    try:
        bench = ram_ml_daemon.benchmark_hot_daemon(HUB_ROOT, runs=5)
        assert bench["ok"], bench
        assert bench["median_ms"] < 50.0, bench
    finally:
        ram_ml_daemon.stop_daemon(HUB_ROOT)


def test_context_compiler_and_adaptive_commit_risk() -> None:
    ctx = ram_ml_engine.compile_session_context(HUB_ROOT)
    assert "Context Compiler" in ctx["summary_line"]
    assert ctx["active_domain"] in ("crucible_engine", "writers_room", "story_lane", "general")

    # Low-risk non-code doc change (isolated path without live co-change churn) -> LOW tier, strict not escalated
    low = ram_ml_engine.assess_commit_risk(HUB_ROOT, staged_files=["docs/notes.md"])
    assert low["tier"] == "LOW"
    assert low["enforce_strict"] is False

    # High-risk core gate change without paired test -> HIGH tier, escalates strict=True
    high = ram_ml_engine.assess_commit_risk(HUB_ROOT, staged_files=[".agents/scripts/crucible_gate.py"])
    assert high["tier"] == "HIGH"
    assert high["enforce_strict"] is True
    assert high["risk_prob"] >= 0.55


def test_leakage_free_cv_provenance_calibration_and_lift() -> None:
    from collections import Counter

    # Negative leakage test: 1 unique test_name per row, 50% fail / 50% pass, identical changed_files=[]
    # With full-dataset target leakage, f_rate would equal each row's own label (0.0 or 1.0) -> F1 == 1.0.
    # With fold-isolated Laplace smoothing, unseen test_names in val folds receive 0.5 -> F1 < 0.9.
    unique_rows = [
        {"test_name": f"test_unique_{i}.py", "changed_files": [], "outcome": 0 if i % 2 == 0 else 1}
        for i in range(20)
    ]
    u_fails = Counter({r["test_name"]: (1 if r["outcome"] == 0 else 0) for r in unique_rows})
    u_totals = Counter({r["test_name"]: 1 for r in unique_rows})

    clf, mode, train_acc, held_out = ram_ml_engine.fit_supervised_model(u_fails, u_totals, unique_rows)
    assert clf is not None
    assert mode == "supervised_logistic"
    assert train_acc is not None
    assert held_out is not None
    assert held_out["f1"] < 0.9
    prov = held_out["provenance"]
    assert prov["leakage_free_cv"] is True
    assert len(prov["dataset_sha256"]) == 64
    assert all(ch in "0123456789abcdef" for ch in prov["dataset_sha256"])
    assert prov["row_count"] == 20
    assert prov["fail_count"] == 10
    assert prov["pass_count"] == 10
    assert prov["feature_schema"] == ["direct_match", "stem_hit", "laplace_fail_rate", "changed_file_count"]
    assert prov["random_state"] == 42
    assert 0.0 <= held_out["brier_score"] <= 1.0
    assert 0.0 <= held_out["ece"] <= 1.0
    assert 0.0 <= held_out["average_precision"] <= 1.0
    assert held_out["baseline_ap"] == 0.5
    assert held_out["ranking_lift_ap"] == round(held_out["average_precision"] - held_out["baseline_ap"], 4)

    # Positive signal test: repeated test names + stem matches should produce positive ranking lift & good calibration
    signal_rows = []
    for i in range(24):
        is_fail = i < 12
        signal_rows.append(
            {
                "test_name": "test_core_gate.py" if is_fail else "test_readme_doc.py",
                "changed_files": ["core_gate.py"] if is_fail else ["notes.md"],
                "outcome": 0 if is_fail else 1,
            }
        )
    s_fails: Counter[str] = Counter()
    s_totals: Counter[str] = Counter()
    for r in signal_rows:
        s_totals[r["test_name"]] += 1
        if r["outcome"] == 0:
            s_fails[r["test_name"]] += 1

    s_clf, s_mode, _, s_ho = ram_ml_engine.fit_supervised_model(s_fails, s_totals, signal_rows)
    assert s_clf is not None
    assert s_mode == "supervised_logistic"
    assert s_ho is not None
    assert s_ho["ranking_lift_ap"] > 0.0
    assert s_ho["brier_score"] < 0.25

    # Negative bootstrap guard: insufficient rows or single class must fall back cleanly
    clf_small, mode_small, acc_small, ho_small = ram_ml_engine.fit_supervised_model(
        Counter(), Counter(), unique_rows[:4]
    )
    assert clf_small is None
    assert mode_small == "heuristic_bootstrap"
    assert acc_small is None
    assert ho_small is None


def test_record_loop_outcome_and_advise_slice_strategy_escalates(tmp_path: Path) -> None:
    hist = tmp_path / "ml_history.jsonl"

    # Cold start: no prior history -> low risk, fast tier, guards off
    cold = ram_ml_engine.advise_slice_strategy(tmp_path, "s-pay", ["billing.py"], history_path=hist)
    assert cold["recommended_model_tier"] == "flash"
    assert cold["enable_withheld_holdout"] is False
    assert cold["enable_counterexample_ratchet"] is False

    # Record 2 recurring failures with identical error hash -> escalates to pro + holdout + ratchet
    ram_ml_engine.record_loop_outcome(
        tmp_path, "s-pay", ["billing.py"], passed=False, error_sha256="err_refund_01", seconds=1.2, out_path=hist
    )
    ram_ml_engine.record_loop_outcome(
        tmp_path, "s-pay", ["billing.py"], passed=False, error_sha256="err_refund_01", seconds=1.4, out_path=hist
    )
    hot = ram_ml_engine.advise_slice_strategy(tmp_path, "s-pay", ["billing.py"], history_path=hist)
    assert hot["prior_runs"] == 2
    assert hot["prior_failures"] == 2
    assert hot["recommended_model_tier"] == "pro"
    assert hot["enable_withheld_holdout"] is True
    assert hot["enable_counterexample_ratchet"] is True
    assert hot["recurring_error_hashes"] == ["err_refund_01"]


def test_contextual_bandit_ucb1_and_diminishing_returns_frontier_rotation(tmp_path: Path) -> None:
    state_file = tmp_path / "bandit_state.json"
    arms = ("spoken_ear_counterpoint", "exemplar_parity_anchor", "decision_first_scaffold")

    # Cold start pulls untried arms in order
    c1 = ram_ml_engine.select_craft_arm(tmp_path, "av_script:cpl", arms, state_path=state_file)
    assert c1["arm_id"] == "spoken_ear_counterpoint"
    assert c1["pulls"] == 0
    ram_ml_engine.update_craft_arm(tmp_path, "av_script:cpl", c1["arm_id"], 0.90, passed=True, target_key="proj-av", state_path=state_file)

    c2 = ram_ml_engine.select_craft_arm(tmp_path, "av_script:cpl", arms, state_path=state_file)
    assert c2["arm_id"] == "exemplar_parity_anchor"
    ram_ml_engine.update_craft_arm(tmp_path, "av_script:cpl", c2["arm_id"], 0.45, passed=True, target_key="proj-av", state_path=state_file)

    c3 = ram_ml_engine.select_craft_arm(tmp_path, "av_script:cpl", arms, state_path=state_file)
    assert c3["arm_id"] == "decision_first_scaffold"
    ram_ml_engine.update_craft_arm(tmp_path, "av_script:cpl", c3["arm_id"], 0.40, passed=True, target_key="proj-av", state_path=state_file)

    # Now all arms tried: UCB1 must select spoken_ear_counterpoint (0.90 mean)
    c4 = ram_ml_engine.select_craft_arm(tmp_path, "av_script:cpl", arms, state_path=state_file)
    assert c4["arm_id"] == "spoken_ear_counterpoint"
    assert c4["pulls"] == 1

    # Diminishing returns detector: plateau below min_delta over 2 consecutive steps triggers rotation
    improving = ram_ml_engine.assess_diminishing_returns([0.55, 0.72, 0.83], min_delta=0.03, window=2)
    assert improving["saturated"] is False

    plateau = ram_ml_engine.assess_diminishing_returns([0.75, 0.77, 0.78], min_delta=0.03, window=2)
    assert plateau["saturated"] is True
    assert "diminishing returns" in plateau["reason"]

    # Frontier rotator skips saturated target and chooses unvisited or unsaturated target
    state = ram_ml_engine.load_bandit_state(tmp_path, state_file)
    state["trajectories"]["proj-brief"] = [0.70, 0.71, 0.72]  # saturated plateau
    state["trajectories"]["proj-call-sheet"] = [0.60, 0.74]   # still improving
    ram_ml_engine.save_bandit_state(tmp_path, state, state_file)

    pick = ram_ml_engine.select_next_frontier_target(
        tmp_path,
        ["proj-brief", "proj-call-sheet", "proj-shot-list"],
        state_path=state_file,
    )
    # Unvisited proj-shot-list goes first; if only brief + call-sheet, call-sheet wins
    assert pick["selected_id"] == "proj-shot-list"
    pick2 = ram_ml_engine.select_next_frontier_target(
        tmp_path,
        ["proj-brief", "proj-call-sheet"],
        state_path=state_file,
    )
    assert pick2["selected_id"] == "proj-call-sheet"
    assert pick2["all_saturated"] is False
