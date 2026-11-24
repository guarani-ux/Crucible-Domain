"""Campaign IR Compiler Front-End: typed IR, compile-time checks, incremental optimizer, and error-hash circuit breaker."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


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
    for dep in sorted(node.depends_on):
        h.update(dep.encode("utf-8"))
        h.update(b"\x00")

    for raw_path in sorted(node.target_paths):
        p = Path(raw_path)
        resolved = p.resolve() if p.is_absolute() else (root / p).resolve()
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


def load_receipt_cache(cache_path: Path | str) -> dict[str, str]:
    """Load local slice_id -> input_sha256 receipt cache."""
    p = Path(cache_path)
    if not p.is_file():
        return {}
    data = json.loads(p.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        return {}
    return {str(k): str(v) for k, v in data.items()}


def save_receipt_cache(cache_path: Path | str, cache: dict[str, str]) -> None:
    """Atomically persist slice_id -> input_sha256 receipt cache."""
    p = Path(cache_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(dict(sorted(cache.items())), indent=2) + "\n").encode("utf-8")
    fd, tmp_name = tempfile.mkstemp(prefix=".ir_cache_", dir=str(p.parent))
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
        os.replace(tmp_name, p)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


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


def hash_error_output(output: str) -> str:
    """Compute normalized SHA-256 of a failure output for circuit-breaker comparison."""
    normalized = "\n".join(line.rstrip() for line in output.strip().splitlines())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


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
