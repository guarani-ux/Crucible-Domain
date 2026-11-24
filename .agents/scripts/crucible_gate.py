#!/usr/bin/env python3
"""Deterministic local gate and session-start context mapper for Crucible Domain."""

from __future__ import annotations

import argparse
import hashlib
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

    cap_line = 'Route: python ".agents/scripts/crucible_gate.py" route "<task or ID>" | Health: doctor'
    try:
        ci = _resolve_index_module()
        global_dir = ci.DEFAULT_GLOBAL_CONFIG_DIR if ci.DEFAULT_GLOBAL_CONFIG_DIR.is_dir() else None
        idx = ci.build_index(root, global_config_dir=global_dir)
        counts = idx.counts_by_kind
        cap_line = (
            f"Capabilities (RAM {idx.build_ms:.0f}ms): procs={counts.get('procedure', 0)}, "
            f"roles={counts.get('role', 0)}, knowledge={counts.get('knowledge', 0)}, "
            f"skills={counts.get('skill', 0)}, primitives={counts.get('primitive', 0)} | "
            f'route "<task/ID>" | doctor'
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


def _check_self_model_drift(root: Path = ROOT) -> list[str]:
    """Verify active plugins and 5-piece crucible/ kernel modules match AGENTS.md and 00_System_Atlas."""
    agents_path = root / "AGENTS.md"
    atlas_path = root / "Graphs" / "00_System_Atlas_and_Neon_Handoff.md"
    if not agents_path.is_file() or not atlas_path.is_file():
        return []

    agents_text = agents_path.read_text(encoding="utf-8", errors="replace").lower()
    atlas_text = atlas_path.read_text(encoding="utf-8", errors="replace").lower()
    reasons: list[str] = []

    plugins_dir = root / ".agents" / "plugins"
    if plugins_dir.is_dir():
        for plugin_dir in sorted(p for p in plugins_dir.iterdir() if p.is_dir()):
            if not (plugin_dir / "plugin.json").is_file():
                continue
            pname = plugin_dir.name.lower()
            variants = (pname, pname.replace("-", " "))
            if not any(v in agents_text for v in variants):
                reasons.append(f"self-model drift: plugin '{plugin_dir.name}' missing from AGENTS.md")
            if not any(v in atlas_text for v in variants):
                reasons.append(
                    f"self-model drift: plugin '{plugin_dir.name}' missing from Graphs/00_System_Atlas_and_Neon_Handoff.md"
                )

    kernel_dir = root / ".agents" / "scripts" / "crucible"
    if kernel_dir.is_dir():
        for py_file in sorted(kernel_dir.glob("*.py")):
            if py_file.name.lower() not in atlas_text:
                reasons.append(
                    f"self-model drift: kernel module '{py_file.name}' missing from Graphs/00_System_Atlas_and_Neon_Handoff.md"
                )

    return reasons


def _extract_frontmatter_depends_on(md_path: Path) -> list[str]:
    """Parse YAML frontmatter `depends_on:` relative paths without external dependencies."""
    text = md_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return []

    deps: list[str] = []
    in_depends = False
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            break
        if stripped.startswith("depends_on:"):
            inline = stripped.split(":", 1)[1].strip()
            if inline.startswith("[") and inline.endswith("]"):
                for item in inline[1:-1].split(","):
                    cleaned = item.strip().strip("'\"")
                    if cleaned:
                        deps.append(cleaned)
                in_depends = False
            else:
                in_depends = True
            continue
        if in_depends:
            if stripped.startswith("- "):
                cleaned = stripped[2:].strip().strip("'\"")
                if cleaned:
                    deps.append(cleaned)
            elif stripped and not line.startswith((" ", "\t")):
                in_depends = False
    return deps


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _extract_frontmatter_depends_on_sha256(md_path: Path) -> dict[str, str]:
    """Parse optional YAML frontmatter `depends_on_sha256:` mapping of rel_path -> sha256."""
    text = md_path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}

    hashes: dict[str, str] = {}
    in_map = False
    for line in lines[1:]:
        stripped = line.strip()
        if stripped == "---":
            break
        if stripped.startswith("depends_on_sha256:"):
            in_map = True
            continue
        if in_map:
            if line.startswith((" ", "\t")) and ":" in stripped:
                key, val = stripped.split(":", 1)
                k = key.strip().strip("'\"")
                v = val.strip().strip("'\"").lower()
                if k and v:
                    hashes[k] = v
            elif stripped and not line.startswith((" ", "\t")):
                in_map = False
    return hashes


