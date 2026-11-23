"""Modular RAM capability index, router, forge, doctor, and repo sieve package."""

from __future__ import annotations

from .doctor import run_doctor
from .forge import forge_brief
from .indexer import build_index, validate_primitives_registry
from .ledger import (
    assess_risk,
    capability_posterior_multiplier,
    load_ledger,
    record_outcome,
    validate_ledger,
)
from .router import route_query
from .sieve import compute_melt_diff, fetch_github_repos, run_melt_scan

__all__ = [
    "assess_risk",
    "build_index",
    "capability_posterior_multiplier",
    "compute_melt_diff",
    "fetch_github_repos",
    "forge_brief",
    "load_ledger",
    "record_outcome",
    "route_query",
    "run_doctor",
    "run_melt_scan",
    "validate_ledger",
    "validate_primitives_registry",
]
