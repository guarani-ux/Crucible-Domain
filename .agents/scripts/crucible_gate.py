#!/usr/bin/env python3
"""Deterministic local gate and session-start context mapper for Crucible Domain."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COUNT_DIRS = ("Calgary Public Library", "Personal Work", "Graphs")
LOCK_DIRS = (".tmp.drivedownload", ".tmp.driveupload")


def _count_files(directory: Path) -> int:
    if not directory.is_dir():
        return 0
    return sum(1 for item in directory.rglob("*") if item.is_file())


def _git_output(args: list[str]) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    return proc.returncode, proc.stdout


def _read_stdin_json() -> dict[str, object]:
    if sys.stdin.isatty():
        return {}
    raw = sys.stdin.read().strip()
    if not raw:
        return {}
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def cmd_session_start() -> int:
    _read_stdin_json()

    counts = {name: _count_files(ROOT / name) for name in COUNT_DIRS}
    active_locks = [name for name in LOCK_DIRS if (ROOT / name).exists()]
    lock_status = ",".join(active_locks) if active_locks else "none"

    rc, status_out = _git_output(["status", "--porcelain"])
    dirty_count = len([line for line in status_out.splitlines() if line.strip()]) if rc == 0 else -1

    ideas_path = ROOT / "IDEAS.md"
    ideas_lines: list[str] = []
    if ideas_path.is_file():
        for line in ideas_path.read_text(encoding="utf-8", errors="replace").splitlines():
            stripped = line.strip()
            if stripped:
                ideas_lines.append(stripped)
                if len(ideas_lines) == 3:
                    break
    ideas_summary = " | ".join(ideas_lines) if ideas_lines else "missing"

    system_map = "\n".join(
        [
            (
                f"Workspace files — CPL: {counts['Calgary Public Library']} | "
                f"Personal: {counts['Personal Work']} | Graphs: {counts['Graphs']}"
            ),
            f"Sync locks: {lock_status} | Git dirty: {dirty_count}",
            f"IDEAS.md: {ideas_summary}",
            'Gate check: python ".agents/scripts/crucible_gate.py" check',
            'Sync check: python "Project/Inner Gravity/check_sync.py"',
        ]
    )

    payload = {
        "injectSteps": [
            {
                "systemMessage": {
                    "systemMessage": system_map,
                }
            }
        ]
    }
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def _staged_contains_asana(rel_path: str) -> bool:
    proc = subprocess.run(
        ["git", "show", f":{rel_path}"],
        cwd=ROOT,
        capture_output=True,
        check=False,
    )
    if proc.returncode == 0:
        content = proc.stdout.decode("utf-8", errors="replace")
    else:
        target = ROOT / rel_path
        if not target.is_file():
            return False
        content = target.read_text(encoding="utf-8", errors="replace")
    return "app.asana.com" in content.lower()


def cmd_check() -> int:
    reasons: list[str] = []

    if not (ROOT / "IDEAS.md").is_file():
        reasons.append("IDEAS.md missing")

    rc, diff_out = _git_output(["diff", "--cached", "--name-only"])
    if rc != 0:
        reasons.append("git diff --cached failed")
    else:
        staged_files = [line.strip() for line in diff_out.splitlines() if line.strip()]
        for rel_path in staged_files:
            norm = rel_path.replace("\\", "/")
            parts = norm.split("/")
            if any(part.startswith(".tmp.drive") for part in parts):
                reasons.append(f"staged drive temp file: {norm}")
            if norm.startswith("Calgary Public Library/") and _staged_contains_asana(norm):
                reasons.append(f"staged CPL file contains app.asana.com: {norm}")

    if reasons:
        print(f"BLOCKED: {'; '.join(reasons)}")
        return 1

    print("PASS: IDEAS.md present; no staged .tmp.drive* or CPL app.asana.com violations.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Crucible Domain deterministic gate.")
    parser.add_argument(
        "subcommand",
        choices=("session-start", "check", "pre-commit"),
        help="Gate action to execute.",
    )
    args = parser.parse_args(argv)

    if args.subcommand == "session-start":
        return cmd_session_start()
    return cmd_check()


if __name__ == "__main__":
    raise SystemExit(main())
