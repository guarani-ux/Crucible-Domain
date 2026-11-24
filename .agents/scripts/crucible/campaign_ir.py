"""Campaign IR Compiler Front-End: typed IR, compile-time checks, incremental optimizer, and error-hash circuit breaker."""

from __future__ import annotations

import ast
import contextlib
import hashlib
import json
import math
import os
import re
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


class CampaignCompileError(ValueError):
    """Raised when compile-time validation of a CampaignSpec fails before Round 1."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


@dataclass
class SliceNode:
    """Single bounded vertical slice in a campaign DAG."""

    id: str
    target_paths: list[str]
    depends_on: list[str] = field(default_factory=list)
    verify_cmd: str = ""
    input_sha256: str = ""
    withheld_verify_cmd: str = ""
    withheld_failure_category: str = ""
    verify_timeout_s: float = 120.0


@dataclass
class CampaignSpec:
    """Typed Campaign IR specification."""

    name: str
    repo_root: str
    slices: list[SliceNode]
    allowed_roots: list[str] = field(default_factory=list)
    max_rounds: int = 12


@dataclass
class PlannedSlice:
    """Compiled and optimized slice ready for execution or cache skip."""

    node: SliceNode
    computed_sha256: str
    status: str  # "RUN" | "SKIP_CACHED"
    reason: str = ""


@dataclass
class CompiledCampaign:
    """Result of compile_campaign() + optimize_campaign()."""

    name: str
    repo_root: Path
    ordered_slices: list[PlannedSlice]

    @property
    def active_slices(self) -> list[PlannedSlice]:
        return [s for s in self.ordered_slices if s.status == "RUN"]

    @property
    def skipped_slices(self) -> list[PlannedSlice]:
        return [s for s in self.ordered_slices if s.status == "SKIP_CACHED"]

    @property
    def execution_waves(self) -> list[list[PlannedSlice]]:
        """Group active slices into parallel DAG execution waves (levelization)."""
        active = {s.node.id: s for s in self.active_slices}
        if not active:
            return []
        depth: dict[str, int] = {}
        for ps in self.ordered_slices:
            sid = ps.node.id
            if sid not in active:
                continue
            dep_depths = [depth[d] for d in ps.node.depends_on if d in depth]
            depth[sid] = (max(dep_depths) + 1) if dep_depths else 0
        max_wave = max(depth.values(), default=0)
        return [
            [ps for ps in self.active_slices if depth[ps.node.id] == w]
            for w in range(max_wave + 1)
        ]


def _resolve_allowed_roots(spec: CampaignSpec) -> list[Path]:
    roots: list[Path] = []
    if spec.allowed_roots:
        for r in spec.allowed_roots:
            if r.strip():
                roots.append(Path(r).resolve())
    else:
        env_val = os.environ.get("CRUCIBLE_ALLOWED_ROOTS", "").strip()
        if env_val:
            for part in env_val.split(os.pathsep):
                if part.strip():
                    roots.append(Path(part).resolve())
    repo_root = Path(spec.repo_root).resolve()
    if not roots:
        roots.append(repo_root)
    return roots


def _is_within_any(path: Path, roots: list[Path]) -> bool:
    for root in roots:
        if path == root or path.is_relative_to(root):
            return True
    return False


def _topological_order(slices: list[SliceNode]) -> tuple[list[SliceNode], list[str]]:
    by_id = {s.id: s for s in slices}
    in_degree = {s.id: 0 for s in slices}
    dependents: dict[str, list[str]] = {s.id: [] for s in slices}

    for s in slices:
        for dep in s.depends_on:
            if dep in by_id:
                in_degree[s.id] += 1
                dependents[dep].append(s.id)

    queue = [s.id for s in slices if in_degree[s.id] == 0]
    ordered: list[SliceNode] = []
    while queue:
        curr = queue.pop(0)
        ordered.append(by_id[curr])
        for nxt in dependents[curr]:
            in_degree[nxt] -= 1
            if in_degree[nxt] == 0:
                queue.append(nxt)

    if len(ordered) != len(slices):
        cycle_nodes = sorted(sid for sid, deg in in_degree.items() if deg > 0)
        return [], [f"dependency cycle detected involving slices: {', '.join(cycle_nodes)}"]
    return ordered, []


def compile_campaign(spec: CampaignSpec) -> list[SliceNode]:
    """Validate path containment, dependency existence, unique IDs, and acyclicity before Round 1."""
    errors: list[str] = []
    repo_root = Path(spec.repo_root).resolve()
    allowed_roots = _resolve_allowed_roots(spec)

    if not spec.name.strip():
        errors.append("campaign name must be non-empty")
    if spec.max_rounds < 1:
        errors.append(f"max_rounds must be >= 1, got {spec.max_rounds}")

    seen_ids: set[str] = set()
    for s in spec.slices:
        if not s.id.strip():
            errors.append("slice id must be non-empty")
            continue
        if s.id in seen_ids:
            errors.append(f"duplicate slice id: {s.id}")
        seen_ids.add(s.id)

    for s in spec.slices:
        for dep in s.depends_on:
            if dep not in seen_ids:
                errors.append(f"slice '{s.id}' depends on missing slice '{dep}'")
            if dep == s.id:
                errors.append(f"slice '{s.id}' cannot depend on itself")

        for raw_path in s.target_paths:
            p = Path(raw_path)
            resolved = p.resolve() if p.is_absolute() else (repo_root / p).resolve()
            if not _is_within_any(resolved, allowed_roots):
                errors.append(
                    f"slice '{s.id}' target_path '{raw_path}' escapes allowed roots"
                )
            if not _is_within_any(resolved, [repo_root]):
                errors.append(
                    f"slice '{s.id}' target_path '{raw_path}' escapes repo_root '{repo_root}'"
                )

    ordered, cycle_errors = _topological_order(spec.slices)
    errors.extend(cycle_errors)

    if errors:
        raise CampaignCompileError(errors)
    return ordered


def compute_slice_input_sha256(node: SliceNode, repo_root: Path | str) -> str:
    """Compute deterministic SHA-256 over slice metadata and target file contents."""
    if node.input_sha256:
        return node.input_sha256

    root = Path(repo_root).resolve()
    h = hashlib.sha256()
    h.update(node.id.encode("utf-8"))
    h.update(b"\x00")
    h.update(node.verify_cmd.encode("utf-8"))
    h.update(b"\x00")
    if node.withheld_verify_cmd:
        h.update(b"WITHHELD:")
        h.update(node.withheld_verify_cmd.encode("utf-8"))
        h.update(b"\x00")
    for dep in sorted(node.depends_on):
        h.update(dep.encode("utf-8"))
        h.update(b"\x00")

    seen_files: set[Path] = set()
    queue: list[Path] = []
    for raw_path in sorted(node.target_paths):
        p = Path(raw_path)
        resolved = p.resolve() if p.is_absolute() else (root / p).resolve()
        if resolved not in seen_files:
            seen_files.add(resolved)
            queue.append(resolved)

    # W3: Include local Python imports via ast so shared-module edits invalidate cache
    idx = 0
    while idx < len(queue):
        curr = queue[idx]
        idx += 1
        if curr.is_file() and curr.suffix.lower() == ".py":
            try:
                tree = ast.parse(curr.read_text(encoding="utf-8"))
            except (SyntaxError, UnicodeDecodeError):
                tree = None
            if tree is not None:
                for stmt in ast.walk(tree):
                    mod_names: list[str] = []
                    if isinstance(stmt, ast.Import):
                        mod_names.extend(alias.name for alias in stmt.names)
                    elif isinstance(stmt, ast.ImportFrom) and stmt.module:
                        mod_names.append(stmt.module)
                    for mod in mod_names:
                        cand = (curr.parent / (mod.replace(".", "/") + ".py")).resolve()
                        if cand.is_file() and cand.is_relative_to(root) and cand not in seen_files:
                            seen_files.add(cand)
                            queue.append(cand)

    for resolved in sorted(seen_files):
        rel = str(resolved.relative_to(root)).replace("\\", "/") if resolved.is_relative_to(root) else str(resolved)
        h.update(rel.encode("utf-8"))
        h.update(b"\x00")
        if resolved.is_file():
            h.update(b"FILE:")
            h.update(resolved.read_bytes())
        else:
            h.update(b"MISSING")
        h.update(b"\x00")
    return h.hexdigest()


class CacheConflictError(RuntimeError):
    """Raised when optimistic CAS receipt cache write observes a stale SHA-256."""


_CACHE_LOCKS_GUARD = threading.Lock()
_CACHE_LOCKS: dict[Path, threading.RLock] = {}


def _path_lock(path: Path) -> threading.RLock:
    resolved = path.resolve()
    with _CACHE_LOCKS_GUARD:
        lock = _CACHE_LOCKS.get(resolved)
        if lock is None:
            lock = threading.RLock()
            _CACHE_LOCKS[resolved] = lock
        return lock


def file_sha256(path: Path | str) -> str | None:
    """Return SHA-256 hex digest of file if present, or None if missing."""
    p = Path(path)
    if not p.is_file():
        return None
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _write_receipt_cache_atomic(p: Path, cache: dict[str, str]) -> str:
    p.parent.mkdir(parents=True, exist_ok=True)
    normalized = {str(k): str(v) for k, v in cache.items()}
    payload = (json.dumps(dict(sorted(normalized.items())), indent=2) + "\n").encode("utf-8")
    fd, tmp_name = tempfile.mkstemp(prefix=".ir_cache_", dir=str(p.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
        os.replace(tmp_name, p)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise
    return hashlib.sha256(payload).hexdigest()


def load_receipt_cache(cache_path: Path | str) -> dict[str, str]:
    """Load local slice_id -> input_sha256 receipt cache."""
    p = Path(cache_path)
    with _path_lock(p):
        if not p.is_file():
            return {}
        data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}


def save_receipt_cache(cache_path: Path | str, cache: dict[str, str]) -> None:
    """Atomically persist slice_id -> input_sha256 receipt cache."""
    p = Path(cache_path)
    with _path_lock(p):
        _write_receipt_cache_atomic(p, cache)


def save_receipt_cache_cas(
    cache_path: Path | str,
    cache: dict[str, str],
    expected_sha256: str | None = None,
) -> str:
    """Atomically persist receipt cache iff current on-disk SHA-256 matches expected_sha256 (when provided)."""
    p = Path(cache_path)
    with _path_lock(p):
        current_sha = file_sha256(p)
        if expected_sha256 is not None and current_sha != expected_sha256:
            raise CacheConflictError(
                f"Receipt cache conflict for '{p}': expected sha256 {expected_sha256}, found {current_sha}"
            )
        return _write_receipt_cache_atomic(p, cache)


def merge_receipt_cache(
    cache_path: Path | str,
    updates: dict[str, str],
    max_retries: int = 5,
) -> tuple[dict[str, str], str]:
    """Read-merge-CAS loop preserving concurrent keys from other slices/workers."""
    if max_retries < 0:
        raise ValueError("max_retries must be >= 0")
    p = Path(cache_path)
    clean_updates = {str(k): str(v) for k, v in updates.items()}

    for attempt in range(max_retries + 1):
        expected_sha = file_sha256(p)
        try:
            ctx = _path_lock(p) if expected_sha is None else contextlib.nullcontext()
            with ctx:
                if expected_sha is None:
                    expected_sha = file_sha256(p)
                current = load_receipt_cache(p)
                merged = {**current, **clean_updates}
                new_sha = save_receipt_cache_cas(p, merged, expected_sha256=expected_sha)
                return merged, new_sha
        except CacheConflictError:
            if attempt >= max_retries:
                raise
    raise CacheConflictError(f"Exceeded max_retries ({max_retries}) merging receipt cache '{p}'")


def optimize_campaign(
    spec: CampaignSpec,
    receipt_cache: dict[str, str] | Path | str | None = None,
) -> CompiledCampaign:
    """Compile and run incremental optimizer pass, marking unchanged slices SKIP_CACHED."""
    ordered = compile_campaign(spec)
    repo_root = Path(spec.repo_root).resolve()

    if isinstance(receipt_cache, (Path, str)):
        cache = load_receipt_cache(receipt_cache)
    elif isinstance(receipt_cache, dict):
        cache = receipt_cache
    else:
        cache = {}

    status_by_id: dict[str, str] = {}
    planned: list[PlannedSlice] = []
    for node in ordered:
        digest = compute_slice_input_sha256(node, repo_root)
        upstream_dirty = any(status_by_id.get(dep) != "SKIP_CACHED" for dep in node.depends_on)
        if not upstream_dirty and cache.get(node.id) == digest:
            status = "SKIP_CACHED"
            reason = "input_sha256 matches local receipt cache"
        elif upstream_dirty:
            status = "RUN"
            reason = "upstream dependency invalidated cache"
        else:
            status = "RUN"
            reason = "input_sha256 changed or uncached"
        status_by_id[node.id] = status
        planned.append(
            PlannedSlice(
                node=node,
                computed_sha256=digest,
                status=status,
                reason=reason,
            )
        )

    return CompiledCampaign(name=spec.name, repo_root=repo_root, ordered_slices=planned)


_VOLATILE_PATTERNS = (
    (re.compile(r"0x[0-9a-fA-F]+"), "<HEX>"),
    (re.compile(r"\b\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}(?:\.\d+)?Z?\b"), "<TS>"),
    (re.compile(r"pytest-\d+"), "pytest-<N>"),
    (re.compile(r"\bin \d+\.\d+s\b"), "in <T>s"),
)


def hash_error_output(output: str) -> str:
    """Compute canonical SHA-256 of failure output, stripping volatile paths/timestamps/hex."""
    text = "\n".join(line.rstrip() for line in output.strip().splitlines())
    for pat, repl in _VOLATILE_PATTERNS:
        text = pat.sub(repl, text)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


@dataclass
class BreakerState:
    tripped: bool
    reason: str
    error_sha256: str | None
    consecutive_failures: int


class ErrorCircuitBreaker:
    """Trips immediately on 2 consecutive identical error hashes or max_consecutive_failures."""

    def __init__(self, max_consecutive_failures: int = 3) -> None:
        if max_consecutive_failures < 1:
            raise ValueError("max_consecutive_failures must be >= 1")
        self.max_consecutive_failures = max_consecutive_failures
        self.last_error_sha256: str | None = None
        self.consecutive_failures: int = 0
        self.tripped: bool = False
        self.trip_reason: str = ""

    def record_success(self) -> BreakerState:
        self.last_error_sha256 = None
        self.consecutive_failures = 0
        self.tripped = False
        self.trip_reason = ""
        return BreakerState(
            tripped=False,
            reason="",
            error_sha256=None,
            consecutive_failures=0,
        )

    def record_failure(self, error_output: str) -> BreakerState:
        digest = hash_error_output(error_output)
        self.consecutive_failures += 1

        if self.last_error_sha256 is not None and digest == self.last_error_sha256:
            self.tripped = True
            self.trip_reason = "IDENTICAL_ERROR_HASH"
        elif self.consecutive_failures >= self.max_consecutive_failures:
            self.tripped = True
            self.trip_reason = "MAX_CONSECUTIVE_FAILURES"

        self.last_error_sha256 = digest
        return BreakerState(
            tripped=self.tripped,
            reason=self.trip_reason,
            error_sha256=digest,
            consecutive_failures=self.consecutive_failures,
        )


class StateTransitionError(RuntimeError):
    """Raised on illegal LoopStateMachine transitions or stale SHA verification."""


class LoopStateMachine:
    """Deterministic finite state machine enforcing PLAN -> STAGE -> VERIFY -> COMMIT -> CACHE."""

    STATES = ("PLAN", "STAGE", "VERIFY", "COMMIT", "CACHE", "FAILED")

    def __init__(self) -> None:
        self.state: str = "PLAN"
        self.campaign_name: str = ""
        self.slice_id: str = ""
        self.staged_after_sha256: str = ""
        self.verified_sha256: str = ""
        self.commit_sha: str = ""
        self.last_error_sha256: str | None = None

    def plan(self, campaign_name: str, slice_id: str) -> str:
        if self.state != "PLAN":
            raise StateTransitionError(f"plan() requires state PLAN, current state is {self.state}")
        if not isinstance(campaign_name, str) or not campaign_name.strip():
            raise StateTransitionError("plan() requires non-empty campaign_name")
        if not isinstance(slice_id, str) or not slice_id.strip():
            raise StateTransitionError("plan() requires non-empty slice_id")
        self.campaign_name = campaign_name.strip()
        self.slice_id = slice_id.strip()
        return self.state

    def stage(self, after_sha256: str) -> str:
        if self.state != "PLAN":
            raise StateTransitionError(f"stage() requires state PLAN, current state is {self.state}")
        if not isinstance(after_sha256, str) or not after_sha256.strip():
            raise StateTransitionError("stage() requires non-empty after_sha256")
        self.staged_after_sha256 = after_sha256.strip()
        self.verified_sha256 = ""
        self.commit_sha = ""
        self.last_error_sha256 = None
        self.state = "STAGE"
        return self.state

    def verify(self, exit_code: int, staged_sha256: str, error_output: str = "") -> bool:
        if self.state != "STAGE":
            raise StateTransitionError(f"verify() requires state STAGE, current state is {self.state}")
        if not isinstance(staged_sha256, str) or not staged_sha256.strip():
            raise StateTransitionError("verify() requires non-empty staged_sha256")
        if staged_sha256.strip() != self.staged_after_sha256:
            raise StateTransitionError(
                f"stale verification rejected: staged_sha256 '{staged_sha256}' != '{self.staged_after_sha256}'"
            )
        if exit_code == 0:
            self.verified_sha256 = self.staged_after_sha256
            self.last_error_sha256 = None
            self.state = "VERIFY"
            return True
        self.last_error_sha256 = hash_error_output(error_output)
        self.state = "FAILED"
        return False

    def commit(self, commit_sha: str) -> str:
        if self.state != "VERIFY":
            raise StateTransitionError(f"commit() requires state VERIFY, current state is {self.state}")
        if not isinstance(commit_sha, str) or not commit_sha.strip():
            raise StateTransitionError("commit() requires non-empty commit_sha")
        if not self.verified_sha256 or self.verified_sha256 != self.staged_after_sha256:
            raise StateTransitionError("commit() requires verified_sha256 matching staged_after_sha256")
        self.commit_sha = commit_sha.strip()
        self.state = "COMMIT"
        return self.state

    def cache(self) -> str:
        if self.state != "COMMIT":
            raise StateTransitionError(f"cache() requires state COMMIT, current state is {self.state}")
        self.state = "CACHE"
        return self.state

    def reset(self) -> str:
        self.state = "PLAN"
        self.campaign_name = ""
        self.slice_id = ""
        self.staged_after_sha256 = ""
        self.verified_sha256 = ""
        self.commit_sha = ""
        self.last_error_sha256 = None
        return self.state


RATCHET_LEDGER_COLUMNS = (
    "timestamp",
    "campaign",
    "round_id",
    "slice_id",
    "status",
    "seconds",
    "commit_sha",
    "after_sha256",
    "error_sha256",
)
RATCHET_STATUSES = frozenset({"KEEP", "REVERT", "SKIP_CACHED", "TRIPPED"})


@dataclass
class RatchetEntry:
    """Single append-only TSV ratchet ledger record."""

    timestamp: str
    campaign: str
    round_id: int
    slice_id: str
    status: str
    seconds: float
    commit_sha: str = ""
    after_sha256: str = ""
    error_sha256: str = ""

    def __post_init__(self) -> None:
        if self.status not in RATCHET_STATUSES:
            raise ValueError(
                f"invalid ratchet status '{self.status}'; expected one of {sorted(RATCHET_STATUSES)}"
            )
        if isinstance(self.round_id, bool) or not isinstance(self.round_id, int) or self.round_id < 0:
            raise ValueError(f"round_id must be a non-negative int, got {self.round_id!r}")
        if (
            isinstance(self.seconds, bool)
            or not isinstance(self.seconds, (int, float))
            or not math.isfinite(float(self.seconds))
            or self.seconds < 0
        ):
            raise ValueError(f"seconds must be a finite number >= 0, got {self.seconds!r}")
        self.seconds = float(self.seconds)
        for fname in ("timestamp", "campaign", "slice_id", "commit_sha", "after_sha256", "error_sha256"):
            val = getattr(self, fname)
            if not isinstance(val, str):
                raise ValueError(f"{fname} must be str, got {type(val).__name__}")
            if any(ch in val for ch in ("\t", "\n", "\r")):
                raise ValueError(f"{fname} cannot contain tabs or newlines")


def append_ratchet_ledger(ledger_path: Path | str, entry: RatchetEntry) -> None:
    """Append a RatchetEntry row to a TSV ledger, creating the header if missing or empty."""
    p = Path(ledger_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    row = "\t".join(
        [
            entry.timestamp,
            entry.campaign,
            str(entry.round_id),
            entry.slice_id,
            entry.status,
            repr(entry.seconds),
            entry.commit_sha,
            entry.after_sha256,
            entry.error_sha256,
        ]
    )
    with _path_lock(p):
        needs_header = (not p.is_file()) or (p.stat().st_size == 0)
        with p.open("a", encoding="utf-8", newline="\n") as fh:
            if needs_header:
                fh.write("\t".join(RATCHET_LEDGER_COLUMNS) + "\n")
            fh.write(row + "\n")


def load_ratchet_ledger(ledger_path: Path | str) -> list[RatchetEntry]:
    """Parse an append-only TSV ratchet ledger into RatchetEntry records."""
    p = Path(ledger_path)
    with _path_lock(p):
        if not p.is_file() or p.stat().st_size == 0:
            return []
        lines = p.read_text(encoding="utf-8").splitlines()
    if not lines:
        return []
    header = lines[0].split("\t")
    if header != list(RATCHET_LEDGER_COLUMNS):
        raise ValueError(f"invalid ratchet ledger header: {header!r}")
    entries: list[RatchetEntry] = []
    for idx, line in enumerate(lines[1:], start=2):
        if not line:
            continue
        parts = line.split("\t")
        if len(parts) != len(RATCHET_LEDGER_COLUMNS):
            raise ValueError(
                f"invalid ratchet ledger column count on line {idx}: expected {len(RATCHET_LEDGER_COLUMNS)}, got {len(parts)}"
            )
        entries.append(
            RatchetEntry(
                timestamp=parts[0],
                campaign=parts[1],
                round_id=int(parts[2]),
                slice_id=parts[3],
                status=parts[4],
                seconds=float(parts[5]),
                commit_sha=parts[6],
                after_sha256=parts[7],
                error_sha256=parts[8],
            )
        )
    return entries


WORKER_RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["slice_id", "commit_sha", "after_sha256", "passed", "error_output"],
    "properties": {
        "slice_id": {"type": "string", "minLength": 1},
        "commit_sha": {"type": "string"},
        "after_sha256": {"type": "string"},
        "passed": {"type": "boolean"},
        "error_output": {"type": "string"},
    },
}


def _expect_str_list(value: Any, label: str, errors: list[str]) -> list[str]:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        errors.append(f"{label} must be a list of strings")
        return []
    return list(value)


def _read_campaign_json_file(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise CampaignCompileError([f"invalid campaign spec JSON in '{path}': {exc}"]) from exc


def load_campaign_spec(source: Path | str | dict[str, Any]) -> CampaignSpec:
    """Construct CampaignSpec and SliceNode list from a JSON file path, JSON string, or dict."""
    if isinstance(source, dict):
        raw: Any = source
    elif isinstance(source, Path):
        raw = _read_campaign_json_file(source)
    elif isinstance(source, str):
        if source.lstrip().startswith(("{", "[")):
            try:
                raw = json.loads(source)
            except json.JSONDecodeError as exc:
                raise CampaignCompileError([f"invalid campaign spec JSON string: {exc}"]) from exc
        else:
            raw = _read_campaign_json_file(Path(source))
    else:
        raise TypeError(f"source must be Path, str, or dict, got {type(source).__name__}")

    if not isinstance(raw, dict):
        raise CampaignCompileError(["campaign spec root must be a JSON object"])

    errors: list[str] = []
    name = raw.get("name")
    repo_root = raw.get("repo_root")
    if not isinstance(name, str):
        errors.append("campaign spec 'name' must be a string")
    if not isinstance(repo_root, str):
        errors.append("campaign spec 'repo_root' must be a string")

    allowed_roots_raw = raw.get("allowed_roots", [])
    allowed_roots = _expect_str_list(allowed_roots_raw, "campaign spec 'allowed_roots'", errors)

    max_rounds = raw.get("max_rounds", 12)
    if isinstance(max_rounds, bool) or not isinstance(max_rounds, int):
        errors.append("campaign spec 'max_rounds' must be an integer")

    raw_slices = raw.get("slices")
    slices: list[SliceNode] = []
    if not isinstance(raw_slices, list):
        errors.append("campaign spec 'slices' must be a list")
    else:
        for idx, item in enumerate(raw_slices):
            if not isinstance(item, dict):
                errors.append(f"slices[{idx}] must be an object")
                continue
            sid = item.get("id")
            if not isinstance(sid, str):
                errors.append(f"slices[{idx}].id must be a string")
                continue
            target_paths = _expect_str_list(item.get("target_paths"), f"slices[{idx}].target_paths", errors)
            depends_on = _expect_str_list(item.get("depends_on", []), f"slices[{idx}].depends_on", errors)
            verify_cmd = item.get("verify_cmd", "")
            input_sha256 = item.get("input_sha256", "")
            withheld_verify_cmd = item.get("withheld_verify_cmd", "")
            withheld_failure_category = item.get("withheld_failure_category", "")
            verify_timeout_s = item.get("verify_timeout_s", 120.0)
            if not isinstance(verify_cmd, str):
                errors.append(f"slices[{idx}].verify_cmd must be a string")
                verify_cmd = ""
            if not isinstance(input_sha256, str):
                errors.append(f"slices[{idx}].input_sha256 must be a string")
                input_sha256 = ""
            if not isinstance(withheld_verify_cmd, str):
                errors.append(f"slices[{idx}].withheld_verify_cmd must be a string")
                withheld_verify_cmd = ""
            if not isinstance(withheld_failure_category, str):
                errors.append(f"slices[{idx}].withheld_failure_category must be a string")
                withheld_failure_category = ""
            if (
                isinstance(verify_timeout_s, bool)
                or not isinstance(verify_timeout_s, (int, float))
                or not math.isfinite(float(verify_timeout_s))
                or float(verify_timeout_s) <= 0
            ):
                errors.append(f"slices[{idx}].verify_timeout_s must be a positive number")
                verify_timeout_s = 120.0
            slices.append(
                SliceNode(
                    id=sid,
                    target_paths=target_paths,
                    depends_on=depends_on,
                    verify_cmd=verify_cmd,
                    input_sha256=input_sha256,
                    withheld_verify_cmd=withheld_verify_cmd,
                    withheld_failure_category=withheld_failure_category,
                    verify_timeout_s=float(verify_timeout_s),
                )
            )

    if errors:
        raise CampaignCompileError(errors)

    return CampaignSpec(
        name=name,
        repo_root=repo_root,
        slices=slices,
        allowed_roots=allowed_roots,
        max_rounds=max_rounds,
    )


def build_slice_worker_prompt(planned_slice: PlannedSlice, repo_root: Path | str) -> str:
    """Emit minimal delta prompt containing only slice.id, target_paths, depends_on, verify_cmd, and computed_sha256."""
    node = planned_slice.node
    root = Path(repo_root).resolve()
    norm_paths: list[str] = []
    for raw in node.target_paths:
        p = Path(raw)
        if p.is_absolute():
            resolved = p.resolve()
            if resolved.is_relative_to(root):
                norm_paths.append(str(resolved.relative_to(root)).replace("\\", "/"))
                continue
        norm_paths.append(raw)
    return "\n".join(
        [
            f"slice_id: {node.id}",
            f"target_paths: {json.dumps(norm_paths)}",
            f"depends_on: {json.dumps(node.depends_on)}",
            f"verify_cmd: {node.verify_cmd}",
            f"computed_sha256: {planned_slice.computed_sha256}",
        ]
    ) + "\n"


@dataclass(frozen=True)
class CampaignTelemetryEvent:
    """Schema-versioned, append-only telemetry record for campaign execution."""

    slice_id: str
    phase: str
    status: str
    duration_ms: float = 0.0
    wave_idx: int = 0
    cache_hit: bool = False
    error_sha256: str = ""
    schema_version: str = "1.0"


def emit_telemetry_event(telemetry_path: Path | str, event: CampaignTelemetryEvent) -> None:
    """Append a single JSONL telemetry event without mutating prior records."""
    path = Path(telemetry_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "schema_version": event.schema_version,
        "wave_idx": event.wave_idx,
        "slice_id": event.slice_id,
        "phase": event.phase,
        "status": event.status,
        "duration_ms": round(event.duration_ms, 3),
        "cache_hit": event.cache_hit,
        "error_sha256": event.error_sha256,
    }
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(record, sort_keys=True) + "\n")


def summarize_telemetry(telemetry_path: Path | str) -> dict[str, Any]:
    """Aggregate campaign JSONL telemetry to surface bottlenecks, cache hits, and error clusters."""
    path = Path(telemetry_path)
    if not path.exists():
        return {
            "total_events": 0,
            "total_ms": 0.0,
            "cache_hit_rate": 0.0,
            "slowest_slice": None,
            "failure_counts_by_error_sha256": {},
        }

    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))

    if not events:
        return {
            "total_events": 0,
            "total_ms": 0.0,
            "cache_hit_rate": 0.0,
            "slowest_slice": None,
            "failure_counts_by_error_sha256": {},
        }

    total_ms = sum(float(e.get("duration_ms", 0.0)) for e in events)
    cache_hits = sum(1 for e in events if e.get("cache_hit"))
    slowest = max(events, key=lambda e: float(e.get("duration_ms", 0.0)))
    failures: dict[str, int] = {}
    for e in events:
        err = str(e.get("error_sha256", "") or "")
        if err:
            failures[err] = failures.get(err, 0) + 1

    return {
        "total_events": len(events),
        "total_ms": round(total_ms, 3),
        "cache_hit_rate": round(cache_hits / len(events), 4),
        "slowest_slice": slowest.get("slice_id"),
        "failure_counts_by_error_sha256": failures,
    }

@dataclass
class CampaignCheckpoint:
    """Persistent checkpoint tracking completed/failed slices and bounded round count."""

    campaign_name: str
    completed_slices: dict[str, str] = field(default_factory=dict)
    failed_slices: dict[str, str] = field(default_factory=dict)
    rounds_used: int = 0
    max_rounds: int = 12


def save_campaign_checkpoint(path: Path | str, cp: CampaignCheckpoint) -> None:
    """Atomically persist CampaignCheckpoint JSON via temp file in parent + os.replace."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "campaign_name": str(cp.campaign_name),
        "completed_slices": {str(k): str(v) for k, v in sorted(cp.completed_slices.items())},
        "failed_slices": {str(k): str(v) for k, v in sorted(cp.failed_slices.items())},
        "rounds_used": int(cp.rounds_used),
        "max_rounds": int(cp.max_rounds),
    }
    data = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")
    fd, tmp_name = tempfile.mkstemp(prefix=".cp_", dir=str(p.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
        os.replace(tmp_name, p)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def load_campaign_checkpoint(path: Path | str) -> CampaignCheckpoint | None:
    """Load CampaignCheckpoint JSON if present, returning None if absent or raising ValueError on corrupt JSON."""
    p = Path(path)
    if not p.is_file():
        return None
    try:
        raw = p.read_text(encoding="utf-8")
        data = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"Corrupt campaign checkpoint JSON in '{p}': {exc}") from exc

    if not isinstance(data, dict):
        raise ValueError(f"Corrupt campaign checkpoint in '{p}': expected JSON object")

    required = ("campaign_name", "completed_slices", "failed_slices", "rounds_used", "max_rounds")
    missing = [k for k in required if k not in data]
    if missing:
        raise ValueError(f"Corrupt campaign checkpoint in '{p}': missing keys {missing}")

    campaign_name = data["campaign_name"]
    completed = data["completed_slices"]
    failed = data["failed_slices"]
    rounds_used = data["rounds_used"]
    max_rounds = data["max_rounds"]
    if (
        not isinstance(campaign_name, str)
        or not isinstance(completed, dict)
        or not isinstance(failed, dict)
        or isinstance(rounds_used, bool)
        or not isinstance(rounds_used, int)
        or isinstance(max_rounds, bool)
        or not isinstance(max_rounds, int)
    ):
        raise ValueError(f"Corrupt campaign checkpoint in '{p}': invalid field types")

    return CampaignCheckpoint(
        campaign_name=campaign_name,
        completed_slices={str(k): str(v) for k, v in completed.items()},
        failed_slices={str(k): str(v) for k, v in failed.items()},
        rounds_used=rounds_used,
        max_rounds=max_rounds,
    )


def _restore_slice_snapshots(snapshots: list[tuple[Path, bytes | None]]) -> None:
    for path, prev_bytes in reversed(snapshots):
        if prev_bytes is None:
            if path.is_file() or path.is_symlink():
                path.unlink()
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(prefix=".rb_", dir=str(path.parent))
            try:
                with os.fdopen(fd, "wb") as fh:
                    fh.write(prev_bytes)
                os.replace(tmp_name, path)
            except Exception:
                if os.path.exists(tmp_name):
                    os.unlink(tmp_name)
                raise


def execute_slice_transaction(
    repo_root: Path,
    node: SliceNode,
    apply_fn: Callable[[], None],
    verify_fn: Callable[[], tuple[bool, str]],
    checkpoint: CampaignCheckpoint,
) -> tuple[bool, str]:
    """Execute a slice atomically with RAM pre-image rollback and bounded max_rounds enforcement."""
    if checkpoint.rounds_used >= checkpoint.max_rounds:
        return (False, "HALT_MAX_ROUNDS: bounded execution limit reached")

    root = Path(repo_root).resolve()
    snapshots: list[tuple[Path, bytes | None]] = []
    seen: set[Path] = set()
    for raw_path in node.target_paths:
        p = Path(raw_path)
        resolved = p.resolve() if p.is_absolute() else (root / p).resolve()
        if resolved != root and not resolved.is_relative_to(root):
            raise ValueError(f"target_path '{raw_path}' escapes repo_root '{root}'")
        if resolved in seen:
            continue
        seen.add(resolved)
        snapshots.append((resolved, resolved.read_bytes() if resolved.is_file() else None))

    ok = False
    detail = ""
    try:
        apply_fn()
        ok, detail = verify_fn()
    except Exception as exc:
        ok = False
        detail = f"{type(exc).__name__}: {exc}"

    if ok is True:
        checkpoint.rounds_used += 1
        checkpoint.completed_slices[node.id] = compute_slice_input_sha256(node, root)
        checkpoint.failed_slices.pop(node.id, None)
        return (True, detail)

    _restore_slice_snapshots(snapshots)
    checkpoint.rounds_used += 1
    checkpoint.completed_slices.pop(node.id, None)
    error_hash = hashlib.sha256(detail.encode("utf-8")).hexdigest()[:16]
    checkpoint.failed_slices[node.id] = error_hash
    return (False, f"ROLLED_BACK: {detail}")
