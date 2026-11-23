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
SESSION_BASE_FILENAME = "crucible-session-base"


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


def _git_dir(root: Path = ROOT) -> Path | None:
    rc, out = _git_output(["rev-parse", "--git-dir"], root)
    if rc != 0 or not out.strip():
        return None
    git_dir = Path(out.strip())
    if not git_dir.is_absolute():
        git_dir = root / git_dir
    return git_dir.resolve()


def _record_session_base(root: Path = ROOT) -> None:
    git_dir = _git_dir(root)
    if git_dir is None:
        return
    rc, head_out = _git_output(["rev-parse", "HEAD"], root)
    head_sha = head_out.strip()
    if rc != 0 or not head_sha:
        return
    try:
        (git_dir / SESSION_BASE_FILENAME).write_text(head_sha + "\n", encoding="utf-8")
    except OSError as exc:
        print(f"warning: could not record session base: {exc}", file=sys.stderr)


def _resolve_session_base(root: Path = ROOT) -> tuple[str | None, str | None]:
    git_dir = _git_dir(root)
    if git_dir is not None:
        base_file = git_dir / SESSION_BASE_FILENAME
        if base_file.is_file():
            try:
                candidate = base_file.read_text(encoding="utf-8", errors="replace").strip()
            except OSError as exc:
                print(f"warning: could not read session base: {exc}", file=sys.stderr)
                candidate = ""
            if candidate:
                rc, verified = _git_output(["rev-parse", "--verify", f"{candidate}^{{commit}}"], root)
                if rc == 0 and verified.strip():
                    return verified.strip(), None
    rc, head_out = _git_output(["rev-parse", "HEAD"], root)
    if rc == 0 and head_out.strip():
        return head_out.strip(), None
    return None, "could not resolve session base or git HEAD"


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
            "SHIFTING_SAND: Establish ground truth (workflow, audience, purpose) before proposing deliverables in any [EMPTY — INTAKE REQUIRED] folder.",
            'Gate check: python ".agents/scripts/crucible_gate.py" check',
            'Sync check: python "Project/Inner Gravity/check_sync.py"',
        ]
    )


def cmd_session_start(root: Path = ROOT) -> int:
    _record_session_base(root)
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
    return "app.asana.com" in content.lower()


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

    if _count_files(root / matched_domain) == 0 and target.name.upper() not in GROUND_TRUTH_FILES:
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


def _extract_stage4_section(ideas_text: str) -> str | None:
    lines: list[str] = []
    in_stage4 = False
    for line in ideas_text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            if in_stage4:
                break
            if stripped.startswith("## Stage 4:"):
                in_stage4 = True
            continue
        if in_stage4:
            lines.append(line)
    return "\n".join(lines) if in_stage4 else None


def _extract_contract_block(ideas_text: str) -> tuple[str | None, str | None]:
    stage4 = _extract_stage4_section(ideas_text)
    if stage4 is None:
        return None, None
    in_fence = False
    buf: list[str] = []
    for line in stage4.splitlines():
        stripped = line.strip()
        if not in_fence:
            if stripped == "```contract":
                in_fence = True
            continue
        if stripped == "```":
            return "\n".join(buf), None
        buf.append(line)
    if in_fence:
        return None, "unclosed ```contract block in Stage 4"
    return None, None


def _parse_contract(raw_body: str) -> tuple[dict[str, object] | None, str | None]:
    try:
        parsed = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        return None, f"invalid contract JSON: {exc.msg} (line {exc.lineno})"
    if not isinstance(parsed, dict):
        return None, "contract JSON must be an object"

    intent = parsed.get("intent")
    if not isinstance(intent, str) or not intent.strip():
        return None, "contract 'intent' must be a non-empty string"

    for list_key in ("allowed_paths", "checks"):
        val = parsed.get(list_key)
        if not isinstance(val, list) or not val or not all(isinstance(x, str) and x.strip() for x in val):
            return None, f"contract '{list_key}' must be a non-empty list of strings"

    return parsed, None


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    norm = pattern.strip().replace("\\", "/")
    while norm.startswith("./"):
        norm = norm[2:]
    regex_parts = ["^"]
    idx = 0
    n = len(norm)
    while idx < n:
        if norm[idx : idx + 3] == "**/":
            regex_parts.append("(?:.+/)?")
            idx += 3
        elif norm[idx : idx + 2] == "**":
            regex_parts.append(".*")
            idx += 2
        elif norm[idx] == "*":
            regex_parts.append("[^/]*")
            idx += 1
        elif norm[idx] == "?":
            regex_parts.append("[^/]")
            idx += 1
        else:
            regex_parts.append(re.escape(norm[idx]))
            idx += 1
    regex_parts.append("$")
    return re.compile("".join(regex_parts))


def _path_matches_any(rel_path: str, patterns: list[str]) -> bool:
    return any(_glob_to_regex(pat).match(rel_path) is not None for pat in patterns)


def _collect_changed_files(base_sha: str, root: Path) -> tuple[list[str] | None, str | None]:
    rc_diff, diff_out = _git_output(["-c", "core.quotepath=false", "diff", "--name-only", base_sha], root)
    if rc_diff != 0:
        return None, "git diff against session base failed"
    rc_untracked, untracked_out = _git_output(
        ["-c", "core.quotepath=false", "ls-files", "--others", "--exclude-standard"],
        root,
    )
    if rc_untracked != 0:
        return None, "git ls-files for untracked files failed"

    changed: set[str] = set()
    for chunk in (diff_out, untracked_out):
        for line in chunk.splitlines():
            clean = line.strip().replace("\\", "/")
            if clean:
                changed.add(clean)
    return sorted(changed), None


