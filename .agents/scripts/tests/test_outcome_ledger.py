"""Tests for G4 recipient acceptance and G5 material improvement outcome ledger."""

from __future__ import annotations

import hashlib
import math
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from crucible.outcome_ledger import (
    MaterialImprovementEntry,
    RecipientAcceptanceReceipt,
    evaluate_g5_graduation,
    load_g5_ledger,
    record_g5_improvement,
    save_g5_ledger,
    validate_improvement_entry,
    validate_recipient_acceptance,
    verify_g5_ledger_file,
)


def _sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _make_improvement(
    idx: int,
    *,
    metric_name: str = "route_p95_ms",
    before_value: float = 120.0,
    after_value: float = 45.0,
    higher_is_better: bool = False,
    verify_cmd: str = "python -m pytest .agents/scripts/tests -q",
    evidence_sha256: str | None = None,
) -> MaterialImprovementEntry:
    digest = evidence_sha256 if evidence_sha256 is not None else _sha256_hex(f"ev-{idx}".encode("utf-8"))
    return MaterialImprovementEntry(
        id=f"IMP-{idx:02d}",
        weakness_id=f"CD-W{idx:02d}",
        metric_name=metric_name,
        before_value=before_value,
        after_value=after_value,
        higher_is_better=higher_is_better,
        verify_cmd=verify_cmd,
        evidence_sha256=digest,
    )


def test_recipient_acceptance_rejects_self_and_model_recipients(tmp_path: Path) -> None:
    deliverable = tmp_path / "brief.md"
    content = b"# Brief\nReady for review.\n"
    deliverable.write_bytes(content)
    digest = _sha256_hex(content)

    for bad_recipient in ("", "   ", "self", "Author", "agent", "model", "Assistant", "LLM"):
        receipt = RecipientAcceptanceReceipt(
            deliverable_path="brief.md",
            deliverable_sha256=digest,
            recipient=bad_recipient,
            intended_use="Stakeholder briefing",
            next_action_verified=True,
            accepted_at="2026-11-24T19:00:00Z",
            evidence_ref="notes/signoff.md",
        )
        ok, reason = validate_recipient_acceptance(tmp_path, receipt)
        assert ok is False
        assert "recipient" in reason.lower()


def test_recipient_acceptance_rejects_stale_sha_missing_file_and_unverified_fields(
    tmp_path: Path,
) -> None:
    deliverable = tmp_path / "deliverable.md"
    deliverable.write_bytes(b"v1 content\n")
    stale_sha = _sha256_hex(b"v0 content\n")

    stale_receipt = RecipientAcceptanceReceipt(
        deliverable_path="deliverable.md",
        deliverable_sha256=stale_sha,
        recipient="Jane Doe (Program Lead)",
        intended_use="Board decision",
        next_action_verified=True,
        accepted_at="2026-11-24T19:05:00Z",
        evidence_ref="email/re-board-decision",
    )
    ok_stale, reason_stale = validate_recipient_acceptance(tmp_path, stale_receipt)
    assert ok_stale is False
    assert "mismatch" in reason_stale.lower()

    live_sha = _sha256_hex(deliverable.read_bytes())

    unverified_receipt = RecipientAcceptanceReceipt(
        deliverable_path="deliverable.md",
        deliverable_sha256=live_sha,
        recipient="Jane Doe (Program Lead)",
        intended_use="Board decision",
        next_action_verified=False,
        accepted_at="2026-11-24T19:05:00Z",
        evidence_ref="email/re-board-decision",
    )
    ok_next, _ = validate_recipient_acceptance(tmp_path, unverified_receipt)
    assert ok_next is False

    empty_use_receipt = RecipientAcceptanceReceipt(
        deliverable_path="deliverable.md",
        deliverable_sha256=live_sha,
        recipient="Jane Doe (Program Lead)",
        intended_use="  ",
        next_action_verified=True,
        accepted_at="2026-11-24T19:05:00Z",
        evidence_ref="email/re-board-decision",
    )
    ok_use, _ = validate_recipient_acceptance(tmp_path, empty_use_receipt)
    assert ok_use is False

    empty_ref_receipt = RecipientAcceptanceReceipt(
        deliverable_path="deliverable.md",
        deliverable_sha256=live_sha,
        recipient="Jane Doe (Program Lead)",
        intended_use="Board decision",
        next_action_verified=True,
        accepted_at="2026-11-24T19:05:00Z",
        evidence_ref="",
    )
    ok_ref, _ = validate_recipient_acceptance(tmp_path, empty_ref_receipt)
    assert ok_ref is False

    missing_receipt = RecipientAcceptanceReceipt(
        deliverable_path="does_not_exist.md",
        deliverable_sha256=live_sha,
        recipient="Jane Doe (Program Lead)",
        intended_use="Board decision",
        next_action_verified=True,
        accepted_at="2026-11-24T19:05:00Z",
        evidence_ref="email/re-board-decision",
    )
    ok_missing, reason_missing = validate_recipient_acceptance(tmp_path, missing_receipt)
    assert ok_missing is False
    assert "not found" in reason_missing.lower()

    escape_receipt = RecipientAcceptanceReceipt(
        deliverable_path="../escape.md",
        deliverable_sha256=live_sha,
        recipient="Jane Doe (Program Lead)",
        intended_use="Board decision",
        next_action_verified=True,
        accepted_at="2026-11-24T19:05:00Z",
        evidence_ref="email/re-board-decision",
    )
    ok_escape, reason_escape = validate_recipient_acceptance(tmp_path, escape_receipt)
    assert ok_escape is False
    assert "escapes" in reason_escape.lower()


