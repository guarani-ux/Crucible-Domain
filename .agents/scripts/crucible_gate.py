#!/usr/bin/env python3
"""Deterministic local gate and session-start context mapper for Crucible Domain."""

from __future__ import annotations

import argparse
import json
import py_compile
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
COUNT_DIRS = ("Calgary Public Library", "Personal Work", "Graphs")
CONTEXT_DIRS = ("Knowledge", "Project")
GROUND_TRUTH_FILES = {"GROUND_TRUTH.MD", "INTAKE.MD", "BASELINE.MD"}
LOCK_DIRS = (".tmp.drivedownload", ".tmp.driveupload")
ASANA_URL_RE = re.compile(r"(?:https?://app\.asana\.com\b|app\.asana\.com/\S+)", re.IGNORECASE)


def _count_files(directory: Path) -> int:
    if not directory.is_dir():
        return 0
    return sum(1 for item in directory.rglob("*") if item.is_file())


def _git_output(args: list[str], root: Path = ROOT) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=root,
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


def _check_local_install_and_plugins(root: Path = ROOT) -> str:
    """Check core governance files and plugin manifests in local memory."""
    root_checks = [
        ("IDEAS.md", root / "IDEAS.md"),
        ("AGENTS.md", root / "AGENTS.md"),
        ("acceptance.lock.json", root / ".agents" / "acceptance.lock.json"),
    ]
    present = [label for label, path in root_checks if path.is_file()]
    missing = [label for label, path in root_checks if not path.is_file()]
    root_status = f"root=[{', '.join(present)}]"
    if missing:
        root_status += f" missing=[{', '.join(missing)}]"

    ig_manifest = root / ".agents" / "plugins" / "inner-gravity" / "plugin.json"
    plugin_status = "plugins=[inner-gravity:ok]" if ig_manifest.is_file() else "plugins=[inner-gravity:missing]"
    return f"{root_status} | {plugin_status}"


def _format_domain_count(count: int) -> str:
    return "0 [EMPTY — INTAKE REQUIRED]" if count == 0 else str(count)


def _build_system_map(root: Path = ROOT) -> str:
    """Assemble the Turn-0 workspace RAM snapshot."""
    domain_counts = {name: _count_files(root / name) for name in COUNT_DIRS}
    context_counts = {name: _count_files(root / name) for name in CONTEXT_DIRS}
    active_locks = [name for name in LOCK_DIRS if (root / name).exists()]
    lock_status = ",".join(active_locks) if active_locks else "none"

    rc_status, status_out = _git_output(["status", "--porcelain"], root)
    dirty_count = len([line for line in status_out.splitlines() if line.strip()]) if rc_status == 0 else -1

    rc_head, head_out = _git_output(["log", "-n", "1", "--oneline"], root)
    git_head = head_out.strip() if rc_head == 0 and head_out.strip() else "unknown"

    active_wip = _extract_active_wip(root / "IDEAS.md")
    install_status = _check_local_install_and_plugins(root)

    cap_line = 'Route/Forge: python ".agents/scripts/crucible_gate.py" route|forge "<task or problem>" | Health: doctor'
    try:
        ci = _resolve_index_module()
        global_dir = ci.DEFAULT_GLOBAL_CONFIG_DIR if ci.DEFAULT_GLOBAL_CONFIG_DIR.is_dir() else None
        idx = ci.build_index(root, global_config_dir=global_dir)
        counts = idx.counts_by_kind
        cap_line = (
            f"Capabilities (RAM {idx.build_ms:.0f}ms): procs={counts.get('procedure', 0)}, "
            f"roles={counts.get('role', 0)}, knowledge={counts.get('knowledge', 0)}, "
            f"skills={counts.get('skill', 0)}, primitives={counts.get('primitive', 0)} | "
            f'route "<task/ID>" | forge "<problem>" | doctor | melt-diff | melt-scan'
        )
    except Exception:
        pass

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
            cap_line,
            "SHIFTING_SAND: Check existing local ground truth first; if a domain folder is [EMPTY — INTAKE REQUIRED], synthesize GROUND_TRUTH.md from local sources with explicit [PROPOSED DEFAULT] / [UNKNOWN — OWNER TO CONFIRM] holds and push right instead of quizzing the operator on reversible defaults.",
            'Gate check: python ".agents/scripts/crucible_gate.py" check',
            'Sync check: python "Project/Inner Gravity/check_sync.py"',
        ]
    )


