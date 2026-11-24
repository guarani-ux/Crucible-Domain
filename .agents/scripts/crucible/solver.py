"""SAT/SMT Wave Constraint Solver for parallel Campaign IR execution waves (Slice #9)."""

from __future__ import annotations

import posixpath
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Any

try:
    import z3
except ImportError:  # pragma: no cover - fallback when z3-solver is absent
    z3 = None  # type: ignore[assignment]


class ScheduleConstraintError(ValueError):
    """Raised when wave schedule constraints cannot be satisfied before worker dispatch."""

    def __init__(self, conflicts: list[str]) -> None:
        self.conflicts = list(conflicts)
        super().__init__("; ".join(self.conflicts))


@dataclass(frozen=True)
class FeasibilityReport:
    """Result of SAT/SMT wave schedule feasibility checking."""

    satisfiable: bool
    conflicts: list[str] = field(default_factory=list)
    solver_backend: str = "z3"
    unsat_core: list[str] = field(default_factory=list)


def _extract_slice_id(item: Any) -> str:
    if isinstance(item, str):
        return item
    if hasattr(item, "node") and hasattr(item.node, "id"):
        return str(item.node.id)
    if hasattr(item, "id"):
        return str(item.id)
    if isinstance(item, Mapping) and "id" in item:
        return str(item["id"])
    raise TypeError(f"Unsupported wave slice entry: {item!r}")


def _normalize_path(raw: str | Path) -> PurePosixPath | None:
    text = str(raw).strip().replace("\\", "/")
    if not text:
        return None
    norm = posixpath.normpath(text)
    return PurePosixPath(norm)


def _paths_overlap(a: PurePosixPath, b: PurePosixPath) -> bool:
    return a == b or a.is_relative_to(b) or b.is_relative_to(a)


def _extract_target_paths(
    item: Any,
    sid: str,
    target_paths_by_slice: Mapping[str, Iterable[str | Path]],
) -> list[PurePosixPath]:
    if sid in target_paths_by_slice:
        raw_paths = target_paths_by_slice[sid]
    elif hasattr(item, "node") and hasattr(item.node, "target_paths"):
        raw_paths = item.node.target_paths
    elif hasattr(item, "target_paths"):
        raw_paths = item.target_paths
    else:
        raw_paths = ()

    normalized: list[PurePosixPath] = []
    for raw in raw_paths:
        p = _normalize_path(raw)
        if p is not None and p not in normalized:
            normalized.append(p)
    return normalized


def _normalize_authority_holds(
    authority_holds: Mapping[str, Any] | Iterable[str] | str | None,
) -> dict[str, str]:
    if authority_holds is None:
        return {}
    if isinstance(authority_holds, Mapping):
        holds: dict[str, str] = {}
        for k, v in authority_holds.items():
            if not v:
                continue
            reason = str(v).strip() if isinstance(v, str) and v.strip() else "authority hold active"
            holds[str(k)] = reason
        return holds
    if isinstance(authority_holds, str):
        return {authority_holds: "authority hold active"} if authority_holds.strip() else {}
    return {str(k): "authority hold active" for k in authority_holds if str(k).strip()}


def _normalize_domains(domain_by_slice: Mapping[str, str | None] | None) -> dict[str, str]:
    if domain_by_slice is None:
        return {}
    domains: dict[str, str] = {}
    for k, v in domain_by_slice.items():
        if v is None:
            continue
        cleaned = str(v).strip()
        if cleaned:
            domains[str(k)] = cleaned
    return domains


