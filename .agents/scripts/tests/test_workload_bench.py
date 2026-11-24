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

from crucible.form_diagnostics import diagnose_form_deliverable, FORM_PROFILES
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
    assert len(manifest.projects) == 11
    covered_forms = {p.form for p in manifest.projects if p.form}
    assert set(FORM_PROFILES.keys()).issubset(covered_forms)

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
    assert json.loads(val_proc.stdout)["project_count"] == 11

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
    assert run_data["skipped_count"] == 14  # 7 agy_live projects x 2 rounds
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
    assert rep_data["avg_form_score"] > 0.0


def test_form_diagnostics_separates_weak_vs_professional_across_forms() -> None:
    # 1. Weak A/V script (print-prose slop + high WPM + repeating camera) vs tight spoken-ear script
    slop_av = (
        "## Audio & Video Script\n"
        "| Beat | Audio | Video |\n"
        "| --- | --- | --- |\n"
        "| 00:00 - 00:05 | In today's fast-paced world, let's dive in to see the library host standing at the desk holding a VHS tape in front of the camera right now for you. | Host standing at the desk holding a VHS tape in front of camera |\n"
        "Timing: 0:05.\n"
    )
    pro_av = (
        "## Audio & Video Script\n"
        "| Beat | Audio | Video |\n"
        "| --- | --- | --- |\n"
        "| 00:00 - 00:06 | **VO.** Bring one old family tape. | Close-up on hands feeding VHS into library digitizer. |\n"
        "| 00:06 - 00:14 | **VO.** Press record and leave with a clean file. | Screen shows real-time capture progress bar and USB drive. |\n"
        "Timing estimate: 14 seconds total, 130 WPM.\n"
    )
    d_slop = diagnose_form_deliverable(slop_av, "av_script", repo_root=HUB_ROOT)
    d_pro = diagnose_form_deliverable(pro_av, "av_script", repo_root=HUB_ROOT)
    assert d_pro.overall_score > d_slop.overall_score
    assert d_slop.measured_features["estimated_wpm"] > 195.0

    # 2. Exec summary with internal-lens confusion vs clean mandate-custody summary
    bad_exec = "## Summary\nOur new initiative supports the official mandate Grow and looks great.\n"
    good_exec = (
        "Decision requested: Approve Pilot A and Pilot B for internal pre-production.\n"
        "Mandate alignment: Advances official 2027-2030 Experiences and Expertise mandates.\n"
        "Evidence: Grounded in Calgary Public Library/GROUND_TRUTH.md (213-video audit).\n"
        "Limits & Open Holds: [UNKNOWN — OWNER TO CONFIRM] Branch access and G06 release remain pending.\n"
    )
    e_bad = diagnose_form_deliverable(bad_exec, "leadership_report", repo_root=HUB_ROOT, strict_cpl_mandates=True)
    e_good = diagnose_form_deliverable(good_exec, "leadership_report", repo_root=HUB_ROOT, strict_cpl_mandates=True)
    assert e_good.overall_score > e_bad.overall_score
    assert e_bad.measured_features["mandate_ok"] is False

    # 3. Call sheet vs Content calendar distinct form features
    good_call = (
        "## Call Sheet\n"
        "Door opens 09:00, reset by 11:00. Owner: Producer.\n"
        "| Window | Who | Gate & Fallback |\n"
        "| --- | --- | --- |\n"
        "| 09:00-09:30 | Producer & Sound helper | Sound lav test at -12 dBFS; fallback to battery if house power unavailable; coverage playback check before wrap. |\n"
    )
    good_cal = (
        "## Content Calendar\n"
        "### YouTube Preview\nWatch the 30-second digitizer preview and click the resource link.\n"
        "### Instagram Reel\nVertical crop with muted-safe captions and profile link route.\n"
        "### Newsletter\nEducator segment copy linking unlisted preview.\n"
        "### Milestones & Exposure\nTuesday unlisted handoff (CH-04 hold) before Friday public rollout pending CTA check.\n"
    )
    assert diagnose_form_deliverable(good_call, "call_sheet", repo_root=HUB_ROOT).device_score >= 0.9
    assert diagnose_form_deliverable(good_cal, "content_calendar", repo_root=HUB_ROOT).device_score >= 0.85


