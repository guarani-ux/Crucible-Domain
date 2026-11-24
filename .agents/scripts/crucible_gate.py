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


def cmd_session_start(root: Path = ROOT) -> int:
    system_map = "\n".join(
        [
            _build_system_map(root),
            "Spokes: writers-room, story-lane, crucible-observatory | Verify: scripts/verify_all.ps1",
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


def cmd_pre_tool(root: Path = ROOT) -> int:
    payload = _read_stdin_json()
    tool_call = payload.get("toolCall")
    if not isinstance(tool_call, dict) or tool_call.get("name") not in ("write_file", "edit_file"):
        return _emit_decision("allow")

    args = tool_call.get("args")
    target = _extract_target_path(args, root) if isinstance(args, dict) else None
    if target is None:
        return _emit_decision("allow")

    try:
        rel_parts = target.relative_to(root.resolve()).parts
    except ValueError:
        return _emit_decision("allow")

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
    """Verify active plugins and 5-piece crucible/ kernel modules match AGENTS.md and 00_System_Atlas."""
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
    reasons: list[str] = []
    for py_dir in (root / ".agents" / "scripts", root / ".agents" / "scripts" / "crucible"):
        for py_file in sorted(py_dir.glob("*.py")) if py_dir.is_dir() else []:
            try:
                py_compile.compile(str(py_file), doraise=True)
            except (py_compile.PyCompileError, OSError) as exc:
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


def cmd_campaign(
    root: Path,
    query: list[str] | str,
    *,
    as_json: bool = False,
    cache_path: Path | None = None,
    last: int = 10,
) -> int:
    parts = query.split() if isinstance(query, str) else list(query)
    usage_msg = (
        "usage: crucible_gate.py campaign "
        "{compile <spec.json> | plan <spec.json> [--cache <receipts.json>] | ledger <ledger.tsv> [--last N]}"
    )
    if len(parts) != 2 or parts[0] not in ("compile", "plan", "ledger"):
        print(json.dumps({"ok": False, "error": usage_msg}, indent=2, ensure_ascii=False) if as_json else usage_msg, file=sys.stdout if as_json else sys.stderr)
        return 2

    action, target_raw = parts[0], parts[1]
    cir = _resolve_campaign_ir_module()
    target_path = _resolve_cli_path(root, target_raw)
    if action == "compile":
        return _campaign_compile(cir, target_path, as_json)
    if action == "plan":
        return _campaign_plan(cir, root, target_path, cache_path, as_json)
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
        choices=("session-start", "pre-tool", "check", "pre-commit", "route", "doctor", "campaign", "ml-rank", "ml-review", "ml-train", "ml-curate", "ml-preflight", "ml-daemon"),
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
    parser.add_argument("--verify-cmd", type=str, default="", help="Verification command for 'ml-preflight'.")
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
        return cmd_campaign(root, args.query, as_json=args.json, cache_path=args.cache, last=args.last)
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
    return cmd_check(root, strict=args.strict)


if __name__ == "__main__":
    raise SystemExit(main())
