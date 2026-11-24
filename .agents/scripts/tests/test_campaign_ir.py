"""K-TEST-01 + 100-case randomized property tests for Campaign IR Compiler Front-End."""

from __future__ import annotations

import random
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from crucible.campaign_ir import (
    CampaignCompileError,
    CampaignSpec,
    ErrorCircuitBreaker,
    SliceNode,
    compile_campaign,
    compute_slice_input_sha256,
    hash_error_output,
    load_receipt_cache,
    optimize_campaign,
    save_receipt_cache,
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
