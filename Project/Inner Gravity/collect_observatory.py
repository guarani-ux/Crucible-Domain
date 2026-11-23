#!/usr/bin/env python3
"""Read-only RAM observatory collector for Crucible Domain + Antigravity host state."""

from __future__ import annotations

import argparse
import collections
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = REPO_ROOT / ".agents" / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import crucible_index  # noqa: E402


def _sha256_prefix(path: Path) -> str | None:
    if not path.is_file():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def _git_head(repo: Path) -> str | None:
    if not (repo / ".git").exists():
        return None
    proc = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "--short", "HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    return proc.stdout.strip() if proc.returncode == 0 and proc.stdout.strip() else None


def _collect_session_telemetry(brain_dir: Path, session_id: str | None) -> dict[str, Any]:
    if not brain_dir.is_dir():
        return {"present": False}
    target_dir: Path | None = None
    if session_id:
        cand = brain_dir / session_id
        if cand.is_dir():
            target_dir = cand
    else:
        candidates = sorted(
            (p for p in brain_dir.iterdir() if p.is_dir() and (p / "reliability-events.jsonl").is_file()),
            key=lambda p: p.stat().st_mtime,
            reverse=True,
        )
        if candidates:
            target_dir = candidates[0]
    if target_dir is None:
        return {"present": False}

    rel_file = target_dir / "reliability-events.jsonl"
    tool_counts: collections.Counter[str] = collections.Counter()
    failed_events = 0
    if rel_file.is_file():
        for line in rel_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            ev = json.loads(line)
            tool_counts[str(ev.get("tool") or "unknown")] += 1
            if ev.get("failed"):
                failed_events += 1

    ig_dir = target_dir / "inner-gravity-observations"
    ig_events: collections.Counter[str] = collections.Counter()
    ig_models: collections.Counter[str] = collections.Counter()
    if ig_dir.is_dir():
        for f in ig_dir.glob("*.json"):
            rec = json.loads(f.read_text(encoding="utf-8", errors="replace"))
            ig_events[str(rec.get("event") or "unknown")] += 1
            ig_models[str(rec.get("model") or "unknown")] += 1

    tr_file = target_dir / ".system_generated" / "logs" / "transcript.jsonl"
    step_types: collections.Counter[str] = collections.Counter()
    subagent_calls = 0
    if tr_file.is_file():
        for line in tr_file.read_text(encoding="utf-8", errors="replace").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            step_types[str(row.get("type") or "unknown")] += 1
            for tc in row.get("tool_calls") or []:
                if tc.get("name") == "invoke_subagent":
                    subagent_calls += 1

    return {
        "present": True,
        "session_id": target_dir.name,
        "reliability_events_total": sum(tool_counts.values()),
        "reliability_events_failed": failed_events,
        "tool_counts": dict(tool_counts),
        "ig_observation_events": dict(ig_events),
        "ig_models_seen": dict(ig_models),
        "transcript_steps_total": sum(step_types.values()),
        "transcript_step_types": dict(step_types),
        "subagent_invocations": subagent_calls,
    }


def collect_snapshot(
    root: Path = REPO_ROOT,
    gemini_dir: Path | None = None,
    session_id: str | None = None,
    execute_hooks: bool = False,
) -> dict[str, Any]:
    """Assemble a sanitized, read-only observability snapshot across Crucible and Antigravity."""
    g_root = gemini_dir if gemini_dir is not None else (Path.home() / ".gemini")
    cfg_dir = g_root / "config"
    brain_dir = g_root / "antigravity" / "brain"

    report = crucible_index.run_doctor(
        root,
        global_config_dir=cfg_dir if cfg_dir.is_dir() else None,
        execute_hooks=execute_hooks,
    )

    live_gemini_md = g_root / "GEMINI.md"
    repo_gemini_md = cfg_dir / "GEMINI.global.md"
    live_hooks = cfg_dir / "hooks.json"
    portable_hooks = cfg_dir / "hooks.json.portable"
    hv4_path = cfg_dir / "scripts" / "hook_v4.py"

    skills_json_path = cfg_dir / "skills.json"
    external_skill_roots: list[str] = []
    if skills_json_path.is_file():
        try:
            sdata = json.loads(skills_json_path.read_text(encoding="utf-8"))
            external_skill_roots = [str(e.get("path")) for e in sdata.get("entries", []) if e.get("path")]
        except (OSError, json.JSONDecodeError):
            pass

    weaknesses: list[dict[str, str]] = []
    if hv4_path.is_file() and not (cfg_dir / "scripts" / "tests" / "test_hook_v4.py").is_file():
        weaknesses.append(
            {
                "id": "GAP-HV4-NO-TESTS",
                "component": "hook_v4.py",
                "detail": f"{len(hv4_path.read_text(encoding='utf-8', errors='replace').splitlines())} lines with 0 unit tests.",
            }
        )
    if live_hooks.is_file() and portable_hooks.is_file() and _sha256_prefix(live_hooks) != _sha256_prefix(portable_hooks):
        weaknesses.append(
            {
                "id": "GAP-HOOKS-PORTABILITY",
                "component": "hooks.json",
                "detail": "Live hooks.json differs from hooks.json.portable (contains machine-specific path).",
            }
        )
    if live_gemini_md.is_file() and repo_gemini_md.is_file() and _sha256_prefix(live_gemini_md) != _sha256_prefix(repo_gemini_md):
        weaknesses.append(
            {
                "id": "GAP-GEMINI-DRIFT",
                "component": "GEMINI.md",
                "detail": "Live ~/.gemini/GEMINI.md differs from config/GEMINI.global.md.",
            }
        )
    if any(":" in p or "\\" in p for p in external_skill_roots):
        weaknesses.append(
            {
                "id": "GAP-KAGEYONI-PATH",
                "component": "skills.json",
                "detail": f"External skill root uses OS-specific path: {external_skill_roots}",
            }
        )
    if report.metrics.get("drive_sync_locks"):
        weaknesses.append(
            {
                "id": "GAP-TRIPLE-SYNC",
                "component": "Crucible Domain storage",
                "detail": f"Git repo shares OneDrive/Drive folder with {report.metrics['drive_sync_locks']}.",
            }
        )

    return {
        "crucible_domain": {
            "head": _git_head(root),
            "doctor_summary": {"pass": report.pass_count, "warn": report.warn_count, "fail": report.fail_count},
            "metrics": report.metrics,
        },
        "antigravity_host": {
            "config_head": _git_head(cfg_dir),
            "gemini_md_sha12": _sha256_prefix(live_gemini_md),
            "repo_gemini_md_sha12": _sha256_prefix(repo_gemini_md),
            "hooks_in_sync_with_portable": _sha256_prefix(live_hooks) == _sha256_prefix(portable_hooks),
            "hook_v4_has_unit_tests": (cfg_dir / "scripts" / "tests" / "test_hook_v4.py").is_file(),
            "operator_router_has_unit_tests": (cfg_dir / "scripts" / "tests" / "test_operator_router.py").is_file(),
            "external_skill_roots": external_skill_roots,
        },
        "session_telemetry": _collect_session_telemetry(brain_dir, session_id),
        "known_weaknesses": weaknesses,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Collect read-only Crucible + Antigravity observatory snapshot.")
    parser.add_argument("--root", type=Path, default=REPO_ROOT)
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--exec-hooks", action="store_true")
    args = parser.parse_args(argv)
    snap = collect_snapshot(args.root.resolve(), session_id=args.session_id, execute_hooks=args.exec_hooks)
    print(json.dumps(snap, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
