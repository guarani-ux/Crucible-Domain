"""Tests for SAT/SMT Wave Constraint Solver (Slice #9)."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from crucible.campaign_ir import PlannedSlice, SliceNode
from crucible.solver import (
    FeasibilityReport,
    ScheduleConstraintError,
    assert_wave_feasibility,
    solve_wave_feasibility,
)


def test_valid_disjoint_same_domain_waves() -> None:
    waves = [
        ["s1", "s2"],
        ["s3", "s4"],
    ]
    target_paths = {
        "s1": ["Personal Work/alpha/a.py", "Personal Work/alpha/b.py"],
        "s2": ["Personal Work/beta/c.py"],
        # Wave 1 is sequential after Wave 0, so touching s1's paths in a later wave is valid
        "s3": ["Personal Work/alpha/a.py"],
        "s4": ["Calgary Public Library/notes.md"],
    }
    domains = {
        "s1": "Personal Work",
        "s2": "Personal Work",
        "s3": "Personal Work",
        "s4": "Personal Work",
    }

    report = assert_wave_feasibility(
        waves=waves,
        target_paths_by_slice=target_paths,
        authority_holds=None,
        domain_by_slice=domains,
    )
    assert isinstance(report, FeasibilityReport)
    assert report.satisfiable is True
    assert report.conflicts == []
    assert report.solver_backend == "z3"


def test_sibling_prefix_paths_and_sequential_cross_domain_waves_are_valid() -> None:
    # Sibling prefix trap: "src/app" vs "src/app_v2" must NOT trigger parent/child overlap.
    # Also, different domains across *different* sequential waves are allowed.
    waves = [
        [
            PlannedSlice(node=SliceNode(id="s1", target_paths=["src/app/main.py"]), computed_sha256="x", status="RUN"),
            PlannedSlice(node=SliceNode(id="s2", target_paths=["src/app_v2/main.py"]), computed_sha256="y", status="RUN"),
        ],
        [
            PlannedSlice(node=SliceNode(id="s3", target_paths=["Calgary Public Library/brief.md"]), computed_sha256="z", status="RUN"),
        ],
    ]
    domains = {
        "s1": "Personal Work",
        "s2": "Personal Work",
        "s3": "Calgary Public Library",
    }

    report = solve_wave_feasibility(
        waves=waves,
        target_paths_by_slice={},
        domain_by_slice=domains,
    )
    assert report.satisfiable is True
    assert report.conflicts == []


def test_negative_overlapping_exact_and_normalized_paths() -> None:
    waves = [["s1", "s2"]]
    target_paths = {
        "s1": ["./.agents/scripts/crucible/solver.py"],
        "s2": [".agents\\scripts\\crucible\\sub\\..\\solver.py"],
    }

    report = solve_wave_feasibility(waves=waves, target_paths_by_slice=target_paths)
    assert report.satisfiable is False
    assert len(report.conflicts) == 1
    assert "overlapping target_paths" in report.conflicts[0]
    assert "s1" in report.conflicts[0] and "s2" in report.conflicts[0]

    with pytest.raises(ScheduleConstraintError) as exc_info:
        assert_wave_feasibility(waves=waves, target_paths_by_slice=target_paths)
    assert exc_info.value.conflicts == report.conflicts


def test_negative_parent_child_path_overlap() -> None:
    waves = [["parent_slice", "child_slice"]]
    target_paths = {
        "parent_slice": ["Personal Work/docs/"],
        "child_slice": ["Personal Work/docs/architecture/spec.md"],
    }

    with pytest.raises(ScheduleConstraintError) as exc_info:
        assert_wave_feasibility(
            waves=waves,
            target_paths_by_slice=target_paths,
            domain_by_slice={"parent_slice": "Personal Work", "child_slice": "Personal Work"},
        )
    joined = " | ".join(exc_info.value.conflicts)
    assert "overlapping target_paths" in joined
    assert "parent_slice" in joined and "child_slice" in joined


def test_negative_cross_domain_parallel_wave() -> None:
    waves = [["cpl_slice", "personal_slice"]]
    target_paths = {
        "cpl_slice": ["Calgary Public Library/campaign.md"],
        "personal_slice": ["Personal Work/campaign.md"],
    }
    domains = {
        "cpl_slice": "Calgary Public Library",
        "personal_slice": "Personal Work",
    }

    report = solve_wave_feasibility(
        waves=waves,
        target_paths_by_slice=target_paths,
        domain_by_slice=domains,
    )
    assert report.satisfiable is False
    assert any("cross-domain" in c for c in report.conflicts)

    with pytest.raises(ScheduleConstraintError) as exc_info:
        assert_wave_feasibility(
            waves=waves,
            target_paths_by_slice=target_paths,
            domain_by_slice=domains,
        )
    assert any("Calgary Public Library" in c and "Personal Work" in c for c in exc_info.value.conflicts)


def test_negative_authority_holds_set_and_mapping() -> None:
    waves = [["s1"], ["s2"]]
    target_paths = {
        "s1": ["Personal Work/a.md"],
        "s2": ["Personal Work/b.md"],
    }

    report_set = solve_wave_feasibility(
        waves=waves,
        target_paths_by_slice=target_paths,
        authority_holds={"s2"},
    )
    assert report_set.satisfiable is False
    assert any("authority hold" in c and "s2" in c for c in report_set.conflicts)

    with pytest.raises(ScheduleConstraintError) as exc_info:
        assert_wave_feasibility(
            waves=waves,
            target_paths_by_slice=target_paths,
            authority_holds={"s1": False, "s2": "Tier 2 sign-off required"},
        )
    assert any("Tier 2 sign-off required" in c for c in exc_info.value.conflicts)


def test_negative_multiple_simultaneous_constraints_reported() -> None:
    waves = [["s1", "s2", "s3"]]
    target_paths = {
        "s1": ["Personal Work/shared"],
        "s2": ["Personal Work/shared/file.py"],
        "s3": ["Personal Work/other.py"],
    }
    domains = {
        "s1": "Personal Work",
        "s2": "Calgary Public Library",
        "s3": "Personal Work",
    }

    report = solve_wave_feasibility(
        waves=waves,
        target_paths_by_slice=target_paths,
        authority_holds={"s3": "owner review pending"},
        domain_by_slice=domains,
    )
    assert report.satisfiable is False
    assert len(report.conflicts) == 4
    joined = " | ".join(report.conflicts)
    assert "overlapping target_paths" in joined
    assert "cross-domain" in joined
    assert "authority hold" in joined
