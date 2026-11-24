"""K-TEST-01 + 100-case randomized property tests for Campaign IR Compiler Front-End."""

from __future__ import annotations

import random
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import concurrent.futures
import hashlib
import json

from crucible.campaign_ir import (
    WORKER_RESULT_SCHEMA,
    CacheConflictError,
    CampaignCheckpoint,
    CampaignCompileError,
    CampaignSpec,
    ErrorCircuitBreaker,
    LoopStateMachine,
    PlannedSlice,
    RatchetEntry,
    SliceNode,
    StateTransitionError,
    append_ratchet_ledger,
    build_slice_worker_prompt,
    compile_campaign,
    execute_slice_transaction,
    compute_slice_input_sha256,
    file_sha256,
    hash_error_output,
    load_campaign_checkpoint,
    load_campaign_spec,
    load_ratchet_ledger,
    load_receipt_cache,
    merge_receipt_cache,
    optimize_campaign,
    save_receipt_cache,
    save_campaign_checkpoint,
    save_receipt_cache_cas,
)


def test_compile_rejects_path_escape_and_missing_depends(tmp_path: Path) -> None:
    spec = CampaignSpec(
        name="bad-campaign",
        repo_root=str(tmp_path),
        slices=[
            SliceNode(id="s1", target_paths=["../outside.py"], depends_on=["missing"]),
        ],
    )
    with pytest.raises(CampaignCompileError) as exc_info:
        compile_campaign(spec)

    joined = " | ".join(exc_info.value.errors)
    assert "escapes repo_root" in joined
    assert "missing slice 'missing'" in joined


