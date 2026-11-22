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
CONTEXT_DIRS = ("Knowledge", "Project")
GROUND_TRUTH_FILES = {"GROUND_TRUTH.MD", "INTAKE.MD", "BASELINE.MD"}
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


def _extract_active_wip(ideas_path: Path) -> str:
    """Extract Stage 4 active bullets from IDEAS.md in memory."""
    if not ideas_path.is_file():
        return "missing"
    in_active = False
    bullets: list[str] = []
    for line in ideas_path.read_text(encoding="utf-8", errors="replace").splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            if in_active:
                break
            if stripped.startswith("## Stage 4: Active"):
                in_active = True
            continue
        if in_active and stripped.startswith("- "):
            bullets.append(stripped)
    return " ; ".join(bullets) if bullets else "none"


def _check_local_install_and_plugins() -> str:
    """Check core governance files and plugin manifests in local memory."""
    root_checks = [
        ("IDEAS.md", ROOT / "IDEAS.md"),
        ("AGENTS.md", ROOT / "AGENTS.md"),
        ("acceptance.lock.json", ROOT / ".agents" / "acceptance.lock.json"),
    ]
    present = [label for label, path in root_checks if path.is_file()]
    missing = [label for label, path in root_checks if not path.is_file()]
    root_status = f"root=[{', '.join(present)}]"
    if missing:
        root_status += f" missing=[{', '.join(missing)}]"

    ig_manifest = ROOT / ".agents" / "plugins" / "inner-gravity" / "plugin.json"
    plugin_status = "plugins=[inner-gravity:ok]" if ig_manifest.is_file() else "plugins=[inner-gravity:missing]"
    return f"{root_status} | {plugin_status}"


def _format_domain_count(count: int) -> str:
    return "0 [EMPTY — INTAKE REQUIRED]" if count == 0 else str(count)


def _build_system_map() -> str:
    """Assemble the Turn-0 workspace RAM snapshot."""
    domain_counts = {name: _count_files(ROOT / name) for name in COUNT_DIRS}
    context_counts = {name: _count_files(ROOT / name) for name in CONTEXT_DIRS}
    active_locks = [name for name in LOCK_DIRS if (ROOT / name).exists()]
    lock_status = ",".join(active_locks) if active_locks else "none"

    rc_status, status_out = _git_output(["status", "--porcelain"])
    dirty_count = len([line for line in status_out.splitlines() if line.strip()]) if rc_status == 0 else -1

    rc_head, head_out = _git_output(["log", "-n", "1", "--oneline"])
    git_head = head_out.strip() if rc_head == 0 and head_out.strip() else "unknown"

    active_wip = _extract_active_wip(ROOT / "IDEAS.md")
    install_status = _check_local_install_and_plugins()

    return "\n".join(
        [
            (
                f"Domain outputs — CPL: {_format_domain_count(domain_counts['Calgary Public Library'])} | "
                f"Personal: {_format_domain_count(domain_counts['Personal Work'])} | "
                f"Graphs: {_format_domain_count(domain_counts['Graphs'])}"
            ),
            (
                f"Context dirs — Knowledge: {context_counts['Knowledge']} | "
                f"Project: {context_counts['Project']}"
            ),
            f"Git HEAD: {git_head} | Dirty: {dirty_count} | Sync locks: {lock_status}",
            f"Active WIP: {active_wip}",
            install_status,
            "SHIFTING_SAND: Establish ground truth (workflow, audience, purpose) before proposing deliverables in any [EMPTY — INTAKE REQUIRED] folder.",
            'Gate check: python ".agents/scripts/crucible_gate.py" check',
            'Sync check: python "Project/Inner Gravity/check_sync.py"',
        ]
    )


def cmd_session_start() -> int:
    system_map = _build_system_map()
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


def _extract_target_path(args: dict[str, object]) -> Path | None:
    for key in ("Path", "TargetFile", "file_path", "path", "AbsolutePath"):
        val = args.get(key)
        if isinstance(val, str) and val.strip():
            candidate = Path(val.strip())
            if not candidate.is_absolute():
                candidate = ROOT / candidate
            return candidate.resolve()
    return None


def cmd_pre_tool() -> int:
    payload = _read_stdin_json()
    tool_call = payload.get("toolCall")
    if not isinstance(tool_call, dict):
        print(json.dumps({"decision": "allow"}))
        return 0

    if tool_call.get("name") not in ("write_file", "edit_file"):
        print(json.dumps({"decision": "allow"}))
        return 0

    args = tool_call.get("args")
    if not isinstance(args, dict):
        print(json.dumps({"decision": "allow"}))
        return 0

    target = _extract_target_path(args)
    if target is None:
        print(json.dumps({"decision": "allow"}))
        return 0

    root_resolved = ROOT.resolve()
    try:
        rel_parts = target.relative_to(root_resolved).parts
    except ValueError:
        print(json.dumps({"decision": "allow"}))
        return 0

    if not rel_parts:
        print(json.dumps({"decision": "allow"}))
        return 0

    top_dir_lower = rel_parts[0].lower()
    matched_domain = next((d for d in COUNT_DIRS if d.lower() == top_dir_lower), None)
    if matched_domain is None:
        print(json.dumps({"decision": "allow"}))
        return 0

    if _count_files(ROOT / matched_domain) == 0 and target.name.upper() not in GROUND_TRUTH_FILES:
        print(
            json.dumps(
                {
                    "decision": "deny",
                    "reason": (
                        f"SHIFTING_SAND: '{matched_domain}/' has 0 files. "
                        "Establish ground truth (GROUND_TRUTH.md, INTAKE.md, or BASELINE.md) "
                        "covering existing workflow, audience, and purpose before creating deliverables."
                    ),
                },
                ensure_ascii=False,
            )
        )
        return 0

    print(json.dumps({"decision": "allow"}))
    return 0


def cmd_check() -> int:
    print(_build_system_map())
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
        choices=("session-start", "pre-tool", "check", "pre-commit"),
        help="Gate action to execute.",
    )
    args = parser.parse_args(argv)

    if args.subcommand == "session-start":
        return cmd_session_start()
    if args.subcommand == "pre-tool":
        return cmd_pre_tool()
    return cmd_check()


if __name__ == "__main__":
    raise SystemExit(main())