def test_adaptive_bench_learns_from_weakness_and_rotates_on_diminishing_returns(tmp_path: Path) -> None:
    manifest = load_workload_manifest(
        {
            "version": "1.0",
            "defaults": {
                "staging_dir": "runs",
                "telemetry_file": "tel.jsonl",
                "ml_history_file": "ml.jsonl",
                "bandit_state_file": "bandit.json",
                "timeout_seconds": 15,
                "max_retries": 0,
            },
            "projects": [
                {
                    "id": "p-av-script",
                    "domain": "personal_creative",
                    "mode": "agy_live",
                    "form": "av_script",
                    "intent": "Write a crisp 20s A/V script.",
                    "deliverable": "script.md",
                    "public_checks": {"required_sections": ["Audio", "Video", "Timing"]},
                },
                {
                    "id": "p-call-sheet",
                    "domain": "personal_creative",
                    "mode": "agy_live",
                    "form": "call_sheet",
                    "intent": "Write a crew call sheet.",
                    "deliverable": "call.md",
                    "public_checks": {"required_sections": ["Window", "Sound", "Coverage", "Reset"]},
                },
            ],
        }
    )

    prompts_seen: list[str] = []

    def progressive_worker(prompt: str, _root: Path, _timeout_s: float) -> tuple[bool, str]:
        prompts_seen.append(prompt)
        if "p-call-sheet" in prompt or "call sheet" in prompt.lower():
            return (
                True,
                "Door 09:00, reset 11:00. Owner: Producer.\n"
                "| Window | Who | Gate & Fallback |\n| --- | --- | --- |\n"
                "| 09:00-10:00 | Crew | Sound lav test + camera coverage test; fallback battery; reset by 11:00. |\n",
            )
        # p-av-script improves on round 2 when Prior Round Weakness is fed in, then plateaus at saturation
        if "Prior Round Weakness" not in prompt:
            return (
                True,
                "## Audio & Video\n| Beat | Audio | Video |\n| --- | --- | --- |\n"
                "| 00:00 - 00:04 | In today's fast-paced world let's dive into a shot of a table with paper and pencil on top of it right now. | Shot of a table with paper and pencil |\n"
                "Timing: 0:04.\n",
            )
        return (
            True,
            "## Audio & Video Script\n| Beat | Audio | Video |\n| --- | --- | --- |\n"
            "| 00:00 - 00:06 | **VO.** Fold the sheet in half. | Overhead close-up of hands creasing blank paper. |\n"
            "| 00:06 - 00:14 | **VO.** Open it and sketch around the line. | Pencil draws eyes straddling the vertical crease. |\n"
            "Timing estimate: 14 seconds at 120 WPM.\n",
        )

    res = run_workload_bench(tmp_path, manifest, mode_filter="all", rounds=3, adaptive=True, agy_worker_fn=progressive_worker)
    rotations = [f["selected_id"] for f in res["frontier_rotations"]]
    assert rotations == ["p-av-script", "p-call-sheet", "p-av-script"]
    av_receipts = [r for r in res["receipts"] if r["project_id"] == "p-av-script"]
    assert len(av_receipts) == 2
    assert av_receipts[1]["diagnostic_score"] > av_receipts[0]["diagnostic_score"]
    assert any("Prior Round Weakness" in p for p in prompts_seen)

    bandit = json.loads((tmp_path / "bandit.json").read_text(encoding="utf-8"))
    assert "av_script:personal_creative" in bandit["contexts"]
    assert len(bandit["trajectories"]["p-av-script"]) == 2
    assert len(bandit["trajectories"]["p-call-sheet"]) == 1