def _check_artifact_dependencies(root: Path = ROOT, *, strict: bool = False) -> tuple[list[str], list[str]]:
    """Check Markdown frontmatter depends_on / depends_on_sha256 targets for missing files (FAIL) and staleness (WARN / --strict FAIL)."""
    failures: list[str] = []
    warnings: list[str] = []
    root_resolved = root.resolve()

    for folder_name in COUNT_DIRS:
        folder = root / folder_name
        if not folder.is_dir():
            continue
        for md_path in sorted(folder.rglob("*.md")):
            deps = _extract_frontmatter_depends_on(md_path)
            pinned_hashes = _extract_frontmatter_depends_on_sha256(md_path)
            all_deps = list(dict.fromkeys([*deps, *pinned_hashes.keys()]))
            if not all_deps:
                continue
            rel_art = str(md_path.relative_to(root)).replace("\\", "/")
            art_mtime = md_path.stat().st_mtime
            for dep in all_deps:
                dep_path = (root / dep).resolve()
                try:
                    dep_path.relative_to(root_resolved)
                except ValueError:
                    failures.append(f"broken depends_on in {rel_art}: '{dep}' resolves outside workspace")
                    continue
                if not dep_path.is_file():
                    failures.append(f"broken depends_on in {rel_art}: missing '{dep}'")
                    continue
                if dep in pinned_hashes:
                    actual_sha = _sha256_file(dep_path)
                    if actual_sha != pinned_hashes[dep]:
                        msg = f"stale artifact {rel_art} (content hash changed for '{dep}')"
                        if strict:
                            failures.append(msg)
                        else:
                            warnings.append(msg)
                elif dep_path.stat().st_mtime > art_mtime:
                    msg = f"stale artifact {rel_art} (older than depends_on '{dep}')"
                    if strict:
                        failures.append(msg)
                    else:
                        warnings.append(msg)

    return failures, warnings


def cmd_check(root: Path = ROOT, *, strict: bool = False) -> int:
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

    reasons.extend(_check_self_model_drift(root))
    dep_failures, dep_warnings = _check_artifact_dependencies(root, strict=strict)
    reasons.extend(dep_failures)

    for warn in dep_warnings:
        print(f"WARN: {warn}")

    if reasons:
        print(f"BLOCKED: {'; '.join(reasons)}")
        return 1

    print(
        "PASS: IDEAS.md present; Python syntax, primitives schema, self-model drift, "
        "artifact dependencies, staged files, and test-quality checks clean."
    )
    return 0


def _resolve_index_module():
    scripts_dir = str(Path(__file__).resolve().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, scripts_dir)
    import crucible_index

    return crucible_index


def cmd_route(
    root: Path,
    query_parts: list[str],
    *,
    top_k: int = 5,
    as_json: bool = False,
    no_global: bool = False,
) -> int:
    if not query_parts:
        print("usage: crucible_gate.py route <task query or canonical ID>", file=sys.stderr)
        return 2
    ci = _resolve_index_module()
    global_dir = None if no_global else ci.DEFAULT_GLOBAL_CONFIG_DIR
    idx = ci.build_index(root, global_config_dir=global_dir)
    result = ci.route_query(idx, " ".join(query_parts), top_k=top_k)
    print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False) if as_json else ci._format_route_text(result))
    return 0


def cmd_doctor(root: Path, *, as_json: bool = False, no_global: bool = False, skip_exec: bool = False) -> int:
    ci = _resolve_index_module()
    global_dir = None if no_global else ci.DEFAULT_GLOBAL_CONFIG_DIR
    report = ci.run_doctor(root, global_config_dir=global_dir, execute_hooks=not skip_exec)
    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False) if as_json else ci._format_doctor_text(report))
    return 0 if report.ok else 1


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
        choices=("session-start", "pre-tool", "check", "pre-commit", "route", "doctor"),
        help="Gate action to execute.",
    )
    parser.add_argument("query", nargs="*", help="Query tokens/ID for 'route'.")
    parser.add_argument("--top", type=int, default=5, help="Max matches per category for 'route'.")
    parser.add_argument("--json", action="store_true", help="Emit structured JSON for 'route' or 'doctor'.")
    parser.add_argument("--no-global", action="store_true", help="Skip reading ~/.gemini/config during route/doctor.")
    parser.add_argument("--skip-exec", action="store_true", help="Skip live hook execution during 'doctor'.")
    parser.add_argument("--strict", action="store_true", help="Treat stale depends_on artifacts as blocking failures in 'check'.")
    args = parser.parse_args(argv)
    root = args.root.resolve()

    if args.subcommand == "session-start":
        return cmd_session_start(root)
    if args.subcommand == "pre-tool":
        return cmd_pre_tool(root)
    if args.subcommand == "route":
        return cmd_route(root, args.query, top_k=args.top, as_json=args.json, no_global=args.no_global)
    if args.subcommand == "doctor":
        return cmd_doctor(root, as_json=args.json, no_global=args.no_global, skip_exec=args.skip_exec)
    return cmd_check(root, strict=args.strict)


if __name__ == "__main__":
    raise SystemExit(main())