def test_compile_rejects_allowed_roots_escape(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    allowed_dir = tmp_path / "allowed"
    allowed_dir.mkdir()
    monkeypatch.setenv("CRUCIBLE_ALLOWED_ROOTS", str(allowed_dir))

    spec = CampaignSpec(
        name="root-escape",
        repo_root=str(tmp_path),
        slices=[SliceNode(id="s1", target_paths=["other/file.py"])],
    )
    with pytest.raises(CampaignCompileError) as exc_info:
        compile_campaign(spec)
    assert any("escapes allowed roots" in err for err in exc_info.value.errors)


def test_compile_rejects_dependency_cycle(tmp_path: Path) -> None:
    spec = CampaignSpec(
        name="cycle-campaign",
        repo_root=str(tmp_path),
        slices=[
            SliceNode(id="a", target_paths=["a.py"], depends_on=["b"]),
            SliceNode(id="b", target_paths=["b.py"], depends_on=["a"]),
        ],
    )
    with pytest.raises(CampaignCompileError) as exc_info:
        compile_campaign(spec)
    assert any("dependency cycle" in err for err in exc_info.value.errors)


def test_incremental_optimizer_skips_cached_and_propagates_dirty(tmp_path: Path) -> None:
    f1 = tmp_path / "a.py"
    f2 = tmp_path / "b.py"
    f3 = tmp_path / "c.py"
    f1.write_text("x = 1\n", encoding="utf-8")
    f2.write_text("y = 2\n", encoding="utf-8")
    f3.write_text("z = 3\n", encoding="utf-8")

    spec = CampaignSpec(
        name="inc-campaign",
        repo_root=str(tmp_path),
        slices=[
            SliceNode(id="s1", target_paths=["a.py"], verify_cmd="pytest -q"),
            SliceNode(id="s2", target_paths=["b.py"], depends_on=["s1"], verify_cmd="pytest -q"),
            SliceNode(id="s3", target_paths=["c.py"], verify_cmd="pytest -q"),
        ],
    )

    cache_path = tmp_path / ".cache" / "receipts.json"
    initial = optimize_campaign(spec, cache_path)
    assert [s.node.id for s in initial.active_slices] == ["s1", "s3", "s2"]
    assert initial.skipped_slices == []

    receipts = {s.node.id: s.computed_sha256 for s in initial.ordered_slices}
    save_receipt_cache(cache_path, receipts)
    assert load_receipt_cache(cache_path) == receipts

    second = optimize_campaign(spec, cache_path)
    assert second.active_slices == []
    assert [s.node.id for s in second.skipped_slices] == ["s1", "s3", "s2"]

    # Mutate s1 -> s1 and downstream s2 must run, independent s3 remains SKIP_CACHED
    f1.write_text("x = 99\n", encoding="utf-8")
    third = optimize_campaign(spec, cache_path)
    assert [s.node.id for s in third.active_slices] == ["s1", "s2"]
    assert [s.node.id for s in third.skipped_slices] == ["s3"]


def test_error_hash_circuit_breaker_trips_on_identical_and_resets() -> None:
    breaker = ErrorCircuitBreaker(max_consecutive_failures=3)

    r1 = breaker.record_failure("AssertionError: expected 1 == 2   \n")
    assert not r1.tripped
    assert r1.consecutive_failures == 1

    # Identical normalized error hash trips immediately on 2nd consecutive failure
    r2 = breaker.record_failure("AssertionError: expected 1 == 2")
    assert r2.tripped
    assert r2.reason == "IDENTICAL_ERROR_HASH"
    assert r2.error_sha256 == r1.error_sha256

    ok = breaker.record_success()
    assert not ok.tripped
    assert ok.consecutive_failures == 0

    # Three distinct failures trip 3-strike governor
    assert not breaker.record_failure("err-1").tripped
    assert not breaker.record_failure("err-2").tripped
    r3 = breaker.record_failure("err-3")
    assert r3.tripped
    assert r3.reason == "MAX_CONSECUTIVE_FAILURES"


def test_property_100_random_dags_and_cache_invariants(tmp_path: Path) -> None:
    rng = random.Random(20261123)
    for case in range(100):
        case_dir = tmp_path / f"case_{case}"
        case_dir.mkdir()
        n = rng.randint(2, 7)
        nodes: list[SliceNode] = []
        for idx in range(n):
            fname = f"mod_{idx}.py"
            (case_dir / fname).write_text(f"VAL = {rng.randint(0, 1000)}\n", encoding="utf-8")
            deps = [f"s{j}" for j in range(idx) if rng.random() < 0.4]
            nodes.append(SliceNode(id=f"s{idx}", target_paths=[fname], depends_on=deps))

        # Shuffle input order to verify topological sort restores valid dependency order
        shuffled = list(nodes)
        rng.shuffle(shuffled)
        spec = CampaignSpec(name=f"prop-{case}", repo_root=str(case_dir), slices=shuffled)
        compiled = optimize_campaign(spec, {})

        pos = {ps.node.id: i for i, ps in enumerate(compiled.ordered_slices)}
        for ps in compiled.ordered_slices:
            for dep in ps.node.depends_on:
                assert pos[dep] < pos[ps.node.id]

        # Full cache -> 0 active slices
        full_cache = {ps.node.id: ps.computed_sha256 for ps in compiled.ordered_slices}
        cached_run = optimize_campaign(spec, full_cache)
        assert cached_run.active_slices == []
        assert len(cached_run.skipped_slices) == n

        # Determinism check for compute_slice_input_sha256 and hash_error_output
        sample = compiled.ordered_slices[0].node
        assert compute_slice_input_sha256(sample, case_dir) == compiled.ordered_slices[0].computed_sha256
        err_msg = f"fail-{case}-{rng.randint(1, 99)}"
        assert hash_error_output(err_msg + "  \n") == hash_error_output(err_msg)


def test_hash_error_output_strips_volatile_tokens() -> None:
    e1 = "FAIL at 2026-11-24T00:01:02Z obj=0x7ff123ab pytest-21 in 1.42s"
    e2 = "FAIL at 2026-11-24T00:05:59Z obj=0xdeadbeef pytest-99 in 3.87s"
    assert hash_error_output(e1) == hash_error_output(e2)


def test_ast_import_change_invalidates_slice_hash_and_waves(tmp_path: Path) -> None:
    helper = tmp_path / "helper.py"
    main_a = tmp_path / "main_a.py"
    main_b = tmp_path / "main_b.py"
    helper.write_text("X = 1\n", encoding="utf-8")
    main_a.write_text("import helper\nY = helper.X\n", encoding="utf-8")
    main_b.write_text("Z = 2\n", encoding="utf-8")

    spec = CampaignSpec(
        name="ast-wave",
        repo_root=str(tmp_path),
        slices=[
            SliceNode(id="a", target_paths=["main_a.py"]),
            SliceNode(id="b", target_paths=["main_b.py"]),
            SliceNode(id="c", target_paths=["main_b.py"], depends_on=["a", "b"]),
        ],
    )
    first = optimize_campaign(spec, {})
    waves = [[s.node.id for s in w] for w in first.execution_waves]
    assert waves == [["a", "b"], ["c"]]

    cache = {s.node.id: s.computed_sha256 for s in first.ordered_slices}
    helper.write_text("X = 999\n", encoding="utf-8")
    second = optimize_campaign(spec, cache)
    assert [s.node.id for s in second.active_slices] == ["a", "c"]
    assert [s.node.id for s in second.skipped_slices] == ["b"]

def test_cas_save_detects_stale_sha_and_missing_file(tmp_path: Path) -> None:
    """Fails if optimistic CAS overwrites stale disk state or crashes on missing files."""
    cache_path = tmp_path / "cache" / "receipts.json"
    assert file_sha256(cache_path) is None

    # Reject: expected non-None sha256 when file does not exist (missing treated as None)
    with pytest.raises(CacheConflictError):
        save_receipt_cache_cas(cache_path, {"s1": "h1"}, expected_sha256="deadbeef")
    assert not cache_path.exists()

    # Allow: initial write and valid CAS compare-and-swap
    sha1 = save_receipt_cache_cas(cache_path, {"s1": "h1"})
    assert sha1 == file_sha256(cache_path)
    sha2 = save_receipt_cache_cas(cache_path, {"s1": "h2"}, expected_sha256=sha1)
    assert sha2 != sha1
    assert sha2 == file_sha256(cache_path)

    # Reject: stale expected_sha256 must raise CacheConflictError without mutating disk
    with pytest.raises(CacheConflictError):
        save_receipt_cache_cas(cache_path, {"s1": "stale"}, expected_sha256=sha1)
    assert load_receipt_cache(cache_path) == {"s1": "h2"}
    assert file_sha256(cache_path) == sha2


def test_merge_receipt_cache_preserves_concurrent_keys_and_retries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fails if concurrent merge_receipt_cache workers drop keys or fail to retry CAS conflicts."""
    cache_path = tmp_path / "receipts.json"

    with pytest.raises(ValueError):
        merge_receipt_cache(cache_path, {"k": "v"}, max_retries=-1)

    # Real concurrent workers racing from missing file -> existing file updates
    def worker(idx: int) -> tuple[dict[str, str], str]:
        return merge_receipt_cache(cache_path, {f"slice_{idx}": f"sha_{idx}"}, max_retries=16)

    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(worker, range(16)))

    final_disk = load_receipt_cache(cache_path)
    assert final_disk == {f"slice_{i}": f"sha_{i}" for i in range(16)}
    assert all(isinstance(sha, str) and len(sha) == 64 for _, sha in results)

    # Deterministic CAS retry & exhaustion test
    import crucible.campaign_ir as cir

    real_cas = cir.save_receipt_cache_cas
    calls = {"n": 0}

    def conflict_once(path: Path | str, data: dict[str, str], expected_sha256: str | None = None) -> str:
        calls["n"] += 1
        if calls["n"] == 1:
            raise CacheConflictError("simulated concurrent write")
        return real_cas(path, data, expected_sha256=expected_sha256)

    monkeypatch.setattr(cir, "save_receipt_cache_cas", conflict_once)
    merged, new_sha = merge_receipt_cache(cache_path, {"extra": "ok"}, max_retries=1)
    assert calls["n"] == 2
    assert merged["extra"] == "ok"
    assert new_sha == file_sha256(cache_path)

    def always_conflict(path: Path | str, data: dict[str, str], expected_sha256: str | None = None) -> str:
        raise CacheConflictError("permanent conflict")

    monkeypatch.setattr(cir, "save_receipt_cache_cas", always_conflict)
    with pytest.raises(CacheConflictError):
        merge_receipt_cache(cache_path, {"never": "saved"}, max_retries=2)


def test_loop_state_machine_enforces_order_and_rejects_stale_sha() -> None:
    """Fails if LoopStateMachine permits out-of-order commits or stale SHA verification."""
    fsm = LoopStateMachine()
    assert fsm.state == "PLAN"

    # Negative: illegal transitions from PLAN
    with pytest.raises(StateTransitionError):
        fsm.verify(0, "abc")
    with pytest.raises(StateTransitionError):
        fsm.commit("deadbeef")
    with pytest.raises(StateTransitionError):
        fsm.cache()
    with pytest.raises(StateTransitionError):
        fsm.stage("")
    with pytest.raises(StateTransitionError):
        fsm.plan("", "s1")

    fsm.plan("camp-v4", "wave1")
    assert fsm.stage("sha-after-1") == "STAGE"

    # Negative: cannot re-plan, skip to commit, or verify stale SHA while in STAGE
    with pytest.raises(StateTransitionError):
        fsm.plan("camp-v4", "s2")
    with pytest.raises(StateTransitionError):
        fsm.commit("deadbeef")
    with pytest.raises(StateTransitionError):
        fsm.verify(0, "sha-stale-other")
    assert fsm.state == "STAGE"

    # Failure path: exit_code != 0 moves to FAILED, records canonical error hash, requires reset()
    ok = fsm.verify(1, "sha-after-1", "AssertionError at 2026-11-24T01:02:03Z")
    assert not ok
    assert fsm.state == "FAILED"
    assert fsm.last_error_sha256 == hash_error_output("AssertionError at 2026-11-24T09:00:00Z")
    with pytest.raises(StateTransitionError):
        fsm.commit("deadbeef")
    with pytest.raises(StateTransitionError):
        fsm.stage("sha-after-2")

    assert fsm.reset() == "PLAN"

    # Positive: full PLAN -> STAGE -> VERIFY -> COMMIT -> CACHE -> RESET round-trip
    fsm.plan("camp-v4", "wave1")
    assert fsm.stage("sha-after-2") == "STAGE"
    assert fsm.verify(0, "sha-after-2") is True
    assert fsm.state == "VERIFY"
    with pytest.raises(StateTransitionError):
        fsm.cache()
    with pytest.raises(StateTransitionError):
        fsm.commit("")
    assert fsm.commit("c0mm1t") == "COMMIT"
    assert fsm.cache() == "CACHE"
    with pytest.raises(StateTransitionError):
        fsm.commit("again")
    assert fsm.reset() == "PLAN"


def test_ratchet_ledger_roundtrip_and_validation(tmp_path: Path) -> None:
    """Fails if TSV ratchet ledger drops empty trailing columns, corrupts header, or accepts invalid statuses."""
    ledger = tmp_path / "logs" / "ratchet.tsv"
    assert load_ratchet_ledger(ledger) == []

    # Negative: invalid status, negative round/seconds, tab injection, corrupt header
    with pytest.raises(ValueError):
        RatchetEntry("2026-11-24T00:00:00Z", "c", 1, "s1", "INVALID", 1.0)
    with pytest.raises(ValueError):
        RatchetEntry("2026-11-24T00:00:00Z", "c", -1, "s1", "KEEP", 1.0)
    with pytest.raises(ValueError):
        RatchetEntry("2026-11-24T00:00:00Z", "c\tbad", 1, "s1", "KEEP", 1.0)

    bad_tsv = tmp_path / "bad.tsv"
    bad_tsv.write_text("wrong\theader\n", encoding="utf-8")
    with pytest.raises(ValueError):
        load_ratchet_ledger(bad_tsv)

    entries = [
        RatchetEntry("2026-11-24T00:01:00Z", "v4", 1, "s1", "KEEP", 1.2345, "abc123", "def456", ""),
        RatchetEntry("2026-11-24T00:02:00Z", "v4", 2, "s2", "REVERT", 0.5, "", "ghi789", "err111"),
        RatchetEntry("2026-11-24T00:03:00Z", "v4", 3, "s3", "SKIP_CACHED", 0.0, "", "", ""),
        RatchetEntry("2026-11-24T00:04:00Z", "v4", 4, "s4", "TRIPPED", 2.0, "", "jkl000", "err222"),
    ]
    for e in entries:
        append_ratchet_ledger(ledger, e)

    lines = ledger.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 5
    assert lines[0] == "timestamp\tcampaign\tround_id\tslice_id\tstatus\tseconds\tcommit_sha\tafter_sha256\terror_sha256"
    assert load_ratchet_ledger(ledger) == entries


def test_campaign_spec_loader_worker_schema_and_minimal_prompt(tmp_path: Path) -> None:
    """Fails if spec loader accepts malformed schemas or worker prompt leaks extra slice/file content."""
    # Negative: malformed specs raise CampaignCompileError
    with pytest.raises(CampaignCompileError):
        load_campaign_spec({"name": "bad", "repo_root": str(tmp_path), "slices": "not-a-list"})
    with pytest.raises(CampaignCompileError):
        load_campaign_spec({"name": "bad", "repo_root": str(tmp_path), "slices": [{"id": "s1"}], "max_rounds": True})

    secret_file = tmp_path / "mod.py"
    secret_file.write_text("SECRET_TOKEN = 'do_not_leak_this_in_prompt'\n", encoding="utf-8")

    spec_dict = {
        "name": "v4-camp",
        "repo_root": str(tmp_path),
        "max_rounds": 6,
        "slices": [
            {"id": "s0", "target_paths": ["mod.py"], "verify_cmd": "pytest -q"},
            {"id": "s1", "target_paths": ["mod.py"], "depends_on": ["s0"], "verify_cmd": "pytest -k s1"},
        ],
    }
    spec_json_path = tmp_path / "campaign.json"
    spec_json_path.write_text(json.dumps(spec_dict), encoding="utf-8")

    from_dict = load_campaign_spec(spec_dict)
    from_str = load_campaign_spec(json.dumps(spec_dict))
    from_path = load_campaign_spec(spec_json_path)
    from_path_str = load_campaign_spec(str(spec_json_path))
    assert from_dict == from_str == from_path == from_path_str
    assert from_dict.max_rounds == 6
    assert [s.id for s in from_dict.slices] == ["s0", "s1"]

    assert WORKER_RESULT_SCHEMA["type"] == "object"
    assert set(WORKER_RESULT_SCHEMA["required"]) == {
        "slice_id",
        "commit_sha",
        "after_sha256",
        "passed",
        "error_output",
    }
    assert WORKER_RESULT_SCHEMA["properties"]["passed"]["type"] == "boolean"

    compiled = optimize_campaign(from_dict, {})
    target_ps = next(ps for ps in compiled.ordered_slices if ps.node.id == "s1")
    prompt = build_slice_worker_prompt(target_ps, tmp_path)
    assert "s1" in prompt
    assert "mod.py" in prompt
    assert "s0" in prompt
    assert "pytest -k s1" in prompt
    assert target_ps.computed_sha256 in prompt
    assert "SECRET_TOKEN" not in prompt
    assert "v4-camp" not in prompt


def test_property_100_random_fsm_cas_and_ledger_invariants(tmp_path: Path) -> None:
    """Fails if randomized CAS merges, FSM state gates, or TSV round-trips lose invariants."""
    rng = random.Random(20261124)
    statuses = ["KEEP", "REVERT", "SKIP_CACHED", "TRIPPED"]

    for case in range(100):
        case_dir = tmp_path / f"w1_case_{case}"
        case_dir.mkdir()
        cache_path = case_dir / "receipts.json"
        ledger_path = case_dir / "ratchet.tsv"

        # 1. Randomized CAS & merge-on-write preservation
        expected_map: dict[str, str] = {}
        last_sha: str | None = None
        for step in range(rng.randint(2, 5)):
            key = f"s{step}"
            val = f"{case:03d}-{rng.randint(1000, 9999)}"
            merged, new_sha = merge_receipt_cache(cache_path, {key: val})
            expected_map[key] = val
            assert merged == expected_map
            if last_sha is not None and new_sha != last_sha:
                with pytest.raises(CacheConflictError):
                    save_receipt_cache_cas(cache_path, {"bad": "x"}, expected_sha256=last_sha)
            last_sha = new_sha
        assert load_receipt_cache(cache_path) == expected_map

        # 2. Randomized FSM valid + illegal transition fuzzing
        fsm = LoopStateMachine()
        after_sha = f"after-{case}-{rng.randint(1, 999)}"
        fsm.plan(f"camp-{case}", f"slice-{case}")
        fsm.stage(after_sha)
        if rng.random() < 0.3:
            with pytest.raises(StateTransitionError):
                fsm.verify(0, after_sha + "-stale")
            assert fsm.state == "STAGE"
        if rng.random() < 0.5:
            assert fsm.verify(0, after_sha) is True
            fsm.commit(f"commit-{case}")
            fsm.cache()
            assert fsm.state == "CACHE"
        else:
            assert fsm.verify(2, after_sha, f"err-{case}") is False
            assert fsm.state == "FAILED"
            with pytest.raises(StateTransitionError):
                fsm.commit(f"commit-{case}")
        fsm.reset()
        assert fsm.state == "PLAN"

        # 3. Randomized RatchetEntry TSV round-trip
        entry = RatchetEntry(
            timestamp=f"2026-11-24T00:00:{case % 60:02d}Z",
            campaign=f"camp-{case}",
            round_id=case,
            slice_id=f"s{case % 4}",
            status=rng.choice(statuses),
            seconds=round(rng.uniform(0.0, 25.0), 4),
            commit_sha="" if rng.random() < 0.4 else f"sha{case}",
            after_sha256=after_sha,
            error_sha256="" if rng.random() < 0.5 else f"err{case}",
        )
        append_ratchet_ledger(ledger_path, entry)
        assert load_ratchet_ledger(ledger_path) == [entry]


GATE_SCRIPT = SCRIPTS_DIR / "crucible_gate.py"


def _run_gate_cli(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GATE_SCRIPT), "--root", str(repo), *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def test_cli_campaign_compile_rejects_errors_and_prints_order(tmp_path: Path) -> None:
    """Fails if crucible_gate.py campaign compile exits 0 on invalid specs or drops topological order."""
    # Negative: missing action/arg returns usage exit code
    bad_usage = _run_gate_cli(tmp_path, "campaign")
    assert bad_usage.returncode != 0

    # Negative: path escape + dependency cycle exits 1 and emits errors in text and JSON
    bad_spec = tmp_path / "bad_campaign.json"
    bad_spec.write_text(
        json.dumps(
            {
                "name": "bad-cli",
                "repo_root": str(tmp_path),
                "slices": [
                    {"id": "a", "target_paths": ["../escape.py"], "depends_on": ["b"]},
                    {"id": "b", "target_paths": ["b.py"], "depends_on": ["a"]},
                ],
            }
        ),
        encoding="utf-8",
    )
    bad_txt = _run_gate_cli(tmp_path, "campaign", "compile", "bad_campaign.json")
    assert bad_txt.returncode == 1, bad_txt.stdout + bad_txt.stderr
    assert "escapes repo_root" in (bad_txt.stdout + bad_txt.stderr)
    assert "dependency cycle" in (bad_txt.stdout + bad_txt.stderr)

    bad_json = _run_gate_cli(tmp_path, "campaign", "compile", "bad_campaign.json", "--json")
    assert bad_json.returncode == 1, bad_json.stdout + bad_json.stderr
    bad_payload = json.loads(bad_json.stdout)
    assert bad_payload["ok"] is False
    assert len(bad_payload["errors"]) >= 2

    # Negative: missing spec file exits 1
    missing_proc = _run_gate_cli(tmp_path, "campaign", "compile", "does_not_exist.json")
    assert missing_proc.returncode == 1

    # Positive: valid spec listed in reverse dependency order compiles into topological order
    (tmp_path / "a.py").write_text("A = 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("B = 2\n", encoding="utf-8")
    good_spec = tmp_path / "good_campaign.json"
    good_spec.write_text(
        json.dumps(
            {
                "name": "good-cli",
                "repo_root": str(tmp_path),
                "slices": [
                    {"id": "s2", "target_paths": ["b.py"], "depends_on": ["s1"], "verify_cmd": "pytest -q"},
                    {"id": "s1", "target_paths": ["a.py"], "verify_cmd": "pytest -q"},
                ],
            }
        ),
        encoding="utf-8",
    )
    ok_txt = _run_gate_cli(tmp_path, "campaign", "compile", "good_campaign.json")
    assert ok_txt.returncode == 0, ok_txt.stdout + ok_txt.stderr
    assert ok_txt.stdout.index("s1") < ok_txt.stdout.index("s2")

    ok_json = _run_gate_cli(tmp_path, "campaign", "compile", "good_campaign.json", "--json")
    assert ok_json.returncode == 0, ok_json.stdout + ok_json.stderr
    ok_payload = json.loads(ok_json.stdout)
    assert ok_payload["ok"] is True
    assert [s["id"] for s in ok_payload["ordered_slices"]] == ["s1", "s2"]


def test_cli_campaign_plan_waves_and_cache_skip(tmp_path: Path) -> None:
    """Fails if crucible_gate.py campaign plan misclassifies RUN vs SKIP_CACHED or drops waves."""
    (tmp_path / "a.py").write_text("A = 1\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("B = 2\n", encoding="utf-8")
    (tmp_path / "c.py").write_text("C = 3\n", encoding="utf-8")

    spec_path = tmp_path / "plan_campaign.json"
    spec_path.write_text(
        json.dumps(
            {
                "name": "plan-cli",
                "repo_root": str(tmp_path),
                "slices": [
                    {"id": "s1", "target_paths": ["a.py"], "verify_cmd": "pytest -k s1"},
                    {"id": "s2", "target_paths": ["b.py"], "verify_cmd": "pytest -k s2"},
                    {"id": "s3", "target_paths": ["c.py"], "depends_on": ["s1"], "verify_cmd": "pytest -k s3"},
                ],
            }
        ),
        encoding="utf-8",
    )

    # Negative: invalid spec file fails plan with exit code 1
    bad_spec = tmp_path / "bad_plan.json"
    bad_spec.write_text(
        json.dumps({"name": "bad", "repo_root": str(tmp_path), "slices": [{"id": "x", "target_paths": ["../x.py"]}]}),
        encoding="utf-8",
    )
    assert _run_gate_cli(tmp_path, "campaign", "plan", "bad_plan.json").returncode == 1

    # Positive (cold cache): 2 waves [["s1", "s2"], ["s3"]], all RUN
    cold_proc = _run_gate_cli(tmp_path, "campaign", "plan", "plan_campaign.json", "--json")
    assert cold_proc.returncode == 0, cold_proc.stdout + cold_proc.stderr
    cold = json.loads(cold_proc.stdout)
    assert [[s["id"] for s in wave] for wave in cold["execution_waves"]] == [["s1", "s2"], ["s3"]]
    assert [s["id"] for s in cold["active_slices"]] == ["s1", "s2", "s3"]
    assert cold["skipped_slices"] == []

    # Populate cache for all 3 slices, then dirty s1 -> s1 and downstream s3 RUN, s2 SKIP_CACHED
    cache_path = tmp_path / "receipts.json"
    receipts = {s["id"]: s["computed_sha256"] for s in cold["active_slices"]}
    save_receipt_cache_cas(cache_path, receipts)
    (tmp_path / "a.py").write_text("A = 999\n", encoding="utf-8")

    warm_json = _run_gate_cli(tmp_path, "campaign", "plan", "plan_campaign.json", "--cache", "receipts.json", "--json")
    assert warm_json.returncode == 0, warm_json.stdout + warm_json.stderr
    warm = json.loads(warm_json.stdout)
    assert [[s["id"] for s in wave] for wave in warm["execution_waves"]] == [["s1"], ["s3"]]
    assert [s["id"] for s in warm["active_slices"]] == ["s1", "s3"]
    assert [s["id"] for s in warm["skipped_slices"]] == ["s2"]

    warm_txt = _run_gate_cli(tmp_path, "campaign", "plan", "plan_campaign.json", "--cache", "receipts.json")
    assert warm_txt.returncode == 0, warm_txt.stdout + warm_txt.stderr
    assert "Wave 1" in warm_txt.stdout
    assert "Wave 2" in warm_txt.stdout
    assert "RUN" in warm_txt.stdout
    assert "SKIP_CACHED" in warm_txt.stdout


def test_cli_campaign_ledger_last_n_and_rejects_corrupt(tmp_path: Path) -> None:
    """Fails if crucible_gate.py campaign ledger ignores --last N or accepts corrupt TSV."""
    # Negative: corrupt TSV returns exit 1
    bad_tsv = tmp_path / "corrupt.tsv"
    bad_tsv.write_text("bad\theader\n", encoding="utf-8")
    bad_proc = _run_gate_cli(tmp_path, "campaign", "ledger", "corrupt.tsv")
    assert bad_proc.returncode == 1, bad_proc.stdout + bad_proc.stderr

    # Negative: negative --last fails cleanly
    assert _run_gate_cli(tmp_path, "campaign", "ledger", "missing.tsv", "--last", "-1").returncode != 0

    # Missing/empty ledger returns 0 with empty list
    empty_proc = _run_gate_cli(tmp_path, "campaign", "ledger", "missing.tsv", "--json")
    assert empty_proc.returncode == 0, empty_proc.stdout + empty_proc.stderr
    assert json.loads(empty_proc.stdout)["entries"] == []

    # Populate 5 entries, verify --last 2 and --last 0
    ledger_path = tmp_path / "ratchet.tsv"
    for r in range(1, 6):
        append_ratchet_ledger(
            ledger_path,
            RatchetEntry(
                timestamp=f"2026-11-24T00:0{r}:00Z",
                campaign="v4-cli",
                round_id=r,
                slice_id=f"s{r}",
                status="KEEP" if r < 5 else "SKIP_CACHED",
                seconds=0.25 * r,
                commit_sha=f"c{r:06d}" if r < 5 else "",
                after_sha256=f"a{r:06d}",
                error_sha256="",
            ),
        )

    tail_json = _run_gate_cli(tmp_path, "campaign", "ledger", "ratchet.tsv", "--last", "2", "--json")
    assert tail_json.returncode == 0, tail_json.stdout + tail_json.stderr
    tail_data = json.loads(tail_json.stdout)
    assert tail_data["total"] == 5
    assert [e["round_id"] for e in tail_data["entries"]] == [4, 5]

    zero_json = _run_gate_cli(tmp_path, "campaign", "ledger", "ratchet.tsv", "--last", "0", "--json")
    assert zero_json.returncode == 0, zero_json.stdout + zero_json.stderr
    assert json.loads(zero_json.stdout)["entries"] == []

    tail_txt = _run_gate_cli(tmp_path, "campaign", "ledger", "ratchet.tsv", "--last", "2")
    assert tail_txt.returncode == 0, tail_txt.stdout + tail_txt.stderr
    assert "s4" in tail_txt.stdout
    assert "s5" in tail_txt.stdout
    assert "s1" not in tail_txt.stdout


def test_campaign_telemetry_emit_and_summarize(tmp_path: Path) -> None:
    from crucible.campaign_ir import (
        CampaignTelemetryEvent,
        emit_telemetry_event,
        summarize_telemetry,
    )

    tpath = tmp_path / "telemetry.jsonl"
    # Negative control: missing file returns clean zeroed summary
    empty_summary = summarize_telemetry(tpath)
    assert empty_summary["total_events"] == 0
    assert empty_summary["slowest_slice"] is None

    emit_telemetry_event(
        tpath,
        CampaignTelemetryEvent(
            slice_id="s1", phase="VERIFY", status="KEEP", duration_ms=120.5, wave_idx=0, cache_hit=False
        ),
    )
    emit_telemetry_event(
        tpath,
        CampaignTelemetryEvent(
            slice_id="s2", phase="CACHE", status="SKIP_CACHED", duration_ms=1.2, wave_idx=0, cache_hit=True
        ),
    )
    emit_telemetry_event(
        tpath,
        CampaignTelemetryEvent(
            slice_id="s3",
            phase="VERIFY",
            status="REVERT",
            duration_ms=450.0,
            wave_idx=1,
            cache_hit=False,
            error_sha256="deadbeef",
        ),
    )

    summary = summarize_telemetry(tpath)
    assert summary["total_events"] == 3
    assert summary["total_ms"] == 571.7
    assert summary["cache_hit_rate"] == 0.3333
    assert summary["slowest_slice"] == "s3"
    assert summary["failure_counts_by_error_sha256"] == {"deadbeef": 1}

def test_execute_slice_transaction_rolls_back_on_verify_failure(tmp_path: Path) -> None:
    target = tmp_path / "mod.py"
    created = tmp_path / "created.py"
    original_bytes = b"VALUE = 1\n"
    target.write_bytes(original_bytes)

    node = SliceNode(id="s-fail", target_paths=["mod.py", "created.py"], verify_cmd="pytest")
    cp = CampaignCheckpoint(campaign_name="tx-rollback", max_rounds=4)

    def apply_bad() -> None:
        target.write_bytes(b"VALUE = 999\n")
        created.write_bytes(b"NEW = True\n")

    ok, detail = execute_slice_transaction(
        tmp_path,
        node,
        apply_bad,
        lambda: (False, "lint error"),
        cp,
    )
    assert ok is False
    assert detail == "ROLLED_BACK: lint error"
    assert target.read_bytes() == original_bytes
    assert not created.exists()
    assert cp.rounds_used == 1
    assert "s-fail" not in cp.completed_slices
    assert cp.failed_slices["s-fail"] == hashlib.sha256(b"lint error").hexdigest()[:16]

    def apply_crash() -> None:
        target.write_bytes(b"BROKEN\n")
        raise RuntimeError("boom")

    ok2, detail2 = execute_slice_transaction(
        tmp_path,
        node,
        apply_crash,
        lambda: (True, "unreachable"),
        cp,
    )
    assert ok2 is False
    assert detail2 == "ROLLED_BACK: RuntimeError: boom"
    assert target.read_bytes() == original_bytes
    assert cp.rounds_used == 2
    assert "s-fail" not in cp.completed_slices


def test_execute_slice_transaction_halts_at_max_rounds(tmp_path: Path) -> None:
    target = tmp_path / "bounded.py"
    original_bytes = b"LOCKED = True\n"
    target.write_bytes(original_bytes)

    node = SliceNode(id="s-bound", target_paths=["bounded.py"])
    cp = CampaignCheckpoint(campaign_name="bound-test", rounds_used=3, max_rounds=3)
    called = False

    def apply_should_not_run() -> None:
        nonlocal called
        called = True
        target.write_bytes(b"MUTATED\n")

    ok, detail = execute_slice_transaction(
        tmp_path,
        node,
        apply_should_not_run,
        lambda: (True, "ok"),
        cp,
    )
    assert ok is False
    assert "HALT_MAX_ROUNDS" in detail
    assert called is False
    assert target.read_bytes() == original_bytes
    assert cp.rounds_used == 3
    assert "s-bound" not in cp.completed_slices


def test_campaign_checkpoint_roundtrip_and_corrupt_json(tmp_path: Path) -> None:
    cp_path = tmp_path / "state" / "checkpoint.json"
    assert load_campaign_checkpoint(cp_path) is None

    target = tmp_path / "feature.py"
    target.write_bytes(b"X = 1\n")
    node = SliceNode(id="s1", target_paths=["feature.py"], verify_cmd="pytest")
    cp = CampaignCheckpoint(
        campaign_name="resume-campaign",
        failed_slices={"s1": "prior_err_hash"},
        rounds_used=0,
        max_rounds=5,
    )

    def apply_good() -> None:
        target.write_bytes(b"X = 2\n")

    ok, detail = execute_slice_transaction(
        tmp_path,
        node,
        apply_good,
        lambda: (True, "verified"),
        cp,
    )
    assert ok is True
    assert detail == "verified"
    assert cp.rounds_used == 1
    assert "s1" not in cp.failed_slices
    assert cp.completed_slices["s1"] == compute_slice_input_sha256(node, tmp_path)

    save_campaign_checkpoint(cp_path, cp)
    loaded = load_campaign_checkpoint(cp_path)
    assert loaded == cp

    cp_path.write_text("{corrupt json", encoding="utf-8")
    with pytest.raises(ValueError, match="Corrupt campaign checkpoint"):
        load_campaign_checkpoint(cp_path)


def test_withheld_holdout_parsed_hashed_and_hidden_from_worker_prompt(tmp_path: Path) -> None:
    target = tmp_path / "calc.py"
    target.write_text("VALUE = 1\n", encoding="utf-8")

    spec = load_campaign_spec(
        {
            "name": "holdout-campaign",
            "repo_root": str(tmp_path),
            "slices": [
                {
                    "id": "s-holdout",
                    "target_paths": ["calc.py"],
                    "verify_cmd": "pytest -q tests/test_public.py",
                    "withheld_verify_cmd": "python -c \"assert 'SECRET_EXPECTED_42'\"",
                    "withheld_failure_category": "encoding_damage",
                }
            ],
        }
    )
    node = spec.slices[0]
    assert node.withheld_verify_cmd == "python -c \"assert 'SECRET_EXPECTED_42'\""
    assert node.withheld_failure_category == "encoding_damage"

    base_node = SliceNode(
        id="s-holdout",
        target_paths=["calc.py"],
        verify_cmd="pytest -q tests/test_public.py",
    )
    assert compute_slice_input_sha256(node, tmp_path) != compute_slice_input_sha256(base_node, tmp_path)

    compiled = optimize_campaign(spec)
    prompt = build_slice_worker_prompt(compiled.active_slices[0], tmp_path)
    assert "SECRET_EXPECTED_42" not in prompt
    assert "withheld_verify_cmd" not in prompt
    assert "encoding_damage" not in prompt
    assert "verify_cmd: pytest -q tests/test_public.py" in prompt
