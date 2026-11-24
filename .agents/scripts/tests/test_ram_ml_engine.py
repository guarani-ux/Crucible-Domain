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
