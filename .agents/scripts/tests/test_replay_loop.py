"""Tests for CD-W45 autonomous discovery, replay-verified execution & fault-recovery loop."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from crucible.campaign_ir import (
    CampaignSpec,
    RatchetEntry,
    SliceNode,
    append_ratchet_ledger,
    compile_campaign,
    load_campaign_spec,
    load_ratchet_ledger,
)
from crucible.replay_loop import (
    CounterexampleProbe,
    CounterexampleRatchet,
    audit_campaign_chain,
    discover_gaps,
    execute_replay_verified_slice,
    is_grounded_anchor,
    replay_trace_file,
    run_autonomous_campaign,
    run_counterexample_probe,
)


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _init_temp_git_repo(repo_dir: Path) -> None:
    subprocess.run(["git", "init"], cwd=repo_dir, check=True, capture_output=True, text=True)
    subprocess.run(
        ["git", "config", "user.email", "test@crucible.local"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ["git", "config", "user.name", "Crucible Test"],
        cwd=repo_dir,
        check=True,
        capture_output=True,
        text=True,
    )


def test_discover_gaps_planted_faults_and_clean_negative_control(tmp_path: Path) -> None:
    dirty_repo = tmp_path / "dirty_repo"
    (dirty_repo / ".agents" / "scripts" / "crucible").mkdir(parents=True)
    (dirty_repo / ".agents" / "plugins" / "spoke_a").mkdir(parents=True)
    (dirty_repo / "Graphs").mkdir(parents=True)

    # 1. Planted Python syntax error
    (dirty_repo / ".agents" / "scripts" / "broken_mod.py").write_text(
        "def broken(:\n    pass\n",
        encoding="utf-8",
    )
    # 2. Planted hardcoded Windows drive-letter path in mcp_config.json
    (dirty_repo / ".agents" / "plugins" / "spoke_a" / "mcp_config.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "spoke_a": {
                        "command": "python",
                        "args": ["server.py"],
                        "cwd": "D:/portable_drive/missing_spoke_dir",
                    }
                }
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    # 3. Planted stale depends_on_sha256 in Graphs/
    source_doc = dirty_repo / "Graphs" / "upstream.md"
    source_doc.write_text("# Upstream v2\n", encoding="utf-8")
    stale_hash = "0" * 64
    (dirty_repo / "Graphs" / "downstream.md").write_text(
        "---\n"
        "depends_on:\n"
        "  - Graphs/upstream.md\n"
        "depends_on_sha256:\n"
        f"  Graphs/upstream.md: {stale_hash}\n"
        "---\n"
        "# Downstream\n",
        encoding="utf-8",
    )

    report = discover_gaps(dirty_repo)
    kinds = {g.kind for g in report.gaps}
    assert "syntax_error" in kinds
    assert "mcp_hardcoded_path" in kinds
    assert "stale_depends_on_sha256" in kinds

    slices = report.campaign_spec["slices"]
    target_paths = [p for s in slices for p in s["target_paths"]]
    assert len(target_paths) == len(set(target_paths))
    compiled = compile_campaign(load_campaign_spec(report.campaign_spec))
    assert len(compiled) >= 3

    # Clean negative control: valid Python, portable MCP config, matching SHA-256
    clean_repo = tmp_path / "clean_repo"
    (clean_repo / ".agents" / "scripts" / "pkg").mkdir(parents=True)
    (clean_repo / ".agents" / "plugins" / "spoke_clean").mkdir(parents=True)
    (clean_repo / "Graphs").mkdir(parents=True)

    (clean_repo / ".agents" / "scripts" / "pkg" / "__init__.py").write_text("", encoding="utf-8")
    (clean_repo / ".agents" / "scripts" / "pkg" / "lib.py").write_text(
        "def compute(x: int) -> int:\n    return x + 1\n",
        encoding="utf-8",
    )
    (clean_repo / ".agents" / "scripts" / "pkg" / "caller.py").write_text(
        "from pkg.lib import compute\n\ndef run() -> int:\n    return compute(2)\n",
        encoding="utf-8",
    )
    (clean_repo / ".agents" / "plugins" / "spoke_clean" / "mcp_config.json").write_text(
        json.dumps({"mcpServers": {"spoke_clean": {"command": "python", "args": ["srv.py"]}}}),
        encoding="utf-8",
    )
    clean_upstream = clean_repo / "Graphs" / "upstream.md"
    clean_upstream_bytes = b"# Upstream v1\n"
    clean_upstream.write_bytes(clean_upstream_bytes)
    good_sha = _sha256_bytes(clean_upstream_bytes)
    (clean_repo / "Graphs" / "downstream.md").write_text(
        "---\n"
        "depends_on:\n"
        "  - Graphs/upstream.md\n"
        "depends_on_sha256:\n"
        f"  Graphs/upstream.md: {good_sha}\n"
        "---\n"
        "# Downstream\n",
        encoding="utf-8",
    )

    clean_report = discover_gaps(clean_repo)
    blocking = [g for g in clean_report.gaps if g.severity in ("FAIL", "WARN")]
    assert blocking == []
    assert clean_report.campaign_spec["slices"] == []


def test_execute_replay_verified_slice_ram_fault_rollback(tmp_path: Path) -> None:
    target = tmp_path / "module.py"
    original_bytes = b"VALUE = 1\n"
    target.write_bytes(original_bytes)

    node = SliceNode(id="slice-ram-fail", target_paths=["module.py"])

    def apply_fn(root: Path) -> None:
        (root / "module.py").write_bytes(b"VALUE = 999\n")

    def verify_fn(root: Path) -> tuple[bool, str]:
        return False, "unit test failed on VALUE == 999"

    diff = execute_replay_verified_slice(
        tmp_path,
        node,
        apply_fn=apply_fn,
        verify_fn=verify_fn,
        use_worktree=False,
    )
    assert diff.passed is False
    assert diff.replay_verified is False
    assert diff.rolled_back is True
    assert diff.diff_text == ""
    assert diff.worktree_used is False
    assert "unit test failed" in diff.error
    assert target.read_bytes() == original_bytes


def test_execute_replay_verified_slice_rejects_replay_drift(tmp_path: Path) -> None:
    target = tmp_path / "drifty.py"
    original_bytes = b"STATE = 'clean'\n"
    target.write_bytes(original_bytes)

    node = SliceNode(id="slice-drift", target_paths=["drifty.py"])
    calls = {"count": 0}

    def apply_fn(root: Path) -> None:
        (root / "drifty.py").write_bytes(b"STATE = 'updated'\n")

    def nondeterministic_verify(root: Path) -> tuple[bool, str]:
        calls["count"] += 1
        if calls["count"] == 1:
            return True, "first pass ok"
        (root / "drifty.py").write_bytes(b"STATE = 'mutated_on_replay'\n")
        return True, "second pass mutated"

    diff = execute_replay_verified_slice(
        tmp_path,
        node,
        apply_fn=apply_fn,
        verify_fn=nondeterministic_verify,
        use_worktree=False,
    )
    assert calls["count"] == 2
    assert diff.passed is False
    assert diff.replay_verified is False
    assert diff.rolled_back is True
    assert diff.diff_text == ""
    assert diff.after_sha256 != diff.replay_sha256
    assert "REPLAY_DRIFT" in diff.error
    assert target.read_bytes() == original_bytes


def test_execute_replay_verified_slice_worktree_pass_fail_and_cleanup(tmp_path: Path) -> None:
    repo = tmp_path / "git_repo"
    repo.mkdir()
    _init_temp_git_repo(repo)
    target = repo / "app.py"
    target.write_text("VERSION = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "app.py"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "initial commit"], cwd=repo, check=True, capture_output=True)

    # 1. Passing slice in isolated worktree
    pass_node = SliceNode(id="wt-pass", target_paths=["app.py"])

    def apply_good(work_root: Path) -> None:
        (work_root / "app.py").write_text("VERSION = 2\n", encoding="utf-8")

    def verify_good(work_root: Path) -> tuple[bool, str]:
        text = (work_root / "app.py").read_text(encoding="utf-8")
        return ("VERSION = 2" in text), "version check"

    pass_diff = execute_replay_verified_slice(
        repo,
        pass_node,
        apply_fn=apply_good,
        verify_fn=verify_good,
        use_worktree=True,
    )
    assert pass_diff.passed is True
    assert pass_diff.replay_verified is True
    assert pass_diff.rolled_back is False
    assert pass_diff.worktree_used is True
    assert "-VERSION = 1" in pass_diff.diff_text
    assert "+VERSION = 2" in pass_diff.diff_text
    assert target.read_text(encoding="utf-8") == "VERSION = 2\n"

    wt_list_after_pass = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert wt_list_after_pass.count("worktree ") == 1

    # 2. Failing slice in isolated worktree leaves main repo untouched and cleans up worktree
    fail_node = SliceNode(id="wt-fail", target_paths=["app.py"])

    def apply_bad(work_root: Path) -> None:
        (work_root / "app.py").write_text("VERSION = 999\n", encoding="utf-8")

    def verify_bad(work_root: Path) -> tuple[bool, str]:
        return False, "worktree verification failed"

    fail_diff = execute_replay_verified_slice(
        repo,
        fail_node,
        apply_fn=apply_bad,
        verify_fn=verify_bad,
        use_worktree=True,
    )
    assert fail_diff.passed is False
    assert fail_diff.replay_verified is False
    assert fail_diff.rolled_back is True
    assert fail_diff.worktree_used is True
    assert fail_diff.diff_text == ""
    assert target.read_text(encoding="utf-8") == "VERSION = 2\n"

    wt_list_after_fail = subprocess.run(
        ["git", "worktree", "list", "--porcelain"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    assert wt_list_after_fail.count("worktree ") == 1


def test_run_autonomous_campaign_breaker_and_replay_trace(tmp_path: Path) -> None:
    # 1. Passing multi-slice campaign + trace replay + incremental cache skip
    pass_repo = tmp_path / "pass_campaign"
    pass_repo.mkdir()
    (pass_repo / "a.py").write_text("A = 0\n", encoding="utf-8")
    (pass_repo / "b.py").write_text("B = 0\n", encoding="utf-8")

    pass_spec = CampaignSpec(
        name="camp-pass",
        repo_root=str(pass_repo),
        allowed_roots=[str(pass_repo)],
        slices=[
            SliceNode(id="s1", target_paths=["a.py"]),
            SliceNode(id="s2", target_paths=["b.py"], depends_on=["s1"]),
        ],
    )
    trace_path = tmp_path / "trace.jsonl"
    cache_path = tmp_path / "checkpoint.json"
    ledger_path = tmp_path / "ratchet.tsv"

    apply_map = {
        "s1": lambda r: (r / "a.py").write_text("A = 1\n", encoding="utf-8"),
        "s2": lambda r: (r / "b.py").write_text("B = 2\n", encoding="utf-8"),
    }
    verify_map = {
        "s1": lambda r: ("A = 1" in (r / "a.py").read_text(encoding="utf-8"), "a ok"),
        "s2": lambda r: ("B = 2" in (r / "b.py").read_text(encoding="utf-8"), "b ok"),
    }

    res = run_autonomous_campaign(
        pass_repo,
        pass_spec,
        apply_map=apply_map,
        verify_map=verify_map,
        cache_path=cache_path,
        trace_path=trace_path,
        ledger_path=ledger_path,
    )
    assert res["ok"] is True
    assert res["breaker_tripped"] is False
    assert len(res["verified_diffs"]) == 2
    assert all(d["replay_verified"] for d in res["verified_diffs"])

    ledger_rows = load_ratchet_ledger(ledger_path)
    assert [row.status for row in ledger_rows] == ["KEEP", "KEEP"]

    replay_report = replay_trace_file(trace_path, pass_repo, verify_map=verify_map)
    assert replay_report["replay_ok"] is True
    assert replay_report["total"] == 2
    assert replay_report["mismatches"] == []

    # Tampered live verify triggers mismatch in replay_trace_file
    mismatch_report = replay_trace_file(
        trace_path,
        pass_repo,
        verify_map={"s1": lambda r: (False, "injected mismatch")},
    )
    assert mismatch_report["replay_ok"] is False
    assert len(mismatch_report["mismatches"]) == 1

    # 2. Failing campaign with identical error hashes trips ErrorCircuitBreaker
    fail_repo = tmp_path / "fail_campaign"
    fail_repo.mkdir()
    (fail_repo / "x.py").write_text("X = 0\n", encoding="utf-8")
    (fail_repo / "y.py").write_text("Y = 0\n", encoding="utf-8")
    (fail_repo / "z.py").write_text("Z = 0\n", encoding="utf-8")

    fail_spec = CampaignSpec(
        name="camp-breaker",
        repo_root=str(fail_repo),
        allowed_roots=[str(fail_repo)],
        slices=[
            SliceNode(id="f1", target_paths=["x.py"]),
            SliceNode(id="f2", target_paths=["y.py"]),
            SliceNode(id="f3", target_paths=["z.py"]),
        ],
    )
    fail_ledger = tmp_path / "fail_ratchet.tsv"
    fail_trace = tmp_path / "fail_trace.jsonl"

    fail_res = run_autonomous_campaign(
        fail_repo,
        fail_spec,
        apply_map={
            "f1": lambda r: (r / "x.py").write_text("X = 1\n", encoding="utf-8"),
            "f2": lambda r: (r / "y.py").write_text("Y = 1\n", encoding="utf-8"),
            "f3": lambda r: (r / "z.py").write_text("Z = 1\n", encoding="utf-8"),
        },
        verify_map={
            "f1": lambda r: (False, "IDENTICAL_ERR"),
            "f2": lambda r: (False, "IDENTICAL_ERR"),
            "f3": lambda r: (False, "IDENTICAL_ERR"),
        },
        trace_path=fail_trace,
        ledger_path=fail_ledger,
    )
    assert fail_res["ok"] is False
    assert fail_res["breaker_tripped"] is True
    assert fail_res["breaker_reason"] == "IDENTICAL_ERROR_HASH"
    assert fail_res["verified_diffs"] == []
    assert fail_res["rounds_used"] == 2
    assert (fail_repo / "x.py").read_text(encoding="utf-8") == "X = 0\n"
    assert (fail_repo / "y.py").read_text(encoding="utf-8") == "Y = 0\n"
    assert (fail_repo / "z.py").read_text(encoding="utf-8") == "Z = 0\n"

    fail_rows = load_ratchet_ledger(fail_ledger)
    assert [row.status for row in fail_rows] == ["REVERT", "TRIPPED"]


def test_withheld_holdout_rolls_back_without_leaking_private_output(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    target.write_text("MODE = 'orig'\n", encoding="utf-8")

    node = SliceNode(
        id="s-withheld",
        target_paths=["app.py"],
        verify_cmd=f'"{sys.executable}" -c "import app; assert app.MODE == \'candidate\'"',
        withheld_verify_cmd=(
            f'"{sys.executable}" -c "import sys; print(\'PRIVATE_SECRET_ANSWER_99\'); sys.exit(1)"'
        ),
        withheld_failure_category="unicode_encoding_damage",
    )

    def apply_candidate(root: Path) -> None:
        (root / "app.py").write_text("MODE = 'candidate'\n", encoding="utf-8")

    diff = execute_replay_verified_slice(tmp_path, node, apply_fn=apply_candidate)
    assert diff.passed is False
    assert diff.rolled_back is True
    assert "WITHHELD_HOLDOUT_FAILED: unicode_encoding_damage" in diff.error
    assert "PRIVATE_SECRET_ANSWER_99" not in diff.error
    assert target.read_text(encoding="utf-8") == "MODE = 'orig'\n"


def test_counterexample_ratchet_catches_refund_bug_and_promotes_inherited_check(tmp_path: Path) -> None:
    target = tmp_path / "ledger.py"
    target.write_text("def net_total(xs):\n    return 0\n", encoding="utf-8")

    objective = "Compute net cents from signed integers. Negative refunds must subtract from the total."
    ratchet_file = tmp_path / "ratchet.json"
    ratchet = CounterexampleRatchet(persist_path=ratchet_file)

    node = SliceNode(
        id="s-refund",
        target_paths=["ledger.py"],
        verify_cmd=f'"{sys.executable}" -c "import ledger; assert ledger.net_total([100, 50]) == 150"',
    )

    refund_probe = CounterexampleProbe(
        id="cx-refund-1",
        anchor="Negative refunds must subtract from the total.",
        command=f'"{sys.executable}" -c "import ledger; print(ledger.net_total([100, -40]))"',
        expected_stdout="60",
        repair_category="compute result",
    )

    # Round 1: buggy abs() implementation passes public check, caught by confirmed counterexample
    def apply_buggy_abs(root: Path) -> None:
        (root / "ledger.py").write_text("def net_total(xs):\n    return sum(abs(x) for x in xs)\n", encoding="utf-8")

    diff1 = execute_replay_verified_slice(
        tmp_path,
        node,
        apply_fn=apply_buggy_abs,
        ratchet=ratchet,
        objective=objective,
        propose_fn=lambda: refund_probe,
        second_opinion_fn=lambda _p: (True, "Negative refunds must subtract from the total.", "60"),
    )
    assert diff1.passed is False
    assert diff1.rolled_back is True
    assert "REALIGN_GOAL: compute result to satisfy Negative refunds must subtract from the total." in diff1.error
    assert target.read_text(encoding="utf-8") == "def net_total(xs):\n    return 0\n"
    assert len(ratchet.inherited) == 1
    assert ratchet_file.is_file()

    # Round 2: reload ratchet from disk; repaired candidate passes public + inherited refund probe
    reloaded_ratchet = CounterexampleRatchet(persist_path=ratchet_file)
    assert len(reloaded_ratchet.inherited) == 1

    def apply_fixed_sum(root: Path) -> None:
        (root / "ledger.py").write_text("def net_total(xs):\n    return sum(xs)\n", encoding="utf-8")

    diff2 = execute_replay_verified_slice(
        tmp_path,
        node,
        apply_fn=apply_fixed_sum,
        ratchet=reloaded_ratchet,
        objective=objective,
    )
    assert diff2.passed is True
    assert diff2.rolled_back is False
    assert target.read_text(encoding="utf-8") == "def net_total(xs):\n    return sum(xs)\n"


def test_counterexample_ratchet_guards_grounding_duplicates_and_disagreement(tmp_path: Path) -> None:
    objective = "Negative refunds must subtract from the total."
    assert is_grounded_anchor("Negative refunds", objective) is True
    assert is_grounded_anchor("invented requirement", objective) is False
    assert is_grounded_anchor("refunds", objective) is False

    ratchet = CounterexampleRatchet()

    ungrounded = CounterexampleProbe(
        id="cx-bad",
        anchor="invented requirement",
        command=f'"{sys.executable}" -c "print(1)"',
        expected_stdout="1",
    )
    res_ungrounded = ratchet.evaluate(tmp_path, objective, propose_fn=lambda: ungrounded)
    assert res_ungrounded.passed is False
    assert "GOAL_REQUIRES_CLARIFICATION" in res_ungrounded.reason
    assert len(ratchet.inherited) == 0

    disputed = CounterexampleProbe(
        id="cx-disputed",
        anchor="Negative refunds must subtract",
        command=f'"{sys.executable}" -c "print(140)"',
        expected_stdout="60",
    )
    res_disputed = ratchet.evaluate(
        tmp_path,
        objective,
        propose_fn=lambda: disputed,
        second_opinion_fn=lambda _p: (True, "Negative refunds must subtract", "999"),
    )
    assert res_disputed.passed is False
    assert "GOAL_REQUIRES_CLARIFICATION" in res_disputed.reason
    assert len(ratchet.inherited) == 0

    passing = CounterexampleProbe(
        id="cx-ok",
        anchor="Negative refunds must subtract",
        command=f'"{sys.executable}" -c "print(60)"',
        expected_stdout="60",
    )
    res_ok = ratchet.evaluate(tmp_path, objective, propose_fn=lambda: passing)
    assert res_ok.passed is True
    assert len(ratchet.inherited) == 1

    res_dup = ratchet.evaluate(tmp_path, objective, propose_fn=lambda: passing)
    assert res_dup.passed is False
    assert "REJECT_DUPLICATE_PROBE" in res_dup.reason


def test_hard_subprocess_timeouts_roll_back_cleanly(tmp_path: Path) -> None:
    target = tmp_path / "slow.py"
    target.write_text("X = 0\n", encoding="utf-8")

    sleep_cmd = f'"{sys.executable}" -c "import time; time.sleep(5)"'
    node_pub = SliceNode(
        id="s-timeout-pub",
        target_paths=["slow.py"],
        verify_cmd=sleep_cmd,
        verify_timeout_s=0.3,
    )
    diff_pub = execute_replay_verified_slice(
        tmp_path,
        node_pub,
        apply_fn=lambda root: (root / "slow.py").write_text("X = 1\n", encoding="utf-8"),
    )
    assert diff_pub.passed is False
    assert diff_pub.rolled_back is True
    assert "VERIFY_TIMEOUT" in diff_pub.error
    assert target.read_text(encoding="utf-8") == "X = 0\n"

    node_withheld = SliceNode(
        id="s-timeout-withheld",
        target_paths=["slow.py"],
        verify_cmd=f'"{sys.executable}" -c "print(1)"',
        withheld_verify_cmd=sleep_cmd,
        withheld_failure_category="holdout_timeout",
        verify_timeout_s=0.3,
    )
    diff_w = execute_replay_verified_slice(
        tmp_path,
        node_withheld,
        apply_fn=lambda root: (root / "slow.py").write_text("X = 2\n", encoding="utf-8"),
    )
    assert diff_w.passed is False
    assert diff_w.rolled_back is True
    assert "WITHHELD_HOLDOUT_FAILED: holdout_timeout" in diff_w.error
    assert target.read_text(encoding="utf-8") == "X = 0\n"

    probe = CounterexampleProbe(
        id="cx-slow",
        anchor="must terminate quickly",
        command=sleep_cmd,
        expected_stdout="ok",
    )
    matched, rc, out = run_counterexample_probe(tmp_path, probe, timeout_s=0.3)
    assert matched is False
    assert rc == -1
    assert "PROBE_TIMEOUT" in out


def test_run_autonomous_campaign_closed_ml_feedback_escalates_on_next_run(tmp_path: Path) -> None:
    target = tmp_path / "mod.py"
    target.write_text("X = 0\n", encoding="utf-8")
    ml_hist = tmp_path / "ml_history.jsonl"

    spec = CampaignSpec(
        name="ml-feedback-campaign",
        repo_root=str(tmp_path),
        slices=[SliceNode(id="s-ml", target_paths=["mod.py"])],
        max_rounds=4,
    )

    # Run 1 (fails): cold advisory is flash; failure gets written to ml_history.jsonl
    res1 = run_autonomous_campaign(
        tmp_path,
        spec,
        apply_map={"s-ml": lambda root: (root / "mod.py").write_text("X = 1\n", encoding="utf-8")},
        verify_map={"s-ml": lambda _root: (False, "same deterministic failure")},
        ml_history_path=ml_hist,
    )
    assert res1["ok"] is False
    assert res1["slice_advisories"]["s-ml"]["recommended_model_tier"] == "flash"
    assert ml_hist.is_file()

    # Run 2 (fails again with same error hash): escalates further
    res2 = run_autonomous_campaign(
        tmp_path,
        spec,
        apply_map={"s-ml": lambda root: (root / "mod.py").write_text("X = 1\n", encoding="utf-8")},
        verify_map={"s-ml": lambda _root: (False, "same deterministic failure")},
        ml_history_path=ml_hist,
    )
    assert res2["ok"] is False
    assert res2["slice_advisories"]["s-ml"]["prior_failures"] == 1

    # Run 3 (succeeds): pre-slice ML advisory now sees 2 recurring failures -> recommends pro + holdout + ratchet
    res3 = run_autonomous_campaign(
        tmp_path,
        spec,
        apply_map={"s-ml": lambda root: (root / "mod.py").write_text("X = 2\n", encoding="utf-8")},
        verify_map={"s-ml": lambda _root: (True, "ok")},
        ml_history_path=ml_hist,
    )
    assert res3["ok"] is True
    adv3 = res3["slice_advisories"]["s-ml"]
    assert adv3["recommended_model_tier"] == "pro"
    assert adv3["enable_withheld_holdout"] is True
    assert adv3["enable_counterexample_ratchet"] is True
    assert len(ml_hist.read_text(encoding="utf-8").splitlines()) == 3


def test_audit_campaign_chain_replays_git_commits_and_catches_scope_or_sha_tamper(tmp_path: Path) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test User"], cwd=repo, check=True)

    (repo / "a.py").write_text("VAL = 1\n", encoding="utf-8")
    (repo / "b.py").write_text("OTHER = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "init"], cwd=repo, check=True, capture_output=True)

    # Commit 1: valid scoped edit to a.py
    (repo / "a.py").write_text("VAL = 2\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "slice a"], cwd=repo, check=True, capture_output=True)
    sha1 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()

    from crucible.replay_loop import _hash_target_state

    after_sha1 = _hash_target_state(repo, ["a.py"])
    spec = CampaignSpec(
        name="audit-chain-test",
        repo_root=str(repo),
        slices=[
            SliceNode(
                id="s-a",
                target_paths=["a.py"],
                verify_cmd=f'"{sys.executable}" -c "import a; assert a.VAL == 2"',
            )
        ],
    )
    ledger = tmp_path / "results.tsv"
    append_ratchet_ledger(
        ledger,
        RatchetEntry(
            timestamp="2026-11-24T00:00:00Z",
            campaign="audit-chain-test",
            round_id=1,
            slice_id="s-a",
            status="KEEP",
            seconds=0.5,
            commit_sha=sha1,
            after_sha256=after_sha1,
        ),
    )

    clean = audit_campaign_chain(repo, spec, ledger_path=ledger)
    assert clean["ok"] is True
    assert clean["learning_eligible"] is True
    assert clean["violations"] == []
    assert len(clean["replayed_slices"]) == 1

    # CLI check: crucible_gate.py campaign audit <spec.json> <ledger.tsv> --json
    spec_file = tmp_path / "campaign.json"
    spec_file.write_text(
        json.dumps(
            {
                "name": "audit-chain-test",
                "repo_root": str(repo),
                "slices": [
                    {
                        "id": "s-a",
                        "target_paths": ["a.py"],
                        "verify_cmd": f'"{sys.executable}" -c "import a; assert a.VAL == 2"',
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    cli = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "crucible_gate.py"), "campaign", "audit", str(spec_file), str(ledger), "--json"],
        cwd=repo,
        capture_output=True,
        text=True,
        check=False,
    )
    assert cli.returncode == 0, cli.stderr
    cli_data = json.loads(cli.stdout)
    assert cli_data["ok"] is True
    assert cli_data["learning_eligible"] is True

    # Negative control: commit touching out-of-scope file b.py must fail audit
    (repo / "a.py").write_text("VAL = 2\n# ok\n", encoding="utf-8")
    (repo / "b.py").write_text("OTHER = 999\n", encoding="utf-8")
    subprocess.run(["git", "add", "a.py", "b.py"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-m", "out of scope"], cwd=repo, check=True, capture_output=True)
    sha2 = subprocess.run(["git", "rev-parse", "HEAD"], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()

    bad_ledger = tmp_path / "bad_results.tsv"
    append_ratchet_ledger(
        bad_ledger,
        RatchetEntry(
            timestamp="2026-11-24T00:01:00Z",
            campaign="audit-chain-test",
            round_id=2,
            slice_id="s-a",
            status="KEEP",
            seconds=0.5,
            commit_sha=sha2,
            after_sha256="0" * 64,
        ),
    )
    failed = audit_campaign_chain(repo, spec, ledger_path=bad_ledger)
    assert failed["ok"] is False
    assert failed["learning_eligible"] is False
    assert any("OUT_OF_SCOPE_FILE" in v for v in failed["violations"])
    assert any("SHA_MISMATCH" in v for v in failed["violations"])
