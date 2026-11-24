"""Tests for YAML-driven Crucible Workload Bench (CPL, Creative & Antigravity Proving Ground)."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
HUB_ROOT = SCRIPTS_DIR.parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from crucible.workload_bench import (
    WorkloadSpecError,
    evaluate_deliverable,
    load_workload_manifest,
    run_workload_bench,
    summarize_bench_telemetry,
)


def test_load_workload_manifest_rejects_invalid_and_accepts_starter() -> None:
    starter = HUB_ROOT / ".agents" / "bench" / "workloads.yaml"
    manifest = load_workload_manifest(starter)
    assert manifest.version == "1.0"
    assert len(manifest.projects) == 5

    with pytest.raises(WorkloadSpecError) as exc_info:
        load_workload_manifest(
            {
                "version": "1.0",
                "projects": [
                    {
                        "id": "escape-test",
                        "domain": "bad_domain",
                        "mode": "plumbing",
                        "deliverable": "../outside.md",
                    }
                ],
            }
        )
    err_text = "; ".join(exc_info.value.errors)
    assert "bad_domain" in err_text
    assert "safe relative filename" in err_text
    assert "planted_faults" in err_text


def test_cpl_blind_holdout_catches_lens_as_mandate_but_allows_distinction() -> None:
    holdouts = {
        "require_official_cpl_mandate": True,
        "forbid_terms_as_mandates": ["Grow", "Books & Reading", "Community"],
        "forbid_unverified_claims": ["approved for release"],
        "failure_category": "cpl_mandate_or_authority_violation",
    }
    pub = {"max_words": 200, "required_sections": ["Patron Problem"]}

    bad_lens = (
        "## Patron Problem\n"
        "Supports Collections and the official 2027-2030 mandate Grow.\n"
    )
    pub_ok, hold_ok, cat, detail = evaluate_deliverable(bad_lens, pub, holdouts)
    assert pub_ok is True
    assert hold_ok is False
    assert cat == "cpl_mandate_or_authority_violation"
    assert "Grow" not in detail  # Blindness invariant: never leak forbidden list

    good_distinct = (
        "## Patron Problem\n"
        "Advances official 2027-2030 mandates Collections and Expertise "
        "(keeping internal lenses like Grow distinct from official mandates).\n"
    )
    pub_ok2, hold_ok2, cat2, _ = evaluate_deliverable(good_distinct, pub, holdouts)
    assert pub_ok2 is True
    assert hold_ok2 is True
    assert cat2 == ""


def test_agy_live_worker_retry_repairs_blind_holdout_without_leaking_secrets(tmp_path: Path) -> None:
    (tmp_path / "Calgary Public Library").mkdir(parents=True)
    (tmp_path / "Calgary Public Library" / "GROUND_TRUTH.md").write_text("# CPL Ground Truth\n", encoding="utf-8")

    manifest = load_workload_manifest(
        {
            "version": "1.0",
            "defaults": {
                "staging_dir": "bench_runs",
                "telemetry_file": "bench_telemetry.jsonl",
                "ml_history_file": "ml_history.jsonl",
                "timeout_seconds": 10,
                "max_retries": 1,
            },
            "projects": [
                {
                    "id": "cpl-live-retry",
                    "domain": "cpl_research",
                    "mode": "agy_live",
                    "intent": "Draft Episode 2 scenario citing Calgary Public Library/GROUND_TRUTH.md",
                    "deliverable": "ep02.md",
                    "public_checks": {"max_words": 150, "required_sections": ["Patron Scenarios"], "must_cite_local_files": True},
                    "blind_holdouts": {
                        "require_official_cpl_mandate": True,
                        "forbid_terms_as_mandates": ["Grow"],
                        "failure_category": "cpl_mandate_violation",
                    },
                }
            ],
        }
    )

    seen_prompts: list[str] = []

    def fake_agy_worker(prompt: str, _root: Path, _timeout_s: float) -> tuple[bool, str]:
        seen_prompts.append(prompt)
        if len(seen_prompts) == 1:
            # First attempt violates blind holdout by calling Grow an official mandate
            return (
                True,
                "## Patron Scenarios\nSee Calgary Public Library/GROUND_TRUTH.md under official mandate Grow and Collections.\n",
            )
        # Second attempt sees sanitized failure category (never the raw forbidden list) and fixes it
        return (
            True,
            "## Patron Scenarios\nSee Calgary Public Library/GROUND_TRUTH.md under official 2027-2030 Collections and Expertise mandates.\n",
        )

    res = run_workload_bench(tmp_path, manifest, mode_filter="all", agy_worker_fn=fake_agy_worker)
    assert res["ok"] is True
    assert len(seen_prompts) == 2
    assert "Grow" not in seen_prompts[0]
    assert "cpl_mandate_violation" in seen_prompts[1]
    assert "forbid_terms_as_mandates" not in seen_prompts[1]
    assert res["receipts"][0]["retries_used"] == 1
    assert len(res["deliverables"]) == 1
    assert (tmp_path / res["deliverables"][0]).is_file()

    summary = summarize_bench_telemetry(tmp_path / "bench_telemetry.jsonl")
    assert summary["total_runs"] == 1
    assert summary["pass_rate"] == 1.0


def test_cli_bench_validate_run_offline_and_report_end_to_end(tmp_path: Path) -> None:
    import yaml as _yaml

    starter = HUB_ROOT / ".agents" / "bench" / "workloads.yaml"
    raw = _yaml.safe_load(starter.read_text(encoding="utf-8"))
    raw["defaults"]["staging_dir"] = str(tmp_path / "runs")
    raw["defaults"]["telemetry_file"] = str(tmp_path / "telemetry.jsonl")
    raw["defaults"]["ml_history_file"] = str(tmp_path / "ml_hist.jsonl")
    temp_yaml = tmp_path / "workloads.yaml"
    temp_yaml.write_text(_yaml.safe_dump(raw), encoding="utf-8")

    val_proc = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "crucible_gate.py"), "bench", "validate", str(temp_yaml), "--json"],
        cwd=HUB_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert val_proc.returncode == 0, val_proc.stderr
    assert json.loads(val_proc.stdout)["project_count"] == 5

    run_proc = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS_DIR / "crucible_gate.py"),
            "bench",
            "run",
            str(temp_yaml),
            "--mode",
            "offline",
            "--rounds",
            "2",
            "--json",
        ],
        cwd=HUB_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert run_proc.returncode == 0, run_proc.stderr
    run_data = json.loads(run_proc.stdout)
    assert run_data["ok"] is True
    assert run_data["executed_count"] == 8  # 4 offline projects x 2 rounds
    assert run_data["skipped_count"] == 2   # 1 agy_live project x 2 rounds
    assert len(run_data["deliverables"]) == 4

    rep_proc = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "crucible_gate.py"), "bench", "report", str(tmp_path / "telemetry.jsonl"), "--json"],
        cwd=HUB_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert rep_proc.returncode == 0, rep_proc.stderr
    rep_data = json.loads(rep_proc.stdout)
    assert rep_data["total_runs"] == 8
    assert rep_data["planted_caught"] == 8
    assert rep_data["planted_total"] == 8