def cmd_session_start(root: Path = ROOT) -> int:
    system_map = _build_system_map(root)
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


def _staged_contains_asana(rel_path: str, root: Path = ROOT) -> bool:
    proc = subprocess.run(
        ["git", "show", f":{rel_path}"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if proc.returncode == 0:
        content = proc.stdout.decode("utf-8", errors="replace")
    else:
        target = root / rel_path
        if not target.is_file():
            return False
        content = target.read_text(encoding="utf-8", errors="replace")
    return bool(ASANA_URL_RE.search(content))


def _extract_target_path(args: dict[str, object], root: Path = ROOT) -> Path | None:
    for key in ("Path", "TargetFile", "file_path", "path", "AbsolutePath"):
        val = args.get(key)
        if isinstance(val, str) and val.strip():
            candidate = Path(val.strip())
            if not candidate.is_absolute():
                candidate = root / candidate
            return candidate.resolve()
    return None


def cmd_pre_tool(root: Path = ROOT) -> int:
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

    target = _extract_target_path(args, root)
    if target is None:
        print(json.dumps({"decision": "allow"}))
        return 0

    root_resolved = root.resolve()
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

    if matched_domain == "Calgary Public Library":
        for field_key in ("Content", "Replacement"):
            val = args.get(field_key)
            if isinstance(val, str) and ASANA_URL_RE.search(val):
                print(
                    json.dumps(
                        {
                            "decision": "deny",
                            "reason": (
                                "ASANA_BOUNDARY: Refusing to write an internal Asana URL into "
                                "Calgary Public Library/. Keep Asana strictly read-only and link pointers outside synced files."
                            ),
                        },
                        ensure_ascii=False,
                    )
                )
                return 0

    if _count_files(root / matched_domain) == 0 and target.name.upper() not in GROUND_TRUTH_FILES:
        print(
            json.dumps(
                {
                    "decision": "deny",
                    "reason": (
                        f"SHIFTING_SAND: '{matched_domain}/' has 0 files. "
                        "Synthesize GROUND_TRUTH.md from existing local context with explicit "
                        "[PROPOSED DEFAULT] and [UNKNOWN — OWNER TO CONFIRM] holds before creating deliverables."
                    ),
                },
                ensure_ascii=False,
            )
        )
        return 0

    print(json.dumps({"decision": "allow"}))
    return 0


def cmd_check(root: Path = ROOT) -> int:
    print(_build_system_map(root))
    reasons: list[str] = []

    if not (root / "IDEAS.md").is_file():
        reasons.append("IDEAS.md missing")

    rc, diff_out = _git_output(["-c", "core.quotepath=false", "diff", "--cached", "--name-only"], root)
    if rc != 0:
        reasons.append("git diff --cached failed")
    else:
        staged_files = [line.strip() for line in diff_out.splitlines() if line.strip()]
        for rel_path in staged_files:
            norm = rel_path.replace("\\", "/")
            parts = norm.split("/")
            if any(part.startswith(".tmp.drive") for part in parts):
                reasons.append(f"staged drive temp file: {norm}")
            if norm.startswith("Calgary Public Library/") and _staged_contains_asana(norm, root):
                reasons.append(f"staged CPL file contains app.asana.com: {norm}")

    wt_cpl: set[str] = set()
    for git_args in (
        ["-c", "core.quotepath=false", "diff", "--name-only", "--", "Calgary Public Library"],
        ["-c", "core.quotepath=false", "ls-files", "--others", "--exclude-standard", "--", "Calgary Public Library"],
    ):
        rc_wt, out_wt = _git_output(git_args, root)
        if rc_wt == 0:
            for line in out_wt.splitlines():
                norm = line.strip().replace("\\", "/")
                if norm:
                    wt_cpl.add(norm)
    for norm in sorted(wt_cpl):
        target = root / norm
        if target.is_file():
            content = target.read_text(encoding="utf-8", errors="replace")
            if ASANA_URL_RE.search(content):
                reasons.append(f"working-tree CPL file contains app.asana.com URL: {norm}")

    for py_dir in (root / ".agents" / "scripts", root / ".agents" / "scripts" / "crucible"):
        if not py_dir.is_dir():
            continue
        for py_file in sorted(py_dir.glob("*.py")):
            try:
                py_compile.compile(str(py_file), doraise=True)
            except (py_compile.PyCompileError, OSError) as exc:
                rel_py = str(py_file.relative_to(root)).replace("\\", "/")
                reasons.append(f"python syntax error in {rel_py}: {exc}")

    if (root / "Knowledge" / "Crucible_Primitives.json").is_file():
        ci = _resolve_index_module()
        prim_findings: list[object] = []
        try:
            ci.validate_primitives_registry(root, prim_findings)
        except AttributeError as exc:
            reasons.append(f"Knowledge/Crucible_Primitives.json: invalid JSON root structure ({exc})")
        for finding in prim_findings:
            if getattr(finding, "severity", "") == "FAIL":
                reasons.append(f"{finding.subject}: {finding.detail}")

    if (root / "Knowledge" / "outcome_ledger.json").is_file():
        ledger_mod = _resolve_ledger_module()
        try:
            ledger_mod.load_ledger(root)
        except ValueError as exc:
            reasons.append(str(exc))

    try:
        scripts_dir = str(Path(__file__).resolve().parent)
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        import test_quality_gate

        tests_dir = root / ".agents" / "scripts" / "tests"
        if tests_dir.is_dir():
            for tqf in test_quality_gate.audit_paths([tests_dir]):
                reasons.append(f"{tqf.rule_id} in {Path(tqf.file).name}:{tqf.line}: {tqf.message}")
    except ImportError:
        pass

    if reasons:
        print(f"BLOCKED: {'; '.join(reasons)}")
        return 1

    print("PASS: IDEAS.md present; Python syntax, primitives schema, staged files, and test-quality checks clean.")
    return 0


def _resolve_index_module():
    scripts_dir = str(Path(__file__).resolve().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import crucible_index

    return crucible_index


def _resolve_exporter_module():
    scripts_dir = str(Path(__file__).resolve().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from crucible import exporter

    return exporter


def _resolve_ledger_module():
    scripts_dir = str(Path(__file__).resolve().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    from crucible import ledger

    return ledger


def cmd_route(
    root: Path,
    query_parts: list[str],
    *,
    top_k: int = 5,
    as_json: bool = False,
    no_global: bool = False,
    no_learn: bool = False,
) -> int:
    if not query_parts:
        print("usage: crucible_gate.py route <task query or canonical ID>", file=sys.stderr)
        return 2
    ci = _resolve_index_module()
    global_dir = None if no_global else ci.DEFAULT_GLOBAL_CONFIG_DIR
    idx = ci.build_index(root, global_config_dir=global_dir)
    ledger_data = None
    if not no_learn and (root / "Knowledge" / "outcome_ledger.json").is_file():
        try:
            ledger_data = _resolve_ledger_module().load_ledger(root)
        except ValueError:
            ledger_data = None
    result = ci.route_query(idx, " ".join(query_parts), top_k=top_k, ledger=ledger_data)
    print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False) if as_json else ci._format_route_text(result))
    return 0


def cmd_forge(
    root: Path,
    problem_parts: list[str],
    *,
    top_k: int = 4,
    as_json: bool = False,
    no_global: bool = False,
    domain: str | None = None,
) -> int:
    if not problem_parts:
        print("usage: crucible_gate.py forge <problem description>", file=sys.stderr)
        return 2
    ci = _resolve_index_module()
    global_dir = None if no_global else ci.DEFAULT_GLOBAL_CONFIG_DIR
    idx = ci.build_index(root, global_config_dir=global_dir)
    brief = ci.forge_brief(idx, " ".join(problem_parts), top_k=top_k, domain=domain)
    print(json.dumps(brief.to_dict(), indent=2, ensure_ascii=False) if as_json else ci._format_forge_text(brief))
    return 0


def cmd_doctor(root: Path, *, as_json: bool = False, no_global: bool = False, skip_exec: bool = False) -> int:
    ci = _resolve_index_module()
    global_dir = None if no_global else ci.DEFAULT_GLOBAL_CONFIG_DIR
    report = ci.run_doctor(root, global_config_dir=global_dir, execute_hooks=not skip_exec)
    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False) if as_json else ci._format_doctor_text(report))
    return 0 if report.ok else 1


def cmd_melt_diff(
    root: Path,
    *,
    owner: str = "guarani-ux",
    from_json: Path | None = None,
    as_json: bool = False,
) -> int:
    ci = _resolve_index_module()
    try:
        if from_json is not None:
            repos_data = json.loads(from_json.read_text(encoding="utf-8"))
        else:
            repos_data = ci.fetch_github_repos(owner=owner)
        report = ci.compute_melt_diff(root, repos_data)
    except Exception as exc:
        print(f"BLOCKED: melt-diff failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, ensure_ascii=False) if as_json else ci._format_melt_diff_text(report))
    return 0


def cmd_melt_scan(
    repos: list[str],
    *,
    owner: str = "guarani-ux",
    from_json: Path | None = None,
    as_json: bool = False,
) -> int:
    ci = _resolve_index_module()
    fixtures: dict[str, Any] | None = None
    if from_json is not None:
        try:
            fixtures = json.loads(from_json.read_text(encoding="utf-8"))
        except Exception as exc:
            print(f"BLOCKED: could not load --from-json fixture: {exc}", file=sys.stderr)
            return 1
    try:
        report = ci.run_melt_scan(repos, owner=owner, fixtures=fixtures)
    except ValueError as exc:
        print(f"usage error: {exc}", file=sys.stderr)
        return 2
    except Exception as exc:
        print(f"BLOCKED: melt-scan failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2, ensure_ascii=False) if as_json else ci._format_melt_scan_text(report))
    return 0


def cmd_export_map(
    root: Path,
    output: Path | None = None,
    *,
    no_global: bool = False,
    as_json: bool = False,
) -> int:
    ci = _resolve_index_module()
    exporter = _resolve_exporter_module()
    global_dir = None if no_global else (ci.DEFAULT_GLOBAL_CONFIG_DIR if ci.DEFAULT_GLOBAL_CONFIG_DIR.is_dir() else None)
    try:
        out_path, payload = exporter.write_capability_map(
            root,
            output_path=output,
            global_config_dir=global_dir,
        )
    except Exception as exc:
        print(f"BLOCKED: export-map failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(payload, indent=2, ensure_ascii=False) if as_json else f"Exported {payload['total']} capabilities to {out_path}")
    return 0


def cmd_learn(
    root: Path,
    *,
    verdict: str | None,
    source: str | None,
    capabilities: list[str],
    files: list[str],
    commit: str = "",
    refresh_git: bool = False,
    as_json: bool = False,
) -> int:
    if not verdict or not source:
        print("usage: crucible_gate.py learn --verdict PASS|FAIL|REVERT --source <label> [--cap ID ...] [--file PATH ...] [--refresh-git]", file=sys.stderr)
        return 2
    ledger_mod = _resolve_ledger_module()
    try:
        ledger = ledger_mod.record_outcome(
            root,
            source=source,
            verdict=verdict,
            capabilities=capabilities,
            files=files,
            commit=commit,
            refresh_git=refresh_git,
        )
    except ValueError as exc:
        print(f"BLOCKED: learn failed: {exc}", file=sys.stderr)
        return 1
    if as_json:
        print(json.dumps(ledger, indent=2, ensure_ascii=False))
    else:
        print(
            f"Recorded {verdict.upper()} from '{source}' "
            f"(priors={len(ledger['capability_priors'])}, file_risk={len(ledger['file_risk'])}, events={len(ledger['events'])})"
        )
    return 0


def cmd_risk(
    root: Path,
    files: list[str],
    *,
    threshold: float = 0.45,
    as_json: bool = False,
) -> int:
    ledger_mod = _resolve_ledger_module()
    try:
        ledger = ledger_mod.load_ledger(root)
    except ValueError as exc:
        print(f"BLOCKED: risk failed: {exc}", file=sys.stderr)
        return 1

    target_files = list(files)
    if not target_files:
        rc, status_out = _git_output(["status", "--porcelain"], root)
        if rc == 0:
            for line in status_out.splitlines():
                if len(line) > 3:
                    raw_path = line[3:].strip()
                    if " -> " in raw_path:
                        raw_path = raw_path.split(" -> ", 1)[1].strip()
                    if raw_path:
                        target_files.append(raw_path)

    report = ledger_mod.assess_risk(ledger, target_files, threshold=threshold)
    if as_json:
        print(json.dumps(report, indent=2, ensure_ascii=False))
    else:
        print(
            f"Risk ({len(report['files'])} file(s), threshold={threshold}): "
            f"{report['recommended_action']}"
        )
        for item in report["files"]:
            flags = []
            if item["high_risk"]:
                flags.append("HIGH_RISK")
            if item["referee_boundary"]:
                flags.append("REFEREE")
            tag = f" [{' | '.join(flags)}]" if flags else ""
            print(f"  - {item['path']}: risk={item['risk_score']:.4f} (fix={item['fix_commits']}/{item['commits']}){tag}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Crucible Domain deterministic gate.")
    parser.add_argument(
        "--root",
        type=Path,
        default=ROOT,
        help="Workspace root directory (defaults to repository root).",
    )
    parser.add_argument(
        "subcommand",
        choices=(
            "session-start",
            "pre-tool",
            "check",
            "pre-commit",
            "route",
            "forge",
            "doctor",
            "melt-diff",
            "melt-scan",
            "export-map",
            "learn",
            "risk",
        ),
        help="Gate action to execute.",
    )
    parser.add_argument(
        "query",
        nargs="*",
        help="Query tokens/ID for 'route', problem description for 'forge', repo names for 'melt-scan', or paths for 'risk'.",
    )
    parser.add_argument("--top", type=int, default=5, help="Max matches per category for 'route' or 'forge'.")
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit structured JSON for 'route', 'forge', 'doctor', 'melt-diff', 'melt-scan', 'export-map', 'learn', or 'risk'.",
    )
    parser.add_argument("--no-global", action="store_true", help="Skip reading ~/.gemini/config during route/forge/doctor/export-map.")
    parser.add_argument("--no-learn", action="store_true", help="Disable learned priors in 'route' for static baseline comparison.")
    parser.add_argument("--skip-exec", action="store_true", help="Skip live hook execution during 'doctor'.")
    parser.add_argument("--owner", default="guarani-ux", help="GitHub owner for 'melt-diff' or 'melt-scan'.")
    parser.add_argument("--from-json", type=Path, default=None, help="Offline JSON fixture path for 'melt-diff' or 'melt-scan'.")
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional output path for 'export-map' (defaults to Graphs/capability_map.json).",
    )
    parser.add_argument(
        "--domain",
        choices=("systems", "media", "writing", "worldbuilding", "general"),
        default=None,
        help="Optional domain scope override for 'forge'.",
    )
    parser.add_argument("--verdict", choices=("PASS", "FAIL", "REVERT"), default=None, help="Outcome verdict for 'learn'.")
    parser.add_argument("--source", default=None, help="Evidence source label (e.g. ci:45234665272) for 'learn'.")
    parser.add_argument("--cap", action="append", default=[], help="Capability ID updated by 'learn' (repeatable).")
    parser.add_argument("--file", action="append", default=[], help="File path associated with 'learn' (repeatable).")
    parser.add_argument("--commit", default="", help="Optional commit SHA for 'learn'.")
    parser.add_argument("--refresh-git", action="store_true", help="Refresh file_risk scores from git history during 'learn'.")
    parser.add_argument("--threshold", type=float, default=0.45, help="Risk escalation threshold for 'risk'.")
    args = parser.parse_args(argv)
    root = args.root.resolve()

    if args.subcommand == "session-start":
        return cmd_session_start(root)
    if args.subcommand == "pre-tool":
        return cmd_pre_tool(root)
    if args.subcommand == "route":
        return cmd_route(
            root,
            args.query,
            top_k=args.top,
            as_json=args.json,
            no_global=args.no_global,
            no_learn=args.no_learn,
        )
    if args.subcommand == "forge":
        return cmd_forge(
            root,
            args.query,
            top_k=4 if args.top == 5 else args.top,
            as_json=args.json,
            no_global=args.no_global,
            domain=args.domain,
        )
    if args.subcommand == "doctor":
        return cmd_doctor(root, as_json=args.json, no_global=args.no_global, skip_exec=args.skip_exec)
    if args.subcommand == "melt-diff":
        return cmd_melt_diff(root, owner=args.owner, from_json=args.from_json, as_json=args.json)
    if args.subcommand == "melt-scan":
        return cmd_melt_scan(args.query, owner=args.owner, from_json=args.from_json, as_json=args.json)
    if args.subcommand == "export-map":
        return cmd_export_map(root, output=args.output, no_global=args.no_global, as_json=args.json)
    if args.subcommand == "learn":
        return cmd_learn(
            root,
            verdict=args.verdict,
            source=args.source,
            capabilities=args.cap,
            files=args.file,
            commit=args.commit,
            refresh_git=args.refresh_git,
            as_json=args.json,
        )
    if args.subcommand == "risk":
        return cmd_risk(root, args.query, threshold=args.threshold, as_json=args.json)
    return cmd_check(root)


if __name__ == "__main__":
    raise SystemExit(main())