def test_recipient_acceptance_passes_with_real_recipient_and_matching_sha(
    tmp_path: Path,
) -> None:
    out_dir = tmp_path / "artifacts"
    out_dir.mkdir()
    deliverable = out_dir / "deck.md"
    payload = b"# Executive Deck\nApproved slides.\n"
    deliverable.write_bytes(payload)
    digest = _sha256_hex(payload)

    receipt = RecipientAcceptanceReceipt(
        deliverable_path="artifacts/deck.md",
        deliverable_sha256=digest,
        recipient="Marcus Chen (VP Strategy)",
        intended_use="Quarterly planning review",
        next_action_verified=True,
        accepted_at="2026-11-24T19:10:00Z",
        evidence_ref="meeting/q4-review#item-3",
    )
    ok, msg = validate_recipient_acceptance(tmp_path, receipt)
    assert ok is True
    assert "Marcus Chen" in msg


@pytest.mark.parametrize(
    "bad_metric",
    ["commit_count", "commits_merged", "loc_added", "total_loc", "line_count", "files_touched"],
)
def test_improvement_entry_rejects_commit_and_loc_metrics(bad_metric: str) -> None:
    entry = _make_improvement(1, metric_name=bad_metric, before_value=1.0, after_value=5.0, higher_is_better=True)
    ok, reason = validate_improvement_entry(entry)
    assert ok is False
    assert "rejected" in reason.lower()


def test_improvement_entry_rejects_non_improving_and_invalid_evidence() -> None:
    eq_high = _make_improvement(1, metric_name="pass_rate", before_value=0.8, after_value=0.8, higher_is_better=True)
    assert validate_improvement_entry(eq_high)[0] is False

    worse_high = _make_improvement(2, metric_name="pass_rate", before_value=0.8, after_value=0.7, higher_is_better=True)
    assert validate_improvement_entry(worse_high)[0] is False

    eq_low = _make_improvement(3, metric_name="latency_ms", before_value=50.0, after_value=50.0, higher_is_better=False)
    assert validate_improvement_entry(eq_low)[0] is False

    worse_low = _make_improvement(4, metric_name="latency_ms", before_value=50.0, after_value=60.0, higher_is_better=False)
    assert validate_improvement_entry(worse_low)[0] is False

    nan_entry = _make_improvement(5, before_value=math.nan, after_value=10.0)
    assert validate_improvement_entry(nan_entry)[0] is False

    no_cmd = _make_improvement(6, verify_cmd="   ")
    assert validate_improvement_entry(no_cmd)[0] is False

    bad_sha = _make_improvement(7, evidence_sha256="not-a-sha256")
    ok_sha, reason_sha = validate_improvement_entry(bad_sha)
    assert ok_sha is False
    assert "invalid" in reason_sha.lower()


def test_g5_graduation_fails_under_10_and_passes_at_10_distinct_improvements() -> None:
    nine_entries = [_make_improvement(i) for i in range(1, 10)]
    res_nine = evaluate_g5_graduation(nine_entries)
    assert res_nine["target"] == 10
    assert res_nine["verified_count"] == 9
    assert res_nine["passed"] is False
    assert res_nine["rejected"] == []

    mixed = nine_entries + [
        _make_improvement(10, metric_name="commit_count", before_value=1.0, after_value=5.0, higher_is_better=True),
        _make_improvement(1),
    ]
    res_mixed = evaluate_g5_graduation(mixed)
    assert res_mixed["verified_count"] == 9
    assert res_mixed["passed"] is False
    assert len(res_mixed["rejected"]) == 2

    ten_entries = [
        _make_improvement(
            i,
            metric_name="cv_auc" if i % 2 == 0 else "route_p95_ms",
            before_value=0.70 if i % 2 == 0 else 140.0,
            after_value=0.85 if i % 2 == 0 else 35.0,
            higher_is_better=(i % 2 == 0),
        )
        for i in range(1, 11)
    ]
    res_ten = evaluate_g5_graduation(ten_entries)
    assert res_ten["target"] == 10
    assert res_ten["verified_count"] == 10
    assert res_ten["passed"] is True
    assert res_ten["rejected"] == []


def test_g5_ledger_persistence_and_verification(tmp_path: Path) -> None:
    ledger = tmp_path / ".agents" / "g5_outcomes.json"

    # Negative: missing ledger returns passed=False
    missing_res = verify_g5_ledger_file(tmp_path)
    assert missing_res["exists"] is False
    assert missing_res["passed"] is False

    # Negative: commit-counting entry rejected by record_g5_improvement
    bad = _make_improvement(99, metric_name="commit_velocity", before_value=1.0, after_value=3.0, higher_is_better=True)
    ok_bad, reason_bad = record_g5_improvement(ledger, bad)
    assert ok_bad is False
    assert "rejected" in reason_bad.lower()

    # Positive: persist 10 valid entries and verify roundtrip + graduation
    entries = [_make_improvement(i) for i in range(1, 11)]
    digest = save_g5_ledger(ledger, entries)
    assert len(digest) == 64
    loaded = load_g5_ledger(ledger)
    assert len(loaded) == 10

    res = verify_g5_ledger_file(tmp_path)
    assert res["exists"] is True
    assert res["verified_count"] == 10
    assert res["passed"] is True
    assert res["rejected"] == []


def test_live_repo_g5_outcomes_ledger_passes_10_entries() -> None:
    repo_root = SCRIPTS_DIR.parents[1]
    live_ledger = repo_root / ".agents" / "g5_outcomes.json"
    assert live_ledger.is_file(), "Expected live .agents/g5_outcomes.json G5 ledger"
    res = verify_g5_ledger_file(repo_root, live_ledger, target=10)
    assert res["passed"] is True, res["rejected"]
    assert res["verified_count"] >= 10
    assert res["rejected"] == []
