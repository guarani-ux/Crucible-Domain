"""Modular RAM capability index, router, forge, doctor, and repo sieve package."""

from __future__ import annotations

from .doctor import run_doctor
from .forge import forge_brief
from .indexer import build_index, validate_primitives_registry
from .router import route_query
from .sieve import compute_melt_diff, fetch_github_repos, run_melt_scan

__all__ = [
    "build_index",
    "compute_melt_diff",
    "fetch_github_repos",
    "forge_brief",
    "route_query",
    "run_doctor",
    "run_melt_scan",
    "validate_primitives_registry",
]
