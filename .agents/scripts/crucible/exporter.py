"""Deterministic JSON capability map exporter for Crucible Domain."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .indexer import build_index
from .models import CapabilityEntry, CapabilityIndex

CAPABILITY_MAP_SCHEMA = "crucible-capability-map/v1"


def _normalize_entry_path(raw_path: str, root: Path) -> str:
    """Convert repo-local absolute paths to repo-relative POSIX paths."""
    normalized = raw_path.replace("\\", "/")
    candidate = Path(normalized)
    if candidate.is_absolute():
        try:
            return candidate.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            return normalized
    return normalized


def _serialize_entry(entry: CapabilityEntry, root: Path) -> dict[str, Any]:
    return {
        "id": entry.id,
        "kind": entry.kind,
        "title": entry.title,
        "path": _normalize_entry_path(entry.path, root),
        "line": entry.line,
        "domain": entry.domain,
        "reachability": entry.reachability,
        "summary": entry.summary,
    }


def build_capability_map(index: CapabilityIndex) -> dict[str, Any]:
    """Build a deterministic capability map dictionary sorted by capability ID."""
    ordered_entries = sorted(index.entries.values(), key=lambda entry: entry.id)
    serialized = [_serialize_entry(entry, index.root) for entry in ordered_entries]

    if index.counts_by_kind:
        counts_source = index.counts_by_kind
    else:
        counts_source = {}
        for entry in ordered_entries:
            counts_source[entry.kind] = counts_source.get(entry.kind, 0) + 1
    counts_by_kind = {kind: counts_source[kind] for kind in sorted(counts_source)}

    return {
        "schema": CAPABILITY_MAP_SCHEMA,
        "total": len(serialized),
        "counts_by_kind": counts_by_kind,
        "entries": serialized,
    }


def write_capability_map(
    root: Path,
    output_path: Path | None = None,
    *,
    global_config_dir: Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    """Build the capability index for root and write deterministic capability_map.json."""
    resolved_root = root.resolve()
    if not resolved_root.is_dir():
        raise FileNotFoundError(f"workspace root does not exist: {resolved_root}")

    index = build_index(resolved_root, global_config_dir=global_config_dir)
    payload = build_capability_map(index)

    target = output_path if output_path is not None else (resolved_root / "Graphs" / "capability_map.json")
    if not target.is_absolute():
        target = resolved_root / target
    target = target.resolve()
    if target.exists() and target.is_dir():
        raise IsADirectoryError(f"output path is a directory: {target}")

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    return target, payload