def _run_contract_checks(checks: list[str], root: Path) -> list[str]:
    failures: list[str] = []
    for cmd in checks:
        proc = subprocess.run(
            cmd,
            cwd=root,
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if proc.returncode != 0:
            combined = "\n".join(part for part in (proc.stdout, proc.stderr) if part)
            tail = "\n".join(combined.splitlines()[-10:]).strip()
            msg = f"check failed (exit {proc.returncode}): {cmd}"
            if tail:
                msg += f"\n{tail}"
            failures.append(msg)
    return failures


def _has_active_contract(root: Path = ROOT) -> bool:
    ideas_path = root / "IDEAS.md"
    if ideas_path.is_file():
        wt_raw, wt_err = _extract_contract_block(ideas_path.read_text(encoding="utf-8", errors="replace"))
        if wt_err is not None or wt_raw is not None:
            return True
    base_sha, _ = _resolve_session_base(root)
    if base_sha:
        rc, base_ideas = _git_output(["show", f"{base_sha}:IDEAS.md"], root)
        if rc == 0:
            base_raw, base_err = _extract_contract_block(base_ideas)
            if base_err is not None or base_raw is not None:
                return True
    return False


def _verify_contract(root: Path = ROOT) -> tuple[bool, str]:
    ideas_path = root / "IDEAS.md"
    if not ideas_path.is_file():
        return False, "IDEAS.md missing"

    wt_text = ideas_path.read_text(encoding="utf-8", errors="replace")
    wt_raw, wt_err = _extract_contract_block(wt_text)
    if wt_err is not None:
        return False, wt_err

    base_sha, base_err = _resolve_session_base(root)
    if base_err or not base_sha:
        return False, base_err or "could not resolve session base"

    rc_base, base_ideas = _git_output(["show", f"{base_sha}:IDEAS.md"], root)
    base_raw, _ = _extract_contract_block(base_ideas) if rc_base == 0 else (None, None)

    if wt_raw is None:
        if rc_base == 0 and base_raw is not None:
            return False, "contract changed mid-session; Levi must approve and commit it."
        return False, "no ```contract block in Stage 4 of IDEAS.md"

    if rc_base != 0 or base_raw is None:
        return False, "contract changed mid-session; Levi must approve and commit it."

    wt_contract, wt_parse_err = _parse_contract(wt_raw)
    base_contract, base_parse_err = _parse_contract(base_raw)
    if wt_contract is not None and base_contract is not None:
        if wt_contract != base_contract:
            return False, "contract changed mid-session; Levi must approve and commit it."
    else:
        if wt_raw.strip() != base_raw.strip():
            return False, "contract changed mid-session; Levi must approve and commit it."
        if wt_parse_err is not None:
            return False, wt_parse_err
        if base_parse_err is not None:
            return False, base_parse_err

    assert wt_contract is not None
    allowed_paths = [str(p) for p in wt_contract["allowed_paths"]]  # type: ignore[index]
    checks = [str(c) for c in wt_contract["checks"]]  # type: ignore[index]

    changed, diff_err = _collect_changed_files(base_sha, root)
    if diff_err or changed is None:
        return False, diff_err or "could not collect changed files"

    out_of_scope = [path for path in changed if not _path_matches_any(path, allowed_paths)]
    if out_of_scope:
        return False, f"out-of-scope files: {', '.join(out_of_scope)}"

    failures = _run_contract_checks(checks, root)
    if failures:
        return False, "\n".join(failures)

    return True, f"contract verified ({len(checks)} checks passed, {len(changed)} changed file(s) in scope)"


def cmd_check(root: Path = ROOT) -> int:
    print(_build_system_map(root))
    reasons: list[str] = []

    if not (root / "IDEAS.md").is_file():
        reasons.append("IDEAS.md missing")

    rc, diff_out = _git_output(["diff", "--cached", "--name-only"], root)
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


def cmd_verify(root: Path = ROOT) -> int:
    ok, summary = _verify_contract(root)
    prefix = "PASS" if ok else "BLOCKED"
    print(f"{prefix}: {summary}")
    return 0 if ok else 1


def cmd_stop(root: Path = ROOT) -> int:
    payload = _read_stdin_json()
    if payload.get("terminationReason") not in ("NO_TOOL_CALL", "model_stop", None):
        print(json.dumps({"decision": "allow"}))
        return 0

    attempt = payload.get("executionNum", 0)
    if not isinstance(attempt, int) or isinstance(attempt, bool) or attempt >= 3:
        print(json.dumps({"decision": "allow"}))
        return 0

    if not _has_active_contract(root):
        print(json.dumps({"decision": "allow"}))
        return 0

    ok, summary = _verify_contract(root)
    if ok:
        print(json.dumps({"decision": "allow"}))
    else:
        print(json.dumps({"decision": "continue", "reason": f"Contract Stop Gate BLOCKED: {summary}"}, ensure_ascii=False))
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
            "verify",
            "stop",
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
    if args.subcommand == "verify":
        return cmd_verify(root)
    if args.subcommand == "stop":
        return cmd_stop(root)
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