def solve_wave_feasibility(
    waves: Sequence[Sequence[Any]],
    target_paths_by_slice: Mapping[str, Iterable[str | Path]] | None,
    authority_holds: Mapping[str, Any] | Iterable[str] | str | None = None,
    domain_by_slice: Mapping[str, str | None] | None = None,
) -> FeasibilityReport:
    """Verify disjoint target_paths, single-domain isolation per wave, and authority holds.

    Encodes wave assignments and pairwise/unary exclusion constraints in Z3 (when installed)
    and returns a FeasibilityReport with satisfiability and human-readable conflict diagnostics.
    """
    paths_map = target_paths_by_slice or {}
    holds = _normalize_authority_holds(authority_holds)
    domains = _normalize_domains(domain_by_slice)

    conflicts: list[str] = []
    solver = z3.Solver() if z3 is not None else None

    for wave_idx, wave in enumerate(waves):
        entries = list(wave)
        wave_vars: list[Any] = []
        wave_sids: list[str] = []
        wave_paths: list[list[PurePosixPath]] = []

        for slot_idx, entry in enumerate(entries):
            sid = _extract_slice_id(entry)
            wave_sids.append(sid)
            wave_paths.append(_extract_target_paths(entry, sid, paths_map))

            var = z3.Bool(f"run_w{wave_idx}_i{slot_idx}_{sid}") if solver is not None else None
            wave_vars.append(var)
            if solver is not None:
                solver.assert_and_track(var, f"schedule:wave={wave_idx}:slot={slot_idx}:{sid}")

            if sid in holds:
                conflicts.append(
                    f"Wave {wave_idx}: slice '{sid}' blocked by authority hold ({holds[sid]})"
                )
                if solver is not None:
                    solver.assert_and_track(
                        z3.Not(var),
                        f"authority_hold:wave={wave_idx}:slot={slot_idx}:{sid}",
                    )

        for i in range(len(entries)):
            sid_i = wave_sids[i]
            for j in range(i + 1, len(entries)):
                sid_j = wave_sids[j]

                if sid_i == sid_j:
                    conflicts.append(
                        f"Wave {wave_idx}: duplicate slice '{sid_i}' scheduled in parallel"
                    )
                    if solver is not None:
                        solver.assert_and_track(
                            z3.Not(z3.And(wave_vars[i], wave_vars[j])),
                            f"duplicate:wave={wave_idx}:{i}<->{j}:{sid_i}",
                        )
                    continue

                overlaps = [
                    (str(p_i), str(p_j))
                    for p_i in wave_paths[i]
                    for p_j in wave_paths[j]
                    if _paths_overlap(p_i, p_j)
                ]
                if overlaps:
                    pair_desc = ", ".join(f"{a} <-> {b}" for a, b in overlaps)
                    conflicts.append(
                        f"Wave {wave_idx}: overlapping target_paths between '{sid_i}' and '{sid_j}' ({pair_desc})"
                    )
                    if solver is not None:
                        solver.assert_and_track(
                            z3.Not(z3.And(wave_vars[i], wave_vars[j])),
                            f"path_overlap:wave={wave_idx}:{sid_i}<->{sid_j}",
                        )

                dom_i = domains.get(sid_i)
                dom_j = domains.get(sid_j)
                if dom_i and dom_j and dom_i != dom_j:
                    conflicts.append(
                        f"Wave {wave_idx}: cross-domain parallel execution between "
                        f"'{sid_i}' (domain='{dom_i}') and '{sid_j}' (domain='{dom_j}')"
                    )
                    if solver is not None:
                        solver.assert_and_track(
                            z3.Not(z3.And(wave_vars[i], wave_vars[j])),
                            f"domain_isolation:wave={wave_idx}:{sid_i}<->{sid_j}",
                        )

    if solver is not None:
        check_status = solver.check()
        satisfiable = check_status == z3.sat
        unsat_core = [str(c) for c in solver.unsat_core()] if not satisfiable else []
        backend = "z3"
    else:
        satisfiable = len(conflicts) == 0
        unsat_core = []
        backend = "deterministic"

    return FeasibilityReport(
        satisfiable=satisfiable,
        conflicts=conflicts,
        solver_backend=backend,
        unsat_core=unsat_core,
    )


def assert_wave_feasibility(
    waves: Sequence[Sequence[Any]],
    target_paths_by_slice: Mapping[str, Iterable[str | Path]] | None,
    authority_holds: Mapping[str, Any] | Iterable[str] | str | None = None,
    domain_by_slice: Mapping[str, str | None] | None = None,
) -> FeasibilityReport:
    """Assert that the wave schedule is feasible, raising ScheduleConstraintError on conflict."""
    report = solve_wave_feasibility(
        waves=waves,
        target_paths_by_slice=target_paths_by_slice,
        authority_holds=authority_holds,
        domain_by_slice=domain_by_slice,
    )
    if not report.satisfiable:
        raise ScheduleConstraintError(report.conflicts)
    return report
