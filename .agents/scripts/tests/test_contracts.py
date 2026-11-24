"""Tests for Spoke Design-by-Contract (requires, ensures, and unchanged_roots frame invariants)."""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from crucible.contracts import (
    ContractViolationError,
    SpokeContract,
    snapshot_roots,
    verify_spoke_call,
)


def test_valid_spoke_call_passes_all_invariants(tmp_path: Path) -> None:
    protected_dir = tmp_path / "protected"
    protected_dir.mkdir()
    truth_file = protected_dir / "GROUND_TRUTH.md"
    truth_file.write_text("# Truth\n", encoding="utf-8")

    working_dir = tmp_path / "working"
    working_dir.mkdir()

    contract = SpokeContract(
        spoke="writers-room",
        action="deliver",
        requires=[
            lambda p: isinstance(p, dict) and bool(p.get("doc_id")),
            lambda p: (p.get("revision", 0) >= 1, "revision must be >= 1"),
        ],
        ensures=[
            lambda res: isinstance(res, dict) and res.get("status") == "delivered",
            lambda req, res: res.get("doc_id") == req["doc_id"],
        ],
        unchanged_roots=("protected",),
    )

    def spoke_deliver(payload: dict[str, Any]) -> dict[str, Any]:
        out = working_dir / f"{payload['doc_id']}.txt"
        out.write_text("draft content\n", encoding="utf-8")
        return {"status": "delivered", "doc_id": payload["doc_id"], "path": str(out)}

    before = snapshot_roots(tmp_path, ("protected",))
    result = verify_spoke_call(
        contract,
        {"doc_id": "brief-01", "revision": 2},
        spoke_deliver,
        root=tmp_path,
    )
    after = snapshot_roots(tmp_path, ("protected",))

    assert result["status"] == "delivered"
    assert result["doc_id"] == "brief-01"
    assert (working_dir / "brief-01.txt").read_text(encoding="utf-8") == "draft content\n"
    assert before == after


def test_requires_violation_blocks_spoke_execution(tmp_path: Path) -> None:
    calls: list[dict[str, Any]] = []
    contract = SpokeContract(
        spoke="story-lane",
        action="prepare",
        requires=[
            lambda p: (isinstance(p.get("start"), (int, float)) and p["start"] >= 0, "invalid start"),
        ],
        ensures=[lambda res: res.get("ok") is True],
    )

    def spoke_prepare(payload: dict[str, Any]) -> dict[str, Any]:
        calls.append(payload)
        return {"ok": True}

    with pytest.raises(ContractViolationError) as exc_info:
        verify_spoke_call(contract, {"start": -1}, spoke_prepare, root=tmp_path)

    err = exc_info.value
    assert err.phase == "requires"
    assert err.spoke == "story-lane"
    assert err.action == "prepare"
    assert "invalid start" in err.detail
    assert calls == []

    # Predicate raising KeyError on missing key also surfaces as requires ContractViolationError
    key_contract = SpokeContract(
        spoke="story-lane",
        action="prepare",
        requires=[lambda p: p["missing_key"] > 0],
    )
    with pytest.raises(ContractViolationError) as key_exc:
        verify_spoke_call(key_contract, {}, spoke_prepare)
    assert key_exc.value.phase == "requires"
    assert "KeyError" in key_exc.value.detail
    assert calls == []


def test_ensures_violation_raises_contract_error() -> None:
    contract = SpokeContract(
        spoke="crucible-observatory",
        action="recognize",
        requires=[lambda p: bool(p.get("target"))],
        ensures=[
            lambda res: res.get("status") == "ok",
            lambda req, res: (res.get("target") == req["target"], "target mismatch"),
        ],
    )

    with pytest.raises(ContractViolationError) as status_exc:
        verify_spoke_call(
            contract,
            {"target": "repo-a"},
            lambda p: {"status": "failed", "target": p["target"]},
        )
    assert status_exc.value.phase == "ensures"
    assert status_exc.value.spoke == "crucible-observatory"
    assert status_exc.value.action == "recognize"

    with pytest.raises(ContractViolationError) as mismatch_exc:
        verify_spoke_call(
            contract,
            {"target": "repo-a"},
            lambda p: {"status": "ok", "target": "repo-b"},
        )
    assert mismatch_exc.value.phase == "ensures"
    assert "target mismatch" in mismatch_exc.value.detail


def test_frame_violation_detects_modified_added_and_deleted_roots(tmp_path: Path) -> None:
    protected_dir = tmp_path / "Calgary Public Library"
    protected_dir.mkdir()
    keep = protected_dir / "keep.md"
    keep.write_text("original\n", encoding="utf-8")

    contract = SpokeContract(
        spoke="writers-room",
        action="deliver",
        requires=[lambda p: True],
        ensures=[lambda res: res.get("ok") is True],
        unchanged_roots=("Calgary Public Library", "absent_guard.txt"),
    )

    # 1. Modifying an existing file inside unchanged_roots fails frame check
    def mutate_existing(_payload: Any) -> dict[str, Any]:
        keep.write_text("tampered\n", encoding="utf-8")
        return {"ok": True}

    with pytest.raises(ContractViolationError) as mod_exc:
        verify_spoke_call(contract, {}, mutate_existing, root=tmp_path)
    assert mod_exc.value.phase == "frame"
    assert "modified Calgary Public Library/keep.md" in mod_exc.value.detail

    # Restore clean state
    keep.write_text("original\n", encoding="utf-8")

    # 2. Adding a new file inside unchanged_roots fails frame check
    def add_file(_payload: Any) -> dict[str, Any]:
        (protected_dir / "sneaky.md").write_text("new\n", encoding="utf-8")
        return {"ok": True}

    with pytest.raises(ContractViolationError) as add_exc:
        verify_spoke_call(contract, {}, add_file, root=tmp_path)
    assert add_exc.value.phase == "frame"
    assert "added Calgary Public Library/sneaky.md" in add_exc.value.detail
    (protected_dir / "sneaky.md").unlink()

    # 3. Deleting a file inside unchanged_roots fails frame check
    def delete_file(_payload: Any) -> dict[str, Any]:
        keep.unlink()
        return {"ok": True}

    with pytest.raises(ContractViolationError) as del_exc:
        verify_spoke_call(contract, {}, delete_file, root=tmp_path)
    assert del_exc.value.phase == "frame"
    assert "removed Calgary Public Library/keep.md" in del_exc.value.detail
    keep.write_text("original\n", encoding="utf-8")

    # 4. Creating a previously absent unchanged root fails frame check
    def create_absent(_payload: Any) -> dict[str, Any]:
        (tmp_path / "absent_guard.txt").write_text("created\n", encoding="utf-8")
        return {"ok": True}

    with pytest.raises(ContractViolationError) as abs_exc:
        verify_spoke_call(contract, {}, create_absent, root=tmp_path)
    assert abs_exc.value.phase == "frame"
    assert "modified absent_guard.txt" in abs_exc.value.detail

    # 5. Missing root when unchanged_roots is non-empty fails closed
    with pytest.raises(ContractViolationError) as no_root_exc:
        verify_spoke_call(contract, {}, lambda _p: {"ok": True}, root=None)
    assert no_root_exc.value.phase == "frame"


def test_snapshot_roots_rejects_path_escape(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="escapes root"):
        snapshot_roots(tmp_path, ("../outside",))
