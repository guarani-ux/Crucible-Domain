#!/usr/bin/env python3
"""Cross-platform parallel verifier for Crucible Domain and attached spokes."""

from __future__ import annotations

import argparse
import concurrent.futures
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any


def resolve_spokes_root(root: Path, spokes_root_arg: str | None = None) -> Path:
    """Resolve external spokes root via CLI arg, env var, or sibling directory."""
    if spokes_root_arg:
        return Path(spokes_root_arg).expanduser().resolve()
    env_val = os.environ.get("CRUCIBLE_SPOKES_ROOT", "").strip()
    if env_val:
        return Path(env_val).expanduser().resolve()
    return root.resolve().parent / "crucible-spokes"


def resolve_story_lane_dir(root: Path, spokes_root_arg: str | None = None) -> Path:
    """Resolve the story-lane spoke directory beneath spokes_root."""
    return resolve_spokes_root(root, spokes_root_arg) / "story-lane"


def _load_ranked_tests(root: Path) -> tuple[list[Path], set[str], dict[str, Any], str, Any | None]:
    scripts_dir = root / ".agents" / "scripts"
    tests_dir = scripts_dir / "tests"
    if str(scripts_dir) not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    try:
        import ram_ml_engine

        ml_rank = ram_ml_engine.rank_tests_for_changes(root)
        test_files = [root / r["test_path"] for r in ml_rank["ranked_tests"]]
        impacted_set = {
            r["test_path"] for r in ml_rank["ranked_tests"] if r.get("tier") == "impacted"
        }
        note = (
            f"ML test-ranker: {ml_rank['impacted_count']}/{len(test_files)} impacted "
            f"({ml_rank['elapsed_ms']}ms, source={ml_rank['change_source']})"
        )
        return test_files, impacted_set, ml_rank, note, ram_ml_engine
    except (ImportError, OSError, ValueError, RuntimeError) as exc:
        print(f"[WARN] verify_all: ML test-ranker unavailable ({exc}); falling back to sorted glob", file=sys.stderr)
        test_files = sorted(tests_dir.glob("test_*.py")) if tests_dir.is_dir() else []
        return test_files, set(), {}, "ML test-ranker: fallback alphabetical", None


def _run_step(item: tuple[str, Path, list[str]]) -> tuple[str, int, float, str, str]:
    name, cwd, cmd = item
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            cmd,
            cwd=cwd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=120,
            check=False,
        )
        status = "PASS" if proc.returncode == 0 else "FAIL"
        out = (proc.stdout + proc.stderr).strip()
        return name, proc.returncode, time.perf_counter() - t0, status, out
    except subprocess.TimeoutExpired as exc:
        return name, 124, time.perf_counter() - t0, "FAIL", f"TIMEOUT after 120s: {exc}"
    except (OSError, subprocess.SubprocessError) as exc:
        return name, 1, time.perf_counter() - t0, "FAIL", f"EXECUTION ERROR: {exc}"


def build_parser() -> argparse.ArgumentParser:
    default_root = Path(__file__).resolve().parents[2]
    parser = argparse.ArgumentParser(description="Cross-platform parallel verifier for Crucible Domain.")
    parser.add_argument("--root", default=str(default_root), help="Repository root path.")
    parser.add_argument("--ci", action="store_true", help="Portable CI mode (skip ML history writes and optional absent spokes).")
    parser.add_argument("--require-spokes", action="store_true", help="Fail if external spoke directories are missing.")
    parser.add_argument("--spokes-root", default=None, help="Override CRUCIBLE_SPOKES_ROOT directory.")
    parser.add_argument("--skip-mutations", action="store_true", help="Skip mutation_gate.py step.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.root).resolve()

    test_files, impacted_set, ml_rank, ml_note, ram_ml_engine = _load_ranked_tests(root)

    doctor_cmd = [sys.executable, ".agents/scripts/crucible_gate.py", "doctor"]
    if args.ci:
        doctor_cmd.append("--no-global")

    steps: list[tuple[str, Path, list[str]]] = [
        ("Hub Gate (--strict)", root, [sys.executable, ".agents/scripts/crucible_gate.py", "check", "--strict"]),
        ("Hub Doctor", root, doctor_cmd),
    ]
    if not args.skip_mutations:
        steps.append(("Mutation Kill Gate", root, [sys.executable, ".agents/scripts/mutation_gate.py"]))

    preset_results: list[tuple[str, int, float, str, str]] = []
    story_lane_dir = resolve_story_lane_dir(root, args.spokes_root)
    if story_lane_dir.is_dir():
        steps.append(
            (
                "Story-Lane Pytest",
                story_lane_dir,
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    "tests/test_storylane_spoke_mcp.py",
                    "tests/test_storylane_fuzz_and_replay.py",
                    "-q",
                ],
            )
        )
    elif args.require_spokes:
        preset_results.append(
            ("Story-Lane Pytest", 1, 0.0, "FAIL", f"Required spoke missing: {story_lane_dir}")
        )
    else:
        preset_results.append(
            ("Story-Lane Pytest", 0, 0.0, "SKIP", f"SKIPPED_OPTIONAL_SPOKE: {story_lane_dir}")
        )

    for test_file in test_files:
        rel_test = test_file.relative_to(root).as_posix() if test_file.is_relative_to(root) else test_file.name
        star = "*" if rel_test in impacted_set else ""
        steps.append(
            (f"Pytest:{test_file.stem}{star}", root, [sys.executable, "-m", "pytest", str(test_file), "-q"])
        )

    t_all = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, len(steps))) as pool:
        exec_results = list(pool.map(_run_step, steps))
    wall = time.perf_counter() - t_all

    results = exec_results[:2]
    idx = 2
    if not args.skip_mutations:
        results.append(exec_results[idx])
        idx += 1
    if story_lane_dir.is_dir():
        results.append(exec_results[idx])
        idx += 1
    else:
        results.extend(preset_results)
    results.extend(exec_results[idx:])

    failed = 0
    print("\n=== Crucible Terminal Verification Summary (Parallel) ===")
    print(ml_note)
    print(f"{'Check':<34} {'Status':<8} {'Seconds':>7}")
    print(f"{'-'*34} {'-'*8} {'-'*7}")
    for name, rc, secs, status, out in results:
        print(f"{name:<34} {status:<8} {secs:>7.2f}")
        if status == "SKIP" and out:
            print(f"  -> {out}")
        if rc != 0:
            failed += 1
            print(f"\n--- FAILED: {name} (exit {rc}) ---\n{out}\n")

    print(f"\nWall-clock: {wall:.2f}s ({len(results)} parallel checks)")

    if not args.ci and ram_ml_engine is not None:
        try:
            ram_ml_engine.record_verify_outcomes(
                root,
                ml_rank.get("changed_files", []),
                [(name, rc) for name, rc, _, _, _ in results],
            )
        except (ImportError, OSError, ValueError, RuntimeError) as exc:
            print(f"[WARN] verify_all: failed to record ML outcomes ({exc})", file=sys.stderr)

    if failed:
        print(f"RESULT: {failed} check(s) FAILED")
        return 1
    print(f"RESULT: ALL {len(results)} CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
