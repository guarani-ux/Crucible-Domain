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
    SliceNode,
    compile_campaign,
    load_campaign_spec,
    load_ratchet_ledger,
)
from crucible.replay_loop import (
    discover_gaps,
    execute_replay_verified_slice,
    replay_trace_file,
    run_autonomous_campaign,
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
