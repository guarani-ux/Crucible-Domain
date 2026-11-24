"""Spoke Design-by-Contract: formal pre/postconditions and frame invariants for MCP spoke calls."""

from __future__ import annotations

import hashlib
import inspect
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

Predicate = Callable[..., Any]


class ContractViolationError(RuntimeError):
    """Raised when a spoke precondition, postcondition, or frame invariant fails."""

    def __init__(self, phase: str, spoke: str, action: str, detail: str) -> None:
        self.phase = phase
        self.spoke = spoke
        self.action = action
        self.detail = detail
        super().__init__(f"[{phase}] {spoke}.{action}: {detail}")


@dataclass(frozen=True)
class SpokeContract:
    """Design-by-Contract specification for an MCP spoke action."""

    spoke: str
    action: str
    requires: Sequence[Predicate] = ()
    ensures: Sequence[Predicate] = ()
    unchanged_roots: Sequence[str | Path] = ()


def _normalize_predicates(preds: Sequence[Predicate] | Predicate | None) -> tuple[Predicate, ...]:
    if preds is None:
        return ()
    if callable(preds):
        return (preds,)
    return tuple(preds)


def _normalize_roots(roots: Sequence[str | Path] | str | Path | None) -> tuple[str | Path, ...]:
    if roots is None:
        return ()
    if isinstance(roots, (str, Path)):
        return (roots,)
    return tuple(roots)


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _resolve_within_root(base: Path, entry: str | Path) -> tuple[str, Path]:
    raw = Path(entry)
    target = raw.resolve() if raw.is_absolute() else (base / raw).resolve()
    if target != base and not target.is_relative_to(base):
        raise ValueError(f"Unchanged root '{entry}' escapes root '{base}'")
    rel = target.relative_to(base).as_posix()
    return ("." if rel == "" else rel), target


def snapshot_roots(root: Path | str, unchanged_roots: Sequence[str | Path]) -> dict[str, str]:
    """Capture a deterministic content-hash snapshot for all declared unchanged roots."""
    base = Path(root).resolve()
    entries = _normalize_roots(unchanged_roots)
    snapshot: dict[str, str] = {}

    for entry in entries:
        rel_key, target = _resolve_within_root(base, entry)
        if not target.exists() and not target.is_symlink():
            snapshot[rel_key] = "absent"
            continue
        if target.is_file():
            snapshot[rel_key] = f"file:{_sha256_file(target)}"
            continue
        if target.is_dir():
            snapshot[rel_key] = "dir"
            for dirpath, dirnames, filenames in os.walk(target, followlinks=False):
                dirnames.sort()
                filenames.sort()
                cur_dir = Path(dirpath)
                for dname in dirnames:
                    dpath = cur_dir / dname
                    snapshot[dpath.relative_to(base).as_posix()] = "dir"
                for fname in filenames:
                    fpath = cur_dir / fname
                    snapshot[fpath.relative_to(base).as_posix()] = f"file:{_sha256_file(fpath)}"
            continue
        snapshot[rel_key] = "special"

    return snapshot


def _predicate_label(pred: Predicate) -> str:
    return getattr(pred, "__name__", type(pred).__name__)


def _accepts_two_args(pred: Predicate) -> bool:
    try:
        sig = inspect.signature(pred)
    except (TypeError, ValueError):
        return False
    positional = 0
    for param in sig.parameters.values():
        if param.kind == inspect.Parameter.VAR_POSITIONAL:
            return True
        if param.kind in (inspect.Parameter.POSITIONAL_ONLY, inspect.Parameter.POSITIONAL_OR_KEYWORD):
            positional += 1
    return positional >= 2


def _eval_predicate(phase: str, contract: SpokeContract, pred: Predicate, *args: Any) -> None:
    label = _predicate_label(pred)
    try:
        outcome = pred(*args)
    except Exception as exc:
        raise ContractViolationError(
            phase,
            contract.spoke,
            contract.action,
            f"predicate {label} raised {type(exc).__name__}: {exc}",
        ) from exc

    if isinstance(outcome, tuple) and len(outcome) == 2 and isinstance(outcome[0], bool):
        ok, detail = outcome
        if not ok:
            raise ContractViolationError(
                phase,
                contract.spoke,
                contract.action,
                str(detail) or f"predicate {label} failed",
            )
        return

    if not bool(outcome):
        raise ContractViolationError(
            phase,
            contract.spoke,
            contract.action,
            f"predicate {label} returned falsy",
        )


def _diff_snapshots(before: dict[str, str], after: dict[str, str]) -> list[str]:
    diffs: list[str] = []
    for key in sorted(set(before) | set(after)):
        if key not in before:
            diffs.append(f"added {key}")
        elif key not in after:
            diffs.append(f"removed {key}")
        elif before[key] != after[key]:
            diffs.append(f"modified {key}")
    return diffs


def verify_spoke_call(
    contract: SpokeContract,
    payload: Any,
    fn: Callable[[Any], Any],
    root: Path | str | None = None,
) -> Any:
    """Execute fn(payload) guarded by contract preconditions, postconditions, and frame invariants."""
    unchanged = _normalize_roots(contract.unchanged_roots)
    before_snap: dict[str, str] | None = None
    if unchanged:
        if root is None:
            raise ContractViolationError(
                "frame",
                contract.spoke,
                contract.action,
                "root must be provided when unchanged_roots is non-empty",
            )
        before_snap = snapshot_roots(root, unchanged)

    for pred in _normalize_predicates(contract.requires):
        _eval_predicate("requires", contract, pred, payload)

    result = fn(payload)

    for pred in _normalize_predicates(contract.ensures):
        if _accepts_two_args(pred):
            _eval_predicate("ensures", contract, pred, payload, result)
        else:
            _eval_predicate("ensures", contract, pred, result)

    if unchanged and before_snap is not None and root is not None:
        after_snap = snapshot_roots(root, unchanged)
        diffs = _diff_snapshots(before_snap, after_snap)
        if diffs:
            raise ContractViolationError(
                "frame",
                contract.spoke,
                contract.action,
                "; ".join(diffs),
            )

    return result
