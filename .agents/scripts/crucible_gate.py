#!/usr/bin/env python3
"""Deterministic local gate and session-start context mapper for Crucible Domain."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import py_compile
import re
import shlex
import subprocess
import sys
from dataclasses import asdict
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
            install_status,
            cap_line,
            "SHIFTING_SAND: Check existing local ground truth first; if a domain folder is [EMPTY — INTAKE REQUIRED], synthesize GROUND_TRUTH.md from local sources with explicit [PROPOSED DEFAULT] / [UNKNOWN — OWNER TO CONFIRM] holds and push right instead of quizzing the operator on reversible defaults.",
            'Gate check: python ".agents/scripts/crucible_gate.py" check',
            'Sync check: python "Project/Inner Gravity/check_sync.py"',
        ]
    )


def _fast_session_context_line(root: Path) -> str:
    """Zero-sklearn (<50ms) Context Compiler for session-start; upgrades to hot daemon (<15ms) if running."""
    state_file = root / ".agents" / ".ml_daemon.json"
    if state_file.is_file():
        try:
            import socket
            info = json.loads(state_file.read_text(encoding="utf-8"))
            with socket.create_connection(("127.0.0.1", int(info["port"])), timeout=0.15) as sock:
                sock.sendall(b'{"cmd":"context"}\n')
                raw = sock.recv(65536).decode("utf-8", errors="replace").strip()
                data = json.loads(raw)
                if data.get("ok") and data.get("summary_line"):
                    return str(data["summary_line"])
        except Exception:
            pass
    proc = subprocess.run(["git", "-C", str(root), "status", "--porcelain"], capture_output=True, text=True, check=False)
    dirty = [ln[3:].strip().replace("\\", "/") for ln in proc.stdout.splitlines() if len(ln) >= 4] if proc.returncode == 0 else []
    if not dirty:
        return "Context Compiler (clean): active=general | ready for new assignment"
    blob = " ".join(dirty).lower()
    domain = "writers_room" if "writers" in blob else ("story_lane" if "story" in blob else ("crucible_engine" if "crucible_gate" in blob or "verify_all" in blob else "general"))
    focus = ",".join(Path(f).name for f in dirty[:3])
    return f"Context Compiler (fast): domain={domain} | focus={focus} | run ml-preflight or ml-daemon start for full ML"


def cmd_session_start(root: Path = ROOT) -> int:
    lines = [
        _build_system_map(root),
        "Spokes: writers-room, story-lane, crucible-observatory, meeting-prep | Verify: scripts/verify_all.ps1",
        "Engine (0 LLM): discover | ast-scan | campaign {compile|plan|run --worktree --replay-out} | story {recognize|select|chg01} | g5-check | kernel | ml-preflight",
        _fast_session_context_line(root),
    ]
    system_map = "\n".join(lines)
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


def _emit_decision(decision: str, reason: str | None = None) -> int:
    payload = {"decision": decision} if reason is None else {"decision": decision, "reason": reason}
    print(json.dumps(payload, ensure_ascii=False))
    return 0


def _check_mechanical_edit_guard(tool_name: str, args: dict[str, object], target: Path) -> str | None:
    """Enforce delta-only edits on large files (>150 lines) and valid Python syntax in RAM before disk write."""
    if tool_name != "write_file":
        return None
    if args.get("Overwrite") is True and target.is_file():
        try:
            line_count = len(target.read_text(encoding="utf-8", errors="replace").splitlines())
        except OSError:
            line_count = 0
        if line_count > 150:
            return (
                f"DELTA_ONLY: Refusing full-file write_file(Overwrite=True) on existing {line_count}-line file "
                f"'{target.name}'. Use targeted edit_file or tx_patch.py."
            )
    if target.suffix.lower() == ".py" and isinstance(args.get("Content"), str):
        try:
            import ast
            ast.parse(str(args["Content"]), filename=str(target))
        except SyntaxError as exc:
            return f"SYNTAX_GUARD: Refusing to write invalid Python syntax ({exc.msg} at line {exc.lineno})."
    return None


def cmd_pre_tool(root: Path = ROOT) -> int:
    payload = _read_stdin_json()
    tool_call = payload.get("toolCall")
    if not isinstance(tool_call, dict):
        return _emit_decision("allow")
    tool_name = str(tool_call.get("name") or "")
    args = tool_call.get("args")
    if not isinstance(args, dict):
        return _emit_decision("allow")
    if tool_name == "run_command":
        cmd = str(args.get("CommandLine") or args.get("command") or "")
        low = cmd.lower()
        protected_targets = (".agents/operator_grants.json", ".agents/acceptance.lock.json", ".agents/hooks.json")
        if any(pt in low for pt in protected_targets) and any(op in low for op in (">", "tee ", "set-content", "out-file", "write", "rm ", "del ", "remove-item", "python ")):
            return _emit_decision("deny", "AUTHORITY_GUARD: Refusing run_command mutation of protected governance/grant files.")
        if "calgary public library" in low and "app.asana.com" in low:
            return _emit_decision("deny", "ASANA_BOUNDARY: Refusing run_command writing app.asana.com into Calgary Public Library/.")
        destructive_patterns = (
            r"\bgit\s+push\b",
            r"\bgit\s+reset\s+--hard\b",
            r"\brm\s+-rf\b",
            r"\bremove-item\b.*-recurse",
            r"\bdrop\s+table\b",
        )
        if any(re.search(pat, low) for pat in destructive_patterns):
            return _emit_decision("deny", "AUTHORITY_GUARD: Destructive/external run_command requires verified operator grant.")
        return _emit_decision("allow")

    if tool_name not in ("write_file", "edit_file"):
        return _emit_decision("allow")

    target = _extract_target_path(args, root)
    if target is None:
        return _emit_decision("allow")

    try:
        rel_parts = target.relative_to(root.resolve()).parts
    except ValueError:
        return _emit_decision("allow")

    mech_deny = _check_mechanical_edit_guard(str(tool_call.get("name")), args, target)
    if mech_deny is not None:
        return _emit_decision("deny", mech_deny)

    matched_domain = next((d for d in COUNT_DIRS if rel_parts and d.lower() == rel_parts[0].lower()), None)
    if matched_domain is None:
        return _emit_decision("allow")

    if matched_domain == "Calgary Public Library":
        for field_key in ("Content", "Replacement"):
            val = args.get(field_key)
            if isinstance(val, str) and ASANA_URL_RE.search(val):
                return _emit_decision(
                    "deny",
                    "ASANA_BOUNDARY: Refusing to write an internal Asana URL into "
                    "Calgary Public Library/. Keep Asana strictly read-only and link pointers outside synced files.",
                )

    if _count_files(root / matched_domain) == 0 and target.name.upper() not in GROUND_TRUTH_FILES:
        return _emit_decision(
            "deny",
            f"SHIFTING_SAND: '{matched_domain}/' has 0 files. "
            "Synthesize GROUND_TRUTH.md from existing local context with explicit "
            "[PROPOSED DEFAULT] and [UNKNOWN — OWNER TO CONFIRM] holds before creating deliverables.",
        )

    return _emit_decision("allow")


def _check_self_model_drift(root: Path = ROOT) -> list[str]:
    """Verify active plugins and modular crucible/ kernel modules match AGENTS.md and 00_System_Atlas."""
    agents_path = root / "AGENTS.md"
    atlas_path = root / "Graphs" / "00_System_Atlas_and_Neon_Handoff.md"
    if not agents_path.is_file() or not atlas_path.is_file():
        return []

    agents_text = agents_path.read_text(encoding="utf-8", errors="replace").lower()
    atlas_text = atlas_path.read_text(encoding="utf-8", errors="replace").lower()
    reasons: list[str] = []

    plugins_dir = root / ".agents" / "plugins"
    for plugin_dir in sorted(plugins_dir.iterdir()) if plugins_dir.is_dir() else []:
        if not plugin_dir.is_dir() or not (plugin_dir / "plugin.json").is_file():
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
    for py_file in sorted(kernel_dir.glob("*.py")) if kernel_dir.is_dir() else []:
        if py_file.name.lower() not in atlas_text:
            reasons.append(
                f"self-model drift: kernel module '{py_file.name}' missing from Graphs/00_System_Atlas_and_Neon_Handoff.md"
            )

    return reasons


def _frontmatter_lines(md_path: Path) -> list[str]:
    lines = md_path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines or lines[0].strip() != "---":
        return []
    out: list[str] = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        out.append(line)
    return out


def _extract_frontmatter_depends_on(md_path: Path) -> list[str]:
    """Parse YAML frontmatter `depends_on:` relative paths without external dependencies."""
    deps: list[str] = []
    in_depends = False
    for line in _frontmatter_lines(md_path):
        stripped = line.strip()
        if stripped.startswith("depends_on:"):
            inline = stripped.split(":", 1)[1].strip()
            if inline.startswith("[") and inline.endswith("]"):
                deps.extend(c for item in inline[1:-1].split(",") if (c := item.strip().strip("'\"")))
                in_depends = False
            else:
                in_depends = True
        elif in_depends and stripped.startswith("- "):
            if cleaned := stripped[2:].strip().strip("'\""):
                deps.append(cleaned)
        elif in_depends and stripped and not line.startswith((" ", "\t")):
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
    hashes: dict[str, str] = {}
    in_map = False
    for line in _frontmatter_lines(md_path):
        stripped = line.strip()
        if stripped.startswith("depends_on_sha256:"):
            in_map = True
        elif in_map and line.startswith((" ", "\t")) and ":" in stripped:
            key, val = stripped.split(":", 1)
            k, v = key.strip().strip("'\""), val.strip().strip("'\"").lower()
            if k and v:
                hashes[k] = v
        elif in_map and stripped and not line.startswith((" ", "\t")):
            in_map = False
    return hashes


def _check_single_dep(
    root: Path,
    root_resolved: Path,
    rel_art: str,
    art_mtime: float,
    dep: str,
    pinned_hashes: dict[str, str],
    strict: bool,
    failures: list[str],
    warnings: list[str],
) -> None:
    dep_path = (root / dep).resolve()
    try:
        dep_path.relative_to(root_resolved)
    except ValueError:
        failures.append(f"broken depends_on in {rel_art}: '{dep}' resolves outside workspace")
        return
    if not dep_path.is_file():
        failures.append(f"broken depends_on in {rel_art}: missing '{dep}'")
        return
    if dep in pinned_hashes:
        if _sha256_file(dep_path) != pinned_hashes[dep]:
            msg = f"stale artifact {rel_art} (content hash changed for '{dep}')"
            (failures if strict else warnings).append(msg)
    elif dep_path.stat().st_mtime > art_mtime:
        msg = f"stale artifact {rel_art} (older than depends_on '{dep}')"
        (failures if strict else warnings).append(msg)


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
                _check_single_dep(root, root_resolved, rel_art, art_mtime, dep, pinned_hashes, strict, failures, warnings)

    return failures, warnings


def _check_staged_files(root: Path) -> list[str]:
    reasons: list[str] = []
    rc, diff_out = _git_output(["-c", "core.quotepath=false", "diff", "--cached", "--name-only"], root)
    if rc != 0:
        return ["git diff --cached failed"]
    for rel_path in (ln.strip() for ln in diff_out.splitlines() if ln.strip()):
        norm = rel_path.replace("\\", "/")
        if any(part.startswith(".tmp.drive") for part in norm.split("/")):
            reasons.append(f"staged drive temp file: {norm}")
        if norm.startswith("Calgary Public Library/") and _staged_contains_asana(norm, root):
            reasons.append(f"staged CPL file contains app.asana.com: {norm}")
    return reasons


def _check_working_tree_cpl(root: Path) -> list[str]:
    reasons: list[str] = []
    wt_cpl: set[str] = set()
    for git_args in (
        ["-c", "core.quotepath=false", "diff", "--name-only", "--", "Calgary Public Library"],
        ["-c", "core.quotepath=false", "ls-files", "--others", "--exclude-standard", "--", "Calgary Public Library"],
    ):
        rc_wt, out_wt = _git_output(git_args, root)
        if rc_wt == 0:
            wt_cpl.update(ln.strip().replace("\\", "/") for ln in out_wt.splitlines() if ln.strip())
    for norm in sorted(wt_cpl):
        target = root / norm
        if target.is_file() and ASANA_URL_RE.search(target.read_text(encoding="utf-8", errors="replace")):
            reasons.append(f"working-tree CPL file contains app.asana.com URL: {norm}")
    return reasons


def _check_python_and_primitives(root: Path) -> list[str]:
    import ast
    reasons: list[str] = []
    for py_dir in (root / ".agents" / "scripts", root / ".agents" / "scripts" / "crucible"):
        for py_file in sorted(py_dir.glob("*.py")) if py_dir.is_dir() else []:
            try:
                ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
            except (SyntaxError, OSError, UnicodeDecodeError) as exc:
                reasons.append(f"python syntax error in {str(py_file.relative_to(root)).replace('\\', '/')}: {exc}")

    if (root / "Knowledge" / "Crucible_Primitives.json").is_file():
        prim_findings: list[object] = []
        try:
            _resolve_index_module().validate_primitives_registry(root, prim_findings)
        except AttributeError as exc:
            reasons.append(f"Knowledge/Crucible_Primitives.json: invalid JSON root structure ({exc})")
        for finding in prim_findings:
            if getattr(finding, "severity", "") == "FAIL":
                reasons.append(f"{finding.subject}: {finding.detail}")
    return reasons


def _check_test_quality(root: Path) -> list[str]:
    reasons: list[str] = []
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
    return reasons


def cmd_pre_commit(root: Path = ROOT, *, strict: bool = False) -> int:
    effective_strict = strict
    try:
        eng = _load_ram_ml_engine()
        risk = eng.assess_commit_risk(root)
        if risk["staged_count"] > 0:
            effective_strict = strict or bool(risk["enforce_strict"])
            print(
                f"Adaptive Pre-Commit ({risk['elapsed_ms']}ms): staged={risk['staged_count']} | "
                f"P(break)={risk['risk_prob']} tier={risk['tier']} strict={effective_strict}"
            )
            for adv in risk["advisories"]:
                print(f"  ADVISORY: {adv}")
    except Exception:
        pass
    return cmd_check(root, strict=effective_strict)


def cmd_check(root: Path = ROOT, *, strict: bool = False) -> int:
    print(_build_system_map(root))
    reasons: list[str] = []
    if not (root / "IDEAS.md").is_file():
        reasons.append("IDEAS.md missing")
    reasons.extend(_check_staged_files(root))
    reasons.extend(_check_working_tree_cpl(root))
    reasons.extend(_check_python_and_primitives(root))
    reasons.extend(_check_test_quality(root))
    reasons.extend(_check_self_model_drift(root))
    lock_path = root / ".agents" / "acceptance.lock.json"
    if lock_path.is_file():
        try:
            lock_data = json.loads(lock_path.read_text(encoding="utf-8"))
            for req in lock_data.get("required_files") or []:
                if not (root / str(req)).is_file():
                    reasons.append(f"acceptance.lock missing required_file: {req}")
            for py_rel in lock_data.get("python_syntax") or []:
                py_p = root / str(py_rel)
                if not py_p.is_file():
                    reasons.append(f"acceptance.lock missing python_syntax file: {py_rel}")
                else:
                    try:
                        import ast
                        ast.parse(py_p.read_text(encoding="utf-8"), filename=str(py_p))
                    except (SyntaxError, OSError, UnicodeDecodeError) as exc:
                        reasons.append(f"acceptance.lock syntax error in {py_rel}: {exc}")
        except (OSError, json.JSONDecodeError) as exc:
            reasons.append(f"invalid .agents/acceptance.lock.json: {exc}")
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


def cmd_doctor(root: Path, *, as_json: bool = False, no_global: bool = False, skip_exec: bool = False, verbose: bool = False) -> int:
    ci = _resolve_index_module()
    global_dir = None if no_global else ci.DEFAULT_GLOBAL_CONFIG_DIR
    report = ci.run_doctor(root, global_config_dir=global_dir, execute_hooks=not skip_exec)
    print(json.dumps(report.to_dict(), indent=2, ensure_ascii=False) if as_json else ci._format_doctor_text(report, verbose=verbose))
    return 0 if report.ok else 1


def _resolve_campaign_ir_module():
    scripts_dir = str(Path(__file__).resolve().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    from crucible import campaign_ir

    return campaign_ir


def _resolve_crucible_submodule(name: str):
    scripts_dir = str(Path(__file__).resolve().parent)
    if scripts_dir not in sys.path:
        sys.path.insert(0, str(scripts_dir))
    import importlib

    return importlib.import_module(f"crucible.{name}")


def _resolve_cli_path(root: Path, raw_path: Path | str) -> Path:
    p = Path(raw_path)
    if p.is_absolute():
        return p
    candidate = root / p
    if candidate.exists() or not p.exists():
        return candidate
    return p


def _planned_slice_to_dict(ps: object) -> dict[str, object]:
    node = ps.node
    return {
        "id": node.id,
        "status": ps.status,
        "computed_sha256": ps.computed_sha256,
        "target_paths": list(node.target_paths),
        "depends_on": list(node.depends_on),
        "verify_cmd": node.verify_cmd,
        "reason": ps.reason,
    }


def _emit_campaign_errors(errors: list[str], label: str, as_json: bool) -> int:
    if as_json:
        print(json.dumps({"ok": False, "errors": errors}, indent=2, ensure_ascii=False))
    else:
        print(f"BLOCKED: {label}:")
        for err in errors:
            print(f"  - {err}")
    return 1


def _campaign_compile(cir, target_path: Path, as_json: bool) -> int:
    try:
        spec = cir.load_campaign_spec(target_path)
        ordered = cir.compile_campaign(spec)
    except cir.CampaignCompileError as exc:
        return _emit_campaign_errors(exc.errors, "campaign compile failed", as_json)
    except OSError as exc:
        return _emit_campaign_errors([f"cannot read campaign spec '{target_path}': {exc}"], "campaign compile failed", as_json)

    if as_json:
        payload = {
            "ok": True,
            "name": spec.name,
            "repo_root": str(Path(spec.repo_root).resolve()),
            "max_rounds": spec.max_rounds,
            "slice_count": len(ordered),
            "ordered_slices": [
                {"id": n.id, "target_paths": list(n.target_paths), "depends_on": list(n.depends_on), "verify_cmd": n.verify_cmd}
                for n in ordered
            ],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        order_str = " -> ".join(n.id for n in ordered) if ordered else "(none)"
        print(f"PASS: campaign '{spec.name}' compiled ({len(ordered)} slices): {order_str}")
    return 0


def _campaign_plan(cir, root: Path, target_path: Path, cache_path: Path | None, as_json: bool) -> int:
    resolved_cache = _resolve_cli_path(root, cache_path) if cache_path is not None else None
    try:
        compiled = cir.optimize_campaign(cir.load_campaign_spec(target_path), resolved_cache)
    except cir.CampaignCompileError as exc:
        return _emit_campaign_errors(exc.errors, "campaign plan failed", as_json)
    except (OSError, ValueError) as exc:
        return _emit_campaign_errors([f"campaign plan error: {exc}"], "campaign plan failed", as_json)

    waves, active, skipped = compiled.execution_waves, compiled.active_slices, compiled.skipped_slices
    if as_json:
        payload = {
            "ok": True,
            "name": compiled.name,
            "repo_root": str(compiled.repo_root),
            "execution_waves": [[_planned_slice_to_dict(ps) for ps in w] for w in waves],
            "active_slices": [_planned_slice_to_dict(ps) for ps in active],
            "skipped_slices": [_planned_slice_to_dict(ps) for ps in skipped],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"CAMPAIGN PLAN: {compiled.name} | run={len(active)} | skip_cached={len(skipped)} | waves={len(waves)}")
        for idx, wave in enumerate(waves, start=1):
            print(f"Wave {idx}:")
            for ps in wave:
                print(f"  [RUN] {ps.node.id} (sha256={ps.computed_sha256[:12]} targets=[{', '.join(ps.node.target_paths) or '-'}]) - {ps.reason}")
        for ps in skipped:
            print(f"  [SKIP_CACHED] {ps.node.id} (sha256={ps.computed_sha256[:12]}) - {ps.reason}")
    return 0


def _campaign_run(
    cir,
    root: Path,
    target_path: Path,
    cache_path: Path | None,
    as_json: bool,
    *,
    use_worktree: bool = False,
    replay_out: Path | None = None,
) -> int:
    resolved_cache = _resolve_cli_path(root, cache_path) if cache_path is not None else None
    resolved_replay = _resolve_cli_path(root, replay_out) if replay_out is not None else None
    try:
        spec = cir.load_campaign_spec(target_path)
        ordered = cir.compile_campaign(spec)
    except cir.CampaignCompileError as exc:
        return _emit_campaign_errors(exc.errors, "campaign run failed", as_json)
    except (OSError, ValueError) as exc:
        return _emit_campaign_errors([f"campaign run error: {exc}"], "campaign run failed", as_json)

    try:
        cp = cir.load_campaign_checkpoint(resolved_cache) if resolved_cache is not None else None
    except (OSError, ValueError) as exc:
        return _emit_campaign_errors([f"campaign checkpoint error: {exc}"], "campaign run failed", as_json)

    if cp is None:
        cp = cir.CampaignCheckpoint(
            campaign_name=spec.name,
            completed_slices={},
            failed_slices={},
            rounds_used=0,
            max_rounds=spec.max_rounds,
        )

    repo_root = Path(spec.repo_root).resolve()
    node = next((n for n in ordered if n.id not in cp.completed_slices), None)
    if node is None:
        if resolved_cache is not None:
            cir.save_campaign_checkpoint(resolved_cache, cp)
        payload = {
            "ok": True,
            "slice_id": None,
            "input_sha256": None,
            "exit_code": 0,
            "status": "ALREADY_COMPLETED",
            "rounds_used": cp.rounds_used,
            "max_rounds": cp.max_rounds,
        }
        if as_json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(f"PASS: campaign '{spec.name}' already completed ({cp.rounds_used}/{cp.max_rounds} rounds)")
        return 0

    exit_code_box: dict[str, int | None] = {"code": None}

    def _verify(exec_root: Path = repo_root) -> tuple[bool, str]:
        argv = shlex.split(node.verify_cmd, posix=(os.name != "nt"))
        if not argv:
            exit_code_box["code"] = 1
            return (False, "empty verify_cmd")
        proc = subprocess.run(
            argv,
            cwd=exec_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=60,
            check=False,
        )
        exit_code_box["code"] = proc.returncode
        detail = (proc.stdout + proc.stderr).strip() or f"exit_code={proc.returncode}"
        return (proc.returncode == 0, detail)

    input_sha256 = cir.compute_slice_input_sha256(node, repo_root)
    if use_worktree or resolved_replay is not None:
        rl = _resolve_crucible_submodule("replay_loop")
        vdiff = rl.execute_replay_verified_slice(
            repo_root,
            node,
            apply_fn=None,
            verify_fn=_verify,
            use_worktree=use_worktree,
            checkpoint=cp,
            trace_path=resolved_replay,
        )
        ok = vdiff.passed and vdiff.replay_verified
        if ok:
            input_sha256 = cp.completed_slices.get(node.id, input_sha256)
            status = "PASS"
        elif vdiff.error.startswith("HALT_MAX_ROUNDS"):
            status = "HALT_MAX_ROUNDS"
        else:
            status = "ROLLED_BACK"
        detail = vdiff.error or "replay verified"
        replay_verified = vdiff.replay_verified
        worktree_used = vdiff.worktree_used
        diff_text = vdiff.diff_text
    else:
        ok, detail = cir.execute_slice_transaction(
            repo_root,
            node,
            apply_fn=lambda: None,
            verify_fn=lambda: _verify(repo_root),
            checkpoint=cp,
        )
        if ok:
            input_sha256 = cp.completed_slices.get(node.id, input_sha256)
            status = "PASS"
        elif detail.startswith("HALT_MAX_ROUNDS"):
            status = "HALT_MAX_ROUNDS"
        else:
            status = "ROLLED_BACK"
        replay_verified = False
        worktree_used = False
        diff_text = ""

    if resolved_cache is not None:
        cir.save_campaign_checkpoint(resolved_cache, cp)

    payload = {
        "ok": ok,
        "slice_id": node.id,
        "input_sha256": input_sha256,
        "exit_code": exit_code_box["code"],
        "status": status,
        "rounds_used": cp.rounds_used,
        "max_rounds": cp.max_rounds,
        "replay_verified": replay_verified,
        "worktree_used": worktree_used,
        "diff_text": diff_text,
    }
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    elif ok:
        print(f"PASS: slice '{node.id}' ({status}, rounds={cp.rounds_used}/{cp.max_rounds}, sha256={input_sha256[:12]})")
    else:
        print(f"BLOCKED: slice '{node.id}' ({status}, rounds={cp.rounds_used}/{cp.max_rounds}): {detail}")
    return 0 if ok else 1


def _campaign_ledger(cir, target_path: Path, last: int, as_json: bool) -> int:
    if isinstance(last, bool) or last < 0:
        msg = f"--last must be >= 0, got {last!r}"
        print(json.dumps({"ok": False, "error": msg}, indent=2, ensure_ascii=False) if as_json else msg, file=sys.stdout if as_json else sys.stderr)
        return 2
    try:
        entries = cir.load_ratchet_ledger(target_path)
    except (OSError, ValueError) as exc:
        msg = f"cannot read ratchet ledger '{target_path}': {exc}"
        print(json.dumps({"ok": False, "error": msg}, indent=2, ensure_ascii=False) if as_json else f"BLOCKED: {msg}")
        return 1

    tail = entries[-last:] if last > 0 else []
    if as_json:
        print(json.dumps({"ok": True, "ledger": str(target_path), "total": len(entries), "showing": len(tail), "entries": [asdict(e) for e in tail]}, indent=2, ensure_ascii=False))
    else:
        print(f"LEDGER: {target_path} (showing {len(tail)} of {len(entries)} entries)")
        for e in tail:
            print(f"  round={e.round_id} | {e.slice_id} | {e.status} | {e.seconds:.2f}s | commit={e.commit_sha or '-'} | {e.timestamp}")
    return 0


def _campaign_audit(
    cir,
    root: Path,
    spec_path: Path,
    ledger_path: Path | None,
    as_json: bool,
) -> int:
    try:
        spec = cir.load_campaign_spec(spec_path)
    except (OSError, cir.CampaignCompileError) as exc:
        errs = exc.errors if isinstance(exc, cir.CampaignCompileError) else [str(exc)]
        return _emit_campaign_errors(errs, "audit", as_json)

    rl = _resolve_crucible_submodule("replay_loop")
    try:
        res = rl.audit_campaign_chain(Path(spec.repo_root), spec, ledger_path=ledger_path)
    except (OSError, ValueError, cir.CampaignCompileError) as exc:
        errs = exc.errors if isinstance(exc, cir.CampaignCompileError) else [str(exc)]
        return _emit_campaign_errors(errs, "audit", as_json)

    if as_json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        status = "PASS" if res["ok"] else "BLOCKED"
        print(
            f"CAMPAIGN AUDIT ({status}): {res['campaign']} | replayed={len(res['replayed_slices'])} | "
            f"retention={sum(1 for r in res['retention'] if r['passed'])}/{len(res['retention'])} | "
            f"learning_eligible={res['learning_eligible']} | violations={len(res['violations'])}"
        )
        for v in res["violations"]:
            print(f"  - {v}")
    return 0 if res["ok"] else 1


def cmd_campaign(
    root: Path,
    query: list[str] | str,
    *,
    as_json: bool = False,
    cache_path: Path | None = None,
    last: int = 10,
    use_worktree: bool = False,
    replay_out: Path | None = None,
) -> int:
    parts = query.split() if isinstance(query, str) else list(query)
    usage_msg = (
        "usage: crucible_gate.py campaign "
        "{compile <spec.json> | plan <spec.json> [--cache <receipts.json>] | "
        "run <spec.json> [--cache <checkpoint.json>] [--worktree] [--replay-out <trace.jsonl>] | "
        "audit <spec.json> [<ledger.tsv>] | ledger <ledger.tsv> [--last N]}"
    )
    if not parts or parts[0] not in ("compile", "plan", "run", "audit", "ledger"):
        print(json.dumps({"ok": False, "error": usage_msg}, indent=2, ensure_ascii=False) if as_json else usage_msg, file=sys.stdout if as_json else sys.stderr)
        return 2
    if parts[0] == "audit":
        if len(parts) not in (2, 3):
            print(json.dumps({"ok": False, "error": usage_msg}, indent=2, ensure_ascii=False) if as_json else usage_msg, file=sys.stdout if as_json else sys.stderr)
            return 2
        cir = _resolve_campaign_ir_module()
        spec_path = _resolve_cli_path(root, parts[1])
        ledger_path = _resolve_cli_path(root, parts[2]) if len(parts) == 3 else None
        return _campaign_audit(cir, root, spec_path, ledger_path, as_json)
    if len(parts) != 2:
        print(json.dumps({"ok": False, "error": usage_msg}, indent=2, ensure_ascii=False) if as_json else usage_msg, file=sys.stdout if as_json else sys.stderr)
        return 2

    action, target_raw = parts[0], parts[1]
    cir = _resolve_campaign_ir_module()
    target_path = _resolve_cli_path(root, target_raw)
    if action == "compile":
        return _campaign_compile(cir, target_path, as_json)
    if action == "plan":
        return _campaign_plan(cir, root, target_path, cache_path, as_json)
    if action == "run":
        return _campaign_run(
            cir,
            root,
            target_path,
            cache_path,
            as_json,
            use_worktree=use_worktree,
            replay_out=replay_out,
        )
    return _campaign_ledger(cir, target_path, last, as_json)


def _load_ram_ml_engine():
    script_dir = str(Path(__file__).resolve().parent)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    import ram_ml_engine
    return ram_ml_engine


def cmd_ml_rank(root: Path, files: list[str], *, as_json: bool = False) -> int:
    eng = _load_ram_ml_engine()
    res = eng.rank_tests_for_changes(root, changed_files=files or None)
    if as_json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0
    print(f"In-RAM ML Test Ranker ({res['elapsed_ms']}ms | source={res['change_source']} | impacted={res['impacted_count']}/{len(res['ranked_tests'])})")
    for item in res["ranked_tests"]:
        tag = "IMPACTED" if item["tier"] == "impacted" else "baseline"
        print(f"  [{tag:<8}] {item['score']:>6.4f}  {item['test_path']}  ({'; '.join(item['reasons'])})")
    return 0


def cmd_ml_review(root: Path, files: list[str], *, as_json: bool = False) -> int:
    eng = _load_ram_ml_engine()
    res = eng.review_changes_in_ram(root, changed_files=files or None)
    if as_json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0
    print(f"In-RAM ML Review ({res['elapsed_ms']}ms | source={res['change_source']} | high_priority={res['high_priority_count']}/{res['files_reviewed']})")
    for item in res["reviewed_files"]:
        print(f"  [{item['review_priority']:>4.2f}] {item['rel_path']}  ({'; '.join(item['signals'])})")
    return 0


def cmd_ml_preflight(root: Path, query: list[str], *, verify_cmd: str = "", as_json: bool = False) -> int:
    eng = _load_ram_ml_engine()
    task_text = " ".join(query).strip()
    res = eng.preflight_outcome_gate(root, task_text=task_text, verify_cmd=verify_cmd)
    if as_json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0 if res["status"] == "READY" else 2
    if res["status"] != "READY":
        print(f"In-RAM ML Preflight ({res['elapsed_ms']}ms): REALIGNMENT_REQUIRED | missing={res['missing']}")
        for p in res["realignment_prompts"]:
            print(f"  - {p}")
        return 2
    print(f"In-RAM ML Preflight ({res['elapsed_ms']}ms): READY | impacted_tests={len(res['impacted_tests'])} | verify={res['verify_cmd']}")
    for step in res["carry_through_plan"]:
        print(f"  {step}")
    return 0


def cmd_ml_curate(root: Path, *, as_json: bool = False) -> int:
    eng = _load_ram_ml_engine()
    res = eng.curate_training_dataset(root)
    if as_json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0 if res["quality_gate_passed"] else 1
    print(
        f"In-RAM ML Curate ({res['elapsed_ms']}ms): raw={res['raw_rows']} -> deduped={res['deduped_rows']} -> "
        f"curated={res['curated_rows']} ({res['fail_rows']} fail, {res['pass_rows']} pass, "
        f"resolved_fails={res['resolved_fail_rows']}) | domains={res['domain_counts']} | "
        f"quality_gate={'PASS' if res['quality_gate_passed'] else 'FAIL'}"
    )
    return 0 if res["quality_gate_passed"] else 1


def cmd_ml_train(root: Path, *, as_json: bool = False) -> int:
    eng = _load_ram_ml_engine()
    ext = eng.extract_transcript_failures(root)
    rank = eng.rank_tests_for_changes(root)
    ho = rank.get("held_out_metrics") or {}
    out = {
        "extraction": ext,
        "model_mode": rank["model_mode"],
        "training_rows": rank["training_rows"],
        "training_accuracy": rank["training_accuracy"],
        "held_out_metrics": ho,
    }
    if as_json:
        print(json.dumps(out, indent=2, ensure_ascii=False))
        return 0
    ho_str = f" | held_out({ho['folds']}f): acc={ho['accuracy']} P={ho['precision']} R={ho['recall']} F1={ho['f1']}" if ho else ""
    print(
        f"In-RAM ML Train ({ext['elapsed_ms']}ms): scanned {ext['conversations_scanned']} conversations -> "
        f"{ext['rows_written']} rows ({ext['fail_rows']} fail, {ext['pass_rows']} pass) | "
        f"mode={rank['model_mode']} train_acc={rank['training_accuracy']}{ho_str}"
    )
    return 0


def cmd_kernel(root: Path, query: list[str], *, as_json: bool = False, autofix: bool = False) -> int:
    script_dir = str(Path(__file__).resolve().parent)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    import crucible_kernel

    outcome = " ".join(query).strip()
    res = crucible_kernel.run_kernel(root, outcome=outcome, autofix=autofix)
    ok_statuses = ("CHECKS_PASSED", "OUTCOME_VERIFIED")
    if as_json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
        return 0 if res["status"] in ok_statuses else 1
    print(
        f"Crucible Kernel ({res['elapsed_ms']}ms): status={res['status']} | outcome_verified={res.get('outcome_verified')} | V={res['potential_v']} "
        f"({res['convergence']}) | dirty_closure={len(res['dirty_closure'])} | "
        f"autofixed={len(res.get('autofixed') or [])} | counterexamples={len(res['counterexamples'])}"
    )
    for cx in res["counterexamples"][:5]:
        print(f"  COUNTEREXAMPLE: {cx}")
    return 0 if res["status"] in ok_statuses else 1


def cmd_ml_daemon(root: Path, query: list[str], *, as_json: bool = False) -> int:
    script_dir = str(Path(__file__).resolve().parent)
    if script_dir not in sys.path:
        sys.path.insert(0, script_dir)
    import ram_ml_daemon

    action = query[0] if query else "status"
    if action == "start":
        out = ram_ml_daemon.start_daemon_background(root)
    elif action == "stop":
        out = ram_ml_daemon.stop_daemon(root)
    elif action == "bench":
        out = ram_ml_daemon.benchmark_hot_daemon(root)
    elif action == "status":
        out = ram_ml_daemon.query_daemon(root, {"cmd": "ping"}) or {"ok": False, "status": "stopped"}
    else:
        print(f"usage: crucible_gate.py ml-daemon {{start|stop|status|bench}}", file=sys.stderr)
        return 2
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0 if out.get("ok") or out.get("stopped") else 1


def cmd_ast_scan(
    root: Path,
    query: list[str],
    *,
    import_root: str = "",
    as_json: bool = False,
) -> int:
    ast_mod = _resolve_crucible_submodule("ast_scanner")
    target_repo = _resolve_cli_path(root, query[0]) if query else root
    res = ast_mod.scan_repo_edges(target_repo, import_root=import_root)
    if as_json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        print(
            f"AST Scan ({res['elapsed_ms']}ms): repo={res['repo_root']} | "
            f"import_root={res['import_root'] or '.'} | units={res['unit_count']} | edges={res['edge_count']}"
        )
    return 0


def cmd_discover(
    root: Path,
    *,
    import_root: str = ".agents/scripts",
    emit_campaign: Path | None = None,
    as_json: bool = False,
) -> int:
    rl = _resolve_crucible_submodule("replay_loop")
    report = rl.discover_gaps(root, import_root=import_root)
    if emit_campaign is not None:
        out_path = _resolve_cli_path(root, emit_campaign)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(report.campaign_spec, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    payload = report.to_dict()
    if as_json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        fail_count = sum(1 for g in report.gaps if g.severity == "FAIL")
        warn_count = sum(1 for g in report.gaps if g.severity == "WARN")
        print(
            f"Discovery ({report.elapsed_ms}ms): units={report.unit_count} | edges={report.edge_count} | "
            f"gaps={len(report.gaps)} (FAIL={fail_count}, WARN={warn_count}) | slices={len(report.campaign_spec.get('slices', []))}"
        )
        for g in report.gaps[:10]:
            print(f"  [{g.severity}] {g.id} ({g.kind}): {g.detail}")
    return 1 if any(g.severity == "FAIL" for g in report.gaps) else 0


def cmd_story(
    root: Path,
    query: list[str],
    *,
    terms: list[str] | None = None,
    max_duration: float = 60.0,
    output_dir: Path | None = None,
    as_json: bool = False,
) -> int:
    se = _resolve_crucible_submodule("story_engine")
    if not query:
        print("usage: crucible_gate.py story {recognize <brief...> | select <transcript> | chg01 <manifest> <transcript> | mcp}", file=sys.stderr)
        return 2
    action = query[0]
    if action == "mcp":
        se.serve_stdio()
        return 0
    if action == "recognize":
        res = se.recognize_form(" ".join(query[1:]))
        print(json.dumps(res, indent=2, ensure_ascii=False) if as_json else f"Story Recognize: form={res['form']} abstained={res['abstained']} craft={res['pinned_craft']}")
        return 0
    if action == "select":
        if len(query) < 2:
            print("usage: crucible_gate.py story select <transcript_path> [--terms ...] [--max-duration 60] [--output-dir <dir>]", file=sys.stderr)
            return 2
        t_path = _resolve_cli_path(root, query[1])
        segs, src_sha = se.load_transcript_segments(t_path)
        q_terms = list(terms or [])
        selection = se.select_story_arc_clips(segs, q_terms, max_duration_sec=max_duration)
        chg01_sha = se.compute_chg01_fingerprint(src_sha, "", q_terms, max_duration)
        out_dir = _resolve_cli_path(root, output_dir) if output_dir is not None else None
        exported = se.export_clip_manifest(selection, t_path, src_sha, chg01_sha, out_dir)
        payload = {"source_sha256": src_sha, "selection": selection, **exported}
        if as_json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            print(
                f"Story Select: clips={len(selection['clips'])} | duration={selection['total_duration_sec']}s | "
                f"arc_complete={selection['story_arc_complete']} | chg01={chg01_sha[:12]}"
            )
        return 0
    if action == "chg01":
        if len(query) < 3:
            print("usage: crucible_gate.py story chg01 <manifest.json> <transcript_path>", file=sys.stderr)
            return 2
        m_path = _resolve_cli_path(root, query[1])
        t_path = _resolve_cli_path(root, query[2])
        manifest = json.loads(m_path.read_text(encoding="utf-8"))
        res = se.check_chg01_invalidation(manifest, t_path)
        print(json.dumps(res, indent=2, ensure_ascii=False) if as_json else f"CHG-01: {res['status']} (stale={res['stale']}, reasons={res['reasons']})")
        return 0 if not res["stale"] else 1
    print(f"unknown story action: {action}", file=sys.stderr)
    return 2


def cmd_g5_check(
    root: Path,
    *,
    ledger_file: Path | None = None,
    target: int = 10,
    as_json: bool = False,
) -> int:
    ol = _resolve_crucible_submodule("outcome_ledger")
    res = ol.verify_g5_ledger_file(root, ledger_file, target=target)
    if as_json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        status = "PASS" if res["passed"] else "BLOCKED"
        print(f"G5 Ledger ({status}): {res['verified_count']}/{res['target']} verified | rejected={len(res['rejected'])} | path={res['ledger_path']}")
    return 0 if res["passed"] else 1


def cmd_bench(
    root: Path,
    query: list[str] | str,
    *,
    bench_mode: str = "offline",
    form_filter: str | None = None,
    rounds: int = 1,
    interval_min: float = 0.0,
    adaptive: bool = False,
    until_exit: bool = False,
    max_minutes: float = 0.0,
    workers: int | None = None,
    no_judge: bool = False,
    project_ids: list[str] | None = None,
    as_json: bool = False,
) -> int:
    wb = _resolve_crucible_submodule("workload_bench")
    parts = query.split() if isinstance(query, str) else list(query)
    action = parts[0] if parts else "run"
    default_yaml = root / ".agents" / "bench" / "workloads.yaml"

    if action not in ("validate", "run", "report", "stop", "fuzz", "audit", "train", "score", "label", "steer", "pull", "trial", "judge", "test-validity", "inspect"):
        msg = "usage: crucible_gate.py bench {validate [<workloads.yaml>] | run [<workloads.yaml>] [--mode offline|all|plumbing|hybrid|agy_live] [--form FORM] [--no-judge] [--rounds N] [--until-exit] [--max-minutes M] [--interval-min M] [--adaptive] [--project ID...] | fuzz [--rounds N] | trial [reset] [--rounds N] | test-validity | inspect | audit <file> <form_id> | judge <file> <form_id> | train | score <file> <form_id> | label <file> <form_id> pass|fail | steer [apply] | pull <lever_id> [form_id] | stop | report [<telemetry.jsonl>]}"
        print(json.dumps({"ok": False, "error": msg}, indent=2) if as_json else msg, file=sys.stdout if as_json else sys.stderr)
        return 2

    if action == "test-validity":
        rae = _resolve_crucible_submodule("root_axis_engine")
        res = rae.verify_test_validity(root)
        if as_json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        else:
            status = "PASS" if res["ok"] else "BLOCKED"
            ont = res["ontology"]
            print(
                f"3-Axis Test-Validity & L0-L4 Ontology Proof ({status}) in {res['elapsed_ms']:.1f}ms: "
                f"ontology=L0({ont['l0_count']})->L1({ont['l1_count']})->L2({ont['l2_count']})->L3({ont['l3_count']})->L4({ont['l4_count']}) | "
                f"red_counterexamples={res['counterexamples_caught']}/{res['counterexamples_total']} | "
                f"golden={res['golden_passed']}/{res['golden_total']}"
            )
            for ce in res["counterexample_details"]:
                tag = "CAUGHT" if ce["caught"] else "MISSED"
                print(f"  [{tag}] {ce['axis_id']} / {ce['engine_id']} ({ce['form_id']}): expected={ce['expected_probe']} got={ce['failed_probes']}")
            if ont.get("errors"):
                print(f"  Ontology errors: {ont['errors']}")
            if res.get("golden_failures"):
                print(f"  Golden failures: {res['golden_failures']}")
        return 0 if res["ok"] else 1

    if action == "inspect":
        rat = _resolve_crucible_submodule("outcome_ratchet")
        res = rat.build_outcome_matrix(root)
        if as_json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        else:
            print(
                f"3-Axis Outcome & Ratchet Dashboard: forms={res['forms_tracked']} | "
                f"experiments={res['total_experiments']} | promoted={res['total_promoted_lessons']} | "
                f"quarantined={res['total_quarantined_lessons']} | bottleneck={res['top_bottleneck']}"
            )
            for fid, f in res["forms"].items():
                lat = f["latest_axes"]
                dlt = f["net_deltas"]
                print(
                    f"  - {fid:<18} runs={f['runs']} sign_offs={f['sign_offs']} | "
                    f"I={lat['axis_1_integrity']:.2f}({dlt['axis_1_integrity']:+.2f}) "
                    f"II={lat['axis_2_rhetorical_force']:.2f}({dlt['axis_2_rhetorical_force']:+.2f}) "
                    f"III={lat['axis_3_executability']:.2f}({dlt['axis_3_executability']:+.2f}) | "
                    f"promoted={f['promoted_count']} quar={f['quarantined_count']} weak_eng={f['top_weakest_engine']}"
                )
        return 0

    if action == "judge":
        if len(parts) < 3:
            msg = "usage: crucible_gate.py bench judge <file_path> <form_id> [--json]"
            print(json.dumps({"ok": False, "error": msg}, indent=2) if as_json else msg, file=sys.stdout if as_json else sys.stderr)
            return 2
        jp = _resolve_crucible_submodule("judgment_panel")
        target_file = _resolve_cli_path(root, parts[1])
        form_id = parts[2]
        if not target_file.is_file():
            msg = f"File not found: {target_file}"
            print(json.dumps({"ok": False, "error": msg}, indent=2) if as_json else msg, file=sys.stdout if as_json else sys.stderr)
            return 1
        text = target_file.read_text(encoding="utf-8", errors="replace")
        jv = jp.run_adversarial_judgment(
            text,
            form_id,
            repo_root=root,
            worker_fn=wb._default_agy_worker,
            timeout_s=90.0,
            persist_lesson=True,
        )
        if as_json:
            print(json.dumps(jv.to_dict(), indent=2, ensure_ascii=False))
        else:
            print(f"Gate 2 Adversarial Judgment ({jv.verdict}): form={form_id} | judgment_score={jv.judgment_score:.2f}")
            if jv.weakest_quote:
                print(f"  Weakest quote:  \"{jv.weakest_quote}\"")
            if jv.top_executive_objection:
                print(f"  #1 Objection:   {jv.top_executive_objection}")
            if jv.required_cut:
                print(f"  Required cut:   {jv.required_cut}")
            if jv.org_voice_flags:
                print(f"  Org/Voice flags:{jv.org_voice_flags}")
            if jv.actionable_fix:
                print(f"  Actionable fix: {jv.actionable_fix}")
            if jv.reusable_judgment_lesson:
                print(f"  Saved lesson:   {jv.reusable_judgment_lesson}")
            if jv.raw_error:
                print(f"  Error:          {jv.raw_error}")
        return 0 if jv.ok else 1

    if action == "trial":
        lc = _resolve_crucible_submodule("lever_control")
        do_reset = len(parts) >= 2 and parts[1].lower() in ("reset", "--reset")
        res = lc.run_offline_trial_loop(root, rounds=max(1, rounds), reset=do_reset)
        if as_json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        else:
            print(
                f"Crucible Non-Redundant Trial Loop ({res['stopped_reason'].upper()}): "
                f"rounds={res['rounds_executed']} | DRR={res['drr']:.2%} (stop>={res['drr_threshold']:.0%}) | "
                f"tested={res['total_trials_ever']}/{res['total_pool_size']} | "
                f"unique_discoveries={res['total_unique_discoveries']} | remaining={res['remaining_frontier']} in {res['elapsed_ms']:.1f}ms"
            )
            for rr in res["rounds"]:
                print(
                    f"  [r{rr['round']:02d}] trials={rr['trials']:<2} new_discoveries={rr['new_discoveries']:<2} "
                    f"yield={rr['novelty_yield']:.1%} DRR={rr['drr']:.1%} "
                    f"(real_fails={rr['real_failures']}, ml_gaps={rr['ml_disagreements']}, survivors={rr['surviving_mutants']})"
                )
            if res.get("rubric_adjustments_by_form"):
                print("  Rubric Adjustments by Document Type:")
                for fid, adj in res["rubric_adjustments_by_form"].items():
                    print(f"    - {fid:<18}: weakest_element={adj['weakest_rubric_element']:<22} | levers={adj['top_adjustment_levers']}")
        return 0

    if action == "steer":
        lc = _resolve_crucible_submodule("lever_control")
        do_apply = len(parts) >= 2 and parts[1].lower() in ("apply", "--apply")
        res = lc.build_steering_packet(root, auto_apply=do_apply)
        if as_json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        else:
            print(res["compact_steering_brief"])
            for lv in res["recommended_levers"]:
                print(f"  -> Lever [{lv['lever_id']}] ({lv['hits']}x): {lv['rule']}")
            if res["applied_levers"]:
                print(f"  APPLIED {len(res['applied_levers'])} lever(s) into .agents/ml_learned_policies.json")
        return 0

    if action == "pull":
        if len(parts) < 2:
            msg = "usage: crucible_gate.py bench pull <lever_id> [form_id] [--json]"
            print(json.dumps({"ok": False, "error": msg}, indent=2) if as_json else msg, file=sys.stdout if as_json else sys.stderr)
            return 2
        lc = _resolve_crucible_submodule("lever_control")
        lever_id = parts[1]
        form_id = parts[2] if len(parts) >= 3 else "all"
        try:
            res = lc.pull_lever(root, lever_id, form_id=form_id)
        except ValueError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2) if as_json else str(exc), file=sys.stdout if as_json else sys.stderr)
            return 2
        if as_json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        else:
            print(f"PULLED LEVER [{res['lever_id']}] -> forms={len(res['updated_forms'])} | rule: {res['policy_rule']}")
        return 0

    if action == "train":
        mls = _resolve_crucible_submodule("doc_ml_scorer")
        res = mls.train_whitebox_model(root, save=True)
        if as_json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        else:
            status = "PASS" if res["ok"] else "WARN"
            print(
                f"Offline 40-Feature White-Box ML Train ({status}): "
                f"samples={res['train_samples']} (human={res['human_label_count']}) | "
                f"holdout_acc={res['holdout_accuracy']:.1%} | F1={res['holdout_f1']:.3f} in {res['elapsed_ms']:.1f}ms"
            )
            print(f"  Top + drivers: {res['top_positive_weights']}")
            print(f"  Top - drivers: {res['top_negative_weights']}")
            print(f"  Model saved:   {res['model_path']}")
        return 0 if res["ok"] else 1

    if action == "score":
        if len(parts) < 3:
            msg = "usage: crucible_gate.py bench score <file_path> <form_id> [--json]"
            print(json.dumps({"ok": False, "error": msg}, indent=2) if as_json else msg, file=sys.stdout if as_json else sys.stderr)
            return 2
        mls = _resolve_crucible_submodule("doc_ml_scorer")
        target_file = _resolve_cli_path(root, parts[1])
        form_id = parts[2]
        if not target_file.is_file():
            msg = f"File not found: {target_file}"
            print(json.dumps({"ok": False, "error": msg}, indent=2) if as_json else msg, file=sys.stdout if as_json else sys.stderr)
            return 1
        text = target_file.read_text(encoding="utf-8", errors="replace")
        res = mls.score_document_ml(text, form_id, repo_root=root)
        if as_json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        else:
            print(
                f"Offline ML Score ({res['verdict']}): form={form_id} | P(buy-in)={res['buy_in_probability']:.1%} | "
                f"flow={res['flow_score']:.2f} | board={res['board_score']:.2f} | blocking_roles={res['blocking_roles']}"
            )
            if res["top_negative_drivers"]:
                neg = ", ".join(f"{d['feature']}({d['contribution']:+.2f})" for d in res["top_negative_drivers"][:4])
                print(f"  Top negative drivers: {neg}")
            if res["top_positive_drivers"]:
                pos = ", ".join(f"{d['feature']}({d['contribution']:+.2f})" for d in res["top_positive_drivers"][:4])
                print(f"  Top positive drivers: {pos}")
            if res["recommended_levers"]:
                print(f"  Recommended Levers:   {res['recommended_levers']}")
        return 0 if res["ok"] else 1

    if action == "label":
        if len(parts) < 4:
            msg = "usage: crucible_gate.py bench label <file_path> <form_id> pass|fail [--json]"
            print(json.dumps({"ok": False, "error": msg}, indent=2) if as_json else msg, file=sys.stdout if as_json else sys.stderr)
            return 2
        mls = _resolve_crucible_submodule("doc_ml_scorer")
        target_file = _resolve_cli_path(root, parts[1])
        form_id = parts[2]
        verdict = parts[3]
        note = " ".join(parts[4:]) if len(parts) > 4 else ""
        try:
            row = mls.append_human_label(root, target_file, form_id, verdict, note=note)
        except ValueError as exc:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2) if as_json else str(exc), file=sys.stdout if as_json else sys.stderr)
            return 2
        if as_json:
            print(json.dumps({"ok": True, "label": row}, indent=2, ensure_ascii=False))
        else:
            print(f"Recorded human label: {row['verdict'].upper()} for {row['file']} ({row['form_id']}) -> run 'bench train' to retrain.")
        return 0

    if action == "fuzz":
        dfe = _resolve_crucible_submodule("doc_flow_engine")
        res = dfe.run_offline_fuzz_suite(rounds=max(1, rounds))
        if as_json:
            print(json.dumps(res, indent=2, ensure_ascii=False))
        else:
            status = "PASS" if res["ok"] else "BLOCKED"
            print(
                f"Crucible Offline Flow & 6-Role Board Fuzzer ({status}): "
                f"evals={res['total_evaluations']} in {res['elapsed_ms']:.1f}ms ({res['evals_per_sec']:.0f}/sec) | "
                f"golden={res['golden_passed']}/{res['golden_total']} (board_ready={res['golden_board_ready']}/{res['golden_total']}) | "
                f"mutants_killed={res['mutants_killed']}/{res['mutants_total']} ({res['kill_rate']:.1%})"
            )
            print(f"  6-Role Blocks Caught: {res['role_blocks_by_role']}")
            if res["golden_failures"]:
                print(f"  Golden failures: {res['golden_failures']}")
            if res["surviving_mutants"]:
                print(f"  Surviving mutants: {res['surviving_mutants']}")
        return 0 if res["ok"] else 1

    if action == "audit":
        if len(parts) < 3:
            msg = "usage: crucible_gate.py bench audit <file_path> <form_id> [--json]"
            print(json.dumps({"ok": False, "error": msg}, indent=2) if as_json else msg, file=sys.stdout if as_json else sys.stderr)
            return 2
        dfe = _resolve_crucible_submodule("doc_flow_engine")
        target_file = _resolve_cli_path(root, parts[1])
        form_id = parts[2]
        if not target_file.is_file():
            msg = f"File not found: {target_file}"
            print(json.dumps({"ok": False, "error": msg}, indent=2) if as_json else msg, file=sys.stdout if as_json else sys.stderr)
            return 1
        text = target_file.read_text(encoding="utf-8", errors="replace")
        flow_res = dfe.evaluate_document_flow(text, form_id)
        board_res = dfe.evaluate_stakeholder_board(text, form_id, flow_eval=flow_res, repo_root=root)
        payload = {"ok": flow_res.passed and board_res.buy_in_ready, "file": str(target_file), "flow": flow_res.to_dict(), "board": board_res.to_dict()}
        if as_json:
            print(json.dumps(payload, indent=2, ensure_ascii=False))
        else:
            status = "BUY-IN READY" if payload["ok"] else "BLOCKED"
            print(f"Offline Flow & 6-Role Audit ({status}): form={form_id} | flow={flow_res.flow_score:.2f} | board={board_res.board_score:.2f} | blocking_roles={board_res.blocking_roles}")
            for rr in board_res.role_reviews:
                tag = f"{rr.verdict:<7} ({rr.relevance})"
                blk = f" | blockers={rr.blockers}" if rr.blockers else ""
                print(f"  [{tag}] {rr.role_title:<34} score={rr.score:.2f}{blk}")
            if board_res.recommended_levers or flow_res.recommended_levers:
                levers = list(dict.fromkeys(flow_res.recommended_levers + board_res.recommended_levers))
                print(f"  Recommended Levers: {levers}")
        return 0 if payload["ok"] else 1

    if action == "stop":
        stop_p = wb.request_bench_stop(root)
        payload = {"ok": True, "stop_file": str(stop_p)}
        print(json.dumps(payload, indent=2) if as_json else f"BENCH STOP REQUESTED: created {stop_p} (active loop will exit cleanly after current item)")
        return 0

    if action == "report":
        tel_path = _resolve_cli_path(root, parts[1]) if len(parts) >= 2 else (root / ".agents" / "bench_telemetry.jsonl")
        summary = wb.summarize_bench_telemetry(tel_path)
        if as_json:
            print(json.dumps(summary, indent=2, ensure_ascii=False))
        else:
            print(
                f"Crucible Bench Report: runs={summary['total_runs']} | pass_rate={summary['pass_rate']:.1%} | "
                f"avg_form_score={summary.get('avg_form_score', 0.0):.3f} | "
                f"planted_canaries={summary['planted_caught']}/{summary['planted_total']} | "
                f"blind_holdout_catches={summary['holdout_catch_count']}"
            )
            if summary.get("avg_score_by_form"):
                print(f"  Form scores: {summary['avg_score_by_form']}")
            if summary["slowest_project"]:
                print(f"  Slowest workload: {summary['slowest_project']} ({summary['slowest_ms']:.1f}ms)")
            if summary["recent_deliverables"]:
                print("  Ready deliverables:")
                for d in summary["recent_deliverables"]:
                    print(f"    - {d}")
            print(f"  #1 Action: {summary['top_recommendation']}")
        return 0

    yaml_path = _resolve_cli_path(root, parts[1]) if len(parts) >= 2 else default_yaml
    try:
        manifest = wb.load_workload_manifest(yaml_path)
    except wb.WorkloadSpecError as exc:
        if as_json:
            print(json.dumps({"ok": False, "errors": exc.errors}, indent=2, ensure_ascii=False))
        else:
            print(f"BENCH INVALID ({yaml_path}): {'; '.join(exc.errors)}", file=sys.stderr)
        return 1

    if action == "validate":
        payload = {
            "ok": True,
            "manifest": str(yaml_path),
            "version": manifest.version,
            "project_count": len(manifest.projects),
            "projects": [p.id for p in manifest.projects],
        }
        print(json.dumps(payload, indent=2, ensure_ascii=False) if as_json else f"BENCH VALID: {len(manifest.projects)} workloads in {yaml_path.name}")
        return 0

    should_stream = (not as_json) and (until_exit or bench_mode in ("all", "agy_live") or rounds > 1)
    stream_progress = (lambda msg: print(msg, flush=True)) if should_stream else None
    if until_exit and not as_json:
        print("Crucible Workload Bench: starting continuous loop (press Ctrl+C or run 'crucible_gate.py bench stop' in another terminal to exit cleanly)...", flush=True)

    eff_workers = workers if (workers is not None and workers >= 1) else (3 if bench_mode in ("all", "agy_live") else 1)
    enable_judge = (not no_judge) and (bench_mode in ("all", "agy_live"))
    res = wb.run_workload_bench(
        root,
        manifest,
        mode_filter=bench_mode,
        form_filter=form_filter,
        project_ids=project_ids,
        rounds=rounds,
        interval_sec=max(0.0, float(interval_min) * 60.0),
        adaptive=adaptive,
        until_exit=until_exit,
        max_minutes=max_minutes,
        workers=eff_workers,
        enable_judgment_gate=enable_judge,
        progress_fn=stream_progress,
    )
    if as_json:
        print(json.dumps(res, indent=2, ensure_ascii=False))
    else:
        status = "PASS" if res["ok"] else "BLOCKED"
        print(
            f"Crucible Workload Bench ({status}): run_id={res['run_id']} | mode={bench_mode} | "
            f"adaptive={adaptive} | rounds={res['rounds_completed']} | stop={res['stopped_reason']} | "
            f"passed={res['passed_count']}/{res['executed_count']} | skipped={res['skipped_count']}"
        )
        if not should_stream:
            for r in res["receipts"]:
                if r["skipped"]:
                    continue
                tag = "PASS" if r["passed"] else f"FAIL({r['failure_category']})"
                if r["planted_total"]:
                    extra = f" [canaries {r['planted_caught']}/{r['planted_total']}]"
                else:
                    esc = f" ESC->L{r['escalated_to']}" if r.get("escalated_to") else ""
                    extra = f" [form={r['form_id']} L{r.get('difficulty_level', 1)} score={r['diagnostic_score']:.2f} weak_el={r.get('weakest_element') or r['weakest_aspect']} arm={r['craft_arm']}{esc}]"
                    if r["deliverable_path"]:
                        extra += f" -> {r['deliverable_path']}"
                print(f"  [r{r['round_idx']}] {r['project_id']} ({r['mode']}): {tag} in {r['total_ms']:.1f}ms{extra}")
        if res["skipped_count"] > 0 and bench_mode == "offline":
            print("  Note: live 'agy_live' workloads skipped in offline mode (pass --mode all to run live agent jobs).")
        print(f"  #1 Telemetry Insight: {res['telemetry_summary']['top_recommendation']}")
    return 0 if res["ok"] else 1


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
        choices=("session-start", "pre-tool", "check", "pre-commit", "route", "doctor", "campaign", "bench", "ast-scan", "discover", "story", "g5-check", "ml-rank", "ml-review", "ml-train", "ml-curate", "ml-preflight", "ml-daemon", "kernel"),
        help="Gate action to execute.",
    )
    parser.add_argument("query", nargs="*", help="Query tokens/ID for 'route', action+target for 'campaign', or paths for 'ml-rank'/'ml-review'.")
    parser.add_argument("--top", type=int, default=5, help="Max matches per category for 'route'.")
    parser.add_argument("--json", action="store_true", help="Emit structured JSON for 'route', 'doctor', or 'campaign'.")
    parser.add_argument("--no-global", action="store_true", help="Skip reading ~/.gemini/config during route/doctor.")
    parser.add_argument("--skip-exec", action="store_true", help="Skip live hook execution during 'doctor'.")
    parser.add_argument("--strict", action="store_true", help="Treat stale depends_on artifacts as blocking failures in 'check'.")
    parser.add_argument("--verbose", action="store_true", help="Show all passing checks in 'doctor'.")
    parser.add_argument("--cache", type=Path, default=None, help="Optional receipt cache JSON path for 'campaign plan'.")
    parser.add_argument("--last", type=int, default=10, help="Number of recent entries to print for 'campaign ledger'.")
    parser.add_argument("--worktree", action="store_true", help="Execute 'campaign run' inside an isolated detached git worktree.")
    parser.add_argument("--replay-out", type=Path, default=None, help="Write replay trace JSONL during 'campaign run'.")
    parser.add_argument("--import-root", type=str, default="", help="Relative import root for 'ast-scan' or 'discover'.")
    parser.add_argument("--emit-campaign", type=Path, default=None, help="Optional CampaignSpec JSON output path for 'discover'.")
    parser.add_argument("--terms", nargs="*", default=None, help="Query terms for 'story select'.")
    parser.add_argument("--max-duration", type=float, default=60.0, help="Max clip duration seconds for 'story select'.")
    parser.add_argument("--output-dir", type=Path, default=None, help="Output directory for 'story select' manifest.")
    parser.add_argument("--file", type=Path, default=None, help="Optional G5 ledger file path for 'g5-check'.")
    parser.add_argument("--target", type=int, default=10, help="Graduation target count for 'g5-check'.")
    parser.add_argument("--verify-cmd", type=str, default="", help="Verification command for 'ml-preflight'.")
    parser.add_argument("--autofix", action="store_true", help="Auto-repair mechanical stale_sha256 hashes in 'kernel'.")
    parser.add_argument("--mode", type=str, default="offline", choices=("offline", "all", "plumbing", "hybrid", "agy_live"), help="Execution mode for 'bench run' (default: offline).")
    parser.add_argument("--rounds", type=int, default=1, help="Number of rounds to execute in 'bench run'.")
    parser.add_argument("--interval-min", type=float, default=0.0, help="Minutes between rounds in 'bench run'.")
    parser.add_argument("--adaptive", action="store_true", help="Enable UCB1 bandit craft selection & diminishing-returns frontier rotation in 'bench run'.")
    parser.add_argument("--until-exit", action="store_true", help="Run 'bench run' continuously until Ctrl+C or 'bench stop'.")
    parser.add_argument("--max-minutes", type=float, default=0.0, help="Optional safety time limit (minutes) for continuous 'bench run'.")
    parser.add_argument("--workers", type=int, default=None, help="Parallel live workers per round in 'bench run' (default: 3 for live modes, 1 for offline).")
    parser.add_argument("--form", type=str, default=None, help="Filter 'bench run' to a single document type (e.g. production_brief, av_script, leadership_report).")
    parser.add_argument("--no-judge", action="store_true", help="Skip Gate 2 independent adversarial judgment panel in 'bench run'.")
    parser.add_argument("--project", action="append", default=None, help="Filter 'bench run' to specific project ID(s).")
    args = parser.parse_args(argv)
    root = args.root.resolve()

    if args.subcommand == "session-start":
        return cmd_session_start(root)
    if args.subcommand == "pre-tool":
        return cmd_pre_tool(root)
    if args.subcommand == "route":
        return cmd_route(root, args.query, top_k=args.top, as_json=args.json, no_global=args.no_global)
    if args.subcommand == "doctor":
        return cmd_doctor(root, as_json=args.json, no_global=args.no_global, skip_exec=args.skip_exec, verbose=args.verbose)
    if args.subcommand == "campaign":
        return cmd_campaign(
            root,
            args.query,
            as_json=args.json,
            cache_path=args.cache,
            last=args.last,
            use_worktree=args.worktree,
            replay_out=args.replay_out,
        )
    if args.subcommand == "bench":
        return cmd_bench(
            root,
            args.query,
            bench_mode=args.mode,
            form_filter=args.form,
            rounds=args.rounds,
            interval_min=args.interval_min,
            adaptive=args.adaptive,
            until_exit=args.until_exit,
            max_minutes=args.max_minutes,
            workers=args.workers,
            no_judge=args.no_judge,
            project_ids=args.project,
            as_json=args.json,
        )
    if args.subcommand == "ast-scan":
        return cmd_ast_scan(root, args.query, import_root=args.import_root, as_json=args.json)
    if args.subcommand == "discover":
        eff_imp = args.import_root or ".agents/scripts"
        return cmd_discover(root, import_root=eff_imp, emit_campaign=args.emit_campaign, as_json=args.json)
    if args.subcommand == "story":
        return cmd_story(
            root,
            args.query,
            terms=args.terms,
            max_duration=args.max_duration,
            output_dir=args.output_dir,
            as_json=args.json,
        )
    if args.subcommand == "g5-check":
        return cmd_g5_check(root, ledger_file=args.file, target=args.target, as_json=args.json)
    if args.subcommand == "ml-rank":
        return cmd_ml_rank(root, args.query, as_json=args.json)
    if args.subcommand == "ml-review":
        return cmd_ml_review(root, args.query, as_json=args.json)
    if args.subcommand == "ml-train":
        return cmd_ml_train(root, as_json=args.json)
    if args.subcommand == "ml-curate":
        return cmd_ml_curate(root, as_json=args.json)
    if args.subcommand == "ml-preflight":
        return cmd_ml_preflight(root, args.query, verify_cmd=args.verify_cmd, as_json=args.json)
    if args.subcommand == "ml-daemon":
        return cmd_ml_daemon(root, args.query, as_json=args.json)
    if args.subcommand == "kernel":
        return cmd_kernel(root, args.query, as_json=args.json, autofix=args.autofix)
    if args.subcommand == "pre-commit":
        return cmd_pre_commit(root, strict=args.strict)
    return cmd_check(root, strict=args.strict)


if __name__ == "__main__":
    raise SystemExit(main())
