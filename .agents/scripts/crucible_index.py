#!/usr/bin/env python3
"""In-RAM capability index, selective router, and closed-loop doctor for Crucible Domain."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPTS_DIR = str(Path(__file__).resolve().parent)
if _SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _SCRIPTS_DIR)

from crucible.doctor import _format_doctor_text, run_doctor  # noqa: E402
from crucible.forge import _format_forge_text, _load_primitives_meta, forge_brief  # noqa: E402
from crucible.indexer import build_index, validate_primitives_registry  # noqa: E402
from crucible.models import (  # noqa: E402
    DEFAULT_GLOBAL_CONFIG_DIR,
    FORGE_DOMAINS,
    MAX_README_EXCERPT_CHARS,
    DiagnosticFinding,
)
from crucible.router import _format_route_text, route_query  # noqa: E402
from crucible.sieve import (  # noqa: E402
    _format_melt_diff_text,
    _format_melt_scan_text,
    analyze_repo_tree_payload,
    compute_melt_diff,
    fetch_github_repos,
    run_melt_scan,
)

__all__ = [
    "DEFAULT_GLOBAL_CONFIG_DIR",
    "DiagnosticFinding",
    "FORGE_DOMAINS",
    "MAX_README_EXCERPT_CHARS",
    "_format_doctor_text",
    "_format_forge_text",
    "_format_melt_diff_text",
    "_format_melt_scan_text",
    "_format_route_text",
    "_load_primitives_meta",
    "analyze_repo_tree_payload",
    "build_index",
    "compute_melt_diff",
    "fetch_github_repos",
    "forge_brief",
    "main",
    "route_query",
    "run_doctor",
    "run_melt_scan",
    "validate_primitives_registry",
]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Crucible Domain in-RAM index, router, forge, and doctor.")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_route = sub.add_parser("route", help="Resolve an ID or task query to local capabilities in RAM.")
    p_route.add_argument("query", nargs="+")
    p_route.add_argument("--top", type=int, default=5)
    p_route.add_argument("--json", action="store_true")
    p_route.add_argument("--no-global", action="store_true")

    p_forge = sub.add_parser("forge", help="Synthesize prior systems, breakpoints, lessons, and test requirements in RAM.")
    p_forge.add_argument("problem", nargs="+")
    p_forge.add_argument("--top", type=int, default=4)
    p_forge.add_argument("--json", action="store_true")
    p_forge.add_argument("--no-global", action="store_true")
    p_forge.add_argument("--domain", choices=FORGE_DOMAINS, default=None)

    p_doc = sub.add_parser("doctor", help="Audit hooks, bindings, links, duplicates, and storage.")
    p_doc.add_argument("--json", action="store_true")
    p_doc.add_argument("--no-global", action="store_true")
    p_doc.add_argument("--skip-exec", action="store_true")

    args = parser.parse_args(argv)
    global_dir = None if args.no_global else DEFAULT_GLOBAL_CONFIG_DIR

    if args.cmd == "route":
        idx = build_index(args.root, global_config_dir=global_dir)
        res = route_query(idx, " ".join(args.query), top_k=args.top)
        print(json.dumps(res.to_dict(), indent=2, ensure_ascii=False) if args.json else _format_route_text(res))
        return 0

    if args.cmd == "forge":
        idx = build_index(args.root, global_config_dir=global_dir)
        brief = forge_brief(idx, " ".join(args.problem), top_k=args.top, domain=args.domain)
        print(json.dumps(brief.to_dict(), indent=2, ensure_ascii=False) if args.json else _format_forge_text(brief))
        return 0

    report = run_doctor(args.root, global_config_dir=global_dir, execute_hooks=not args.skip_exec)
    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False) if args.json else _format_doctor_text(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
