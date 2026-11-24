"""Modular RAM capability index, router, and doctor kernel package."""

from __future__ import annotations

from .doctor import run_doctor
from .indexer import build_index, validate_primitives_registry
from .router import route_query

__all__ = [
    "build_index",
    "route_query",
    "run_doctor",
    "validate_primitives_registry",
]
