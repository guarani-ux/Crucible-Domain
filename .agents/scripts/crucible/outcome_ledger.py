"""G4 Recipient Acceptance and G5 Material Improvement Outcome Ledger."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

SELF_MODEL_RECIPIENTS = frozenset(
    {"", "self", "author", "agent", "model", "assistant", "llm"}
)

FORBIDDEN_METRIC_SUBSTRINGS = (
    "commit",
    "loc",
    "line_count",
    "files_touched",
)

SHA256_HEX_RE = re.compile(r"^[0-9a-fA-F]{64}$")


@dataclass(frozen=True)
class RecipientAcceptanceReceipt:
    """Recorded acceptance receipt bound to a real recipient and deliverable SHA-256."""

    deliverable_path: str
    deliverable_sha256: str
    recipient: str
    intended_use: str
    next_action_verified: bool
    accepted_at: str
    evidence_ref: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class MaterialImprovementEntry:
    """Measured before/after improvement entry backed by a verification command and evidence hash."""

    id: str
    weakness_id: str
    metric_name: str
    before_value: float
    after_value: float
    higher_is_better: bool
    verify_cmd: str
    evidence_sha256: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def validate_recipient_acceptance(
    root: Path, receipt: RecipientAcceptanceReceipt
) -> tuple[bool, str]:
    """Validate G4 recipient acceptance against live deliverable bytes and non-self custody."""
    recipient_norm = receipt.recipient.strip().lower()
    if recipient_norm in SELF_MODEL_RECIPIENTS:
        return False, f"self/model recipient rejected: {receipt.recipient!r}"

    if not receipt.next_action_verified:
        return False, "next_action_verified must be True"

    if not receipt.intended_use.strip():
        return False, "intended_use must be non-empty"

    if not receipt.evidence_ref.strip():
        return False, "evidence_ref must be non-empty"

    if not receipt.deliverable_path.strip():
        return False, "deliverable_path must be non-empty"

    root_resolved = Path(root).resolve()
    raw_rel = Path(receipt.deliverable_path)
    if raw_rel.is_absolute():
        return False, f"deliverable_path must be relative to root: {receipt.deliverable_path!r}"

    target = (root_resolved / raw_rel).resolve()
    if target != root_resolved and not target.is_relative_to(root_resolved):
        return False, f"deliverable_path escapes root: {receipt.deliverable_path!r}"

    if not target.is_file():
        return False, f"deliverable file not found: {receipt.deliverable_path}"

    expected_sha = receipt.deliverable_sha256.strip().lower()
    if not SHA256_HEX_RE.fullmatch(expected_sha):
        return False, f"invalid deliverable_sha256: {receipt.deliverable_sha256!r}"

    live_sha = hashlib.sha256(target.read_bytes()).hexdigest().lower()
    if live_sha != expected_sha:
        return (
            False,
            f"deliverable SHA-256 mismatch for {receipt.deliverable_path}: "
            f"expected {expected_sha}, got {live_sha}",
        )

    return True, f"accepted by {receipt.recipient.strip()} ({live_sha[:12]})"


def validate_improvement_entry(entry: MaterialImprovementEntry) -> tuple[bool, str]:
    """Validate a G5 material improvement entry against metric gaming and evidence rules."""
    if not entry.id.strip():
        return False, "entry id must be non-empty"

    if not entry.weakness_id.strip():
        return False, "weakness_id must be non-empty"

    metric_lower = entry.metric_name.strip().lower()
    if not metric_lower:
        return False, "metric_name must be non-empty"

    for forbidden in FORBIDDEN_METRIC_SUBSTRINGS:
        if forbidden in metric_lower:
            return (
                False,
                f"vanity/activity metric rejected ({forbidden!r} in {entry.metric_name!r})",
            )

    if not (math.isfinite(entry.before_value) and math.isfinite(entry.after_value)):
        return False, "before_value and after_value must be finite numbers"

    if entry.higher_is_better:
        if not (entry.after_value > entry.before_value):
            return (
                False,
                f"non-improving metric for higher_is_better=True: "
                f"{entry.before_value} -> {entry.after_value}",
            )
    else:
        if not (entry.after_value < entry.before_value):
            return (
                False,
                f"non-improving metric for higher_is_better=False: "
                f"{entry.before_value} -> {entry.after_value}",
            )

    if not entry.verify_cmd.strip():
        return False, "verify_cmd must be non-empty"

    if not SHA256_HEX_RE.fullmatch(entry.evidence_sha256.strip()):
        return False, f"invalid 64-hex evidence_sha256: {entry.evidence_sha256!r}"

    return True, "verified"


def evaluate_g5_graduation(
    entries: list[MaterialImprovementEntry], target: int = 10
) -> dict[str, Any]:
    """Evaluate G5 graduation across material improvement entries against target count."""
    verified_ids: set[str] = set()
    rejected: list[dict[str, str]] = []

    for entry in entries:
        ok, reason = validate_improvement_entry(entry)
        if not ok:
            rejected.append(
                {
                    "id": entry.id,
                    "weakness_id": entry.weakness_id,
                    "reason": reason,
                }
            )
            continue

        entry_id = entry.id.strip()
        if entry_id in verified_ids:
            rejected.append(
                {
                    "id": entry.id,
                    "weakness_id": entry.weakness_id,
                    "reason": f"duplicate improvement id: {entry_id!r}",
                }
            )
            continue

        verified_ids.add(entry_id)

    verified_count = len(verified_ids)
    passed = target > 0 and verified_count >= target
    return {
        "verified_count": verified_count,
        "target": target,
        "passed": passed,
        "rejected": rejected,
    }


DEFAULT_G5_LEDGER_REL_PATH = Path(".agents") / "g5_outcomes.json"


def load_g5_ledger(ledger_path: Path | str) -> list[MaterialImprovementEntry]:
    """Load MaterialImprovementEntry records from a JSON ledger file."""
    p = Path(ledger_path)
    if not p.is_file():
        return []
    raw = json.loads(p.read_text(encoding="utf-8"))
    rows = raw.get("entries", []) if isinstance(raw, dict) else raw
    if not isinstance(rows, list):
        raise ValueError(f"G5 ledger '{p}' must contain a JSON object with 'entries' list")
    entries: list[MaterialImprovementEntry] = []
    for item in rows:
        if not isinstance(item, dict):
            raise ValueError(f"G5 ledger '{p}' entry must be an object")
        entries.append(
            MaterialImprovementEntry(
                id=str(item["id"]),
                weakness_id=str(item["weakness_id"]),
                metric_name=str(item["metric_name"]),
                before_value=float(item["before_value"]),
                after_value=float(item["after_value"]),
                higher_is_better=bool(item["higher_is_better"]),
                verify_cmd=str(item["verify_cmd"]),
                evidence_sha256=str(item["evidence_sha256"]),
            )
        )
    return entries


def save_g5_ledger(ledger_path: Path | str, entries: list[MaterialImprovementEntry]) -> str:
    """Atomically persist G5 MaterialImprovementEntry ledger JSON and return its SHA-256."""
    p = Path(ledger_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "schema_version": "crucible.g5_outcomes.v1",
        "entries": [e.to_dict() for e in entries],
    }
    data = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    fd, tmp_name = tempfile.mkstemp(prefix=".g5_", dir=str(p.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp_name, p)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise
    return hashlib.sha256(data).hexdigest()


def record_g5_improvement(
    ledger_path: Path | str,
    entry: MaterialImprovementEntry,
) -> tuple[bool, str]:
    """Validate and upsert a MaterialImprovementEntry into the persistent G5 ledger."""
    ok, reason = validate_improvement_entry(entry)
    if not ok:
        return False, reason
    p = Path(ledger_path)
    existing = load_g5_ledger(p)
    updated = [e for e in existing if e.id.strip() != entry.id.strip()]
    updated.append(entry)
    save_g5_ledger(p, updated)
    return True, f"recorded {entry.id}"


def verify_g5_ledger_file(
    root: Path | str,
    ledger_path: Path | str | None = None,
    *,
    target: int = 10,
) -> dict[str, Any]:
    """Evaluate a G5 JSON ledger file on disk against target graduation threshold."""
    base = Path(root).resolve()
    target_path = Path(ledger_path) if ledger_path is not None else (base / DEFAULT_G5_LEDGER_REL_PATH)
    if not target_path.is_absolute():
        target_path = (base / target_path).resolve()
    if not target_path.is_file():
        return {
            "ledger_path": str(target_path),
            "exists": False,
            "verified_count": 0,
            "target": target,
            "passed": False,
            "rejected": [{"id": "$ledger", "weakness_id": "G5", "reason": f"ledger file not found: {target_path}"}],
        }
    entries = load_g5_ledger(target_path)
    summary = evaluate_g5_graduation(entries, target=target)
    return {
        "ledger_path": str(target_path),
        "exists": True,
        **summary,
    }
