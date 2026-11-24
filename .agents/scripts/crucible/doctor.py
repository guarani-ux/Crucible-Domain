"""Closed-loop workspace and host reachability doctor for Crucible Domain."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

from .indexer import build_index, validate_primitives_registry
from .models import (
    BARE_URL_RE,
    CANONICAL_LOCAL_FIRST_FILES,
    DEFAULT_GLOBAL_CONFIG_DIR,
    MD_LINK_RE,
    CapabilityIndex,
    DiagnosticFinding,
    DoctorReport,
)


def _extract_python_script_arg(cmd: str) -> str | None:
    m = re.search(r'\bpython(?:3)?(?:\.exe)?\s+(?:"([^"]+)"|(\S+))', cmd or "")
    if not m:
        return None
    return (m.group(1) or m.group(2)).strip()


def _probe_hook_command(cmd: str, cwd: Path, event_name: str) -> tuple[bool, str]:
    probe_payloads = {
        "SessionStart": json.dumps({"conversationId": "doctor-probe", "workspacePaths": [str(cwd)]}),
        "PreInvocation": json.dumps({"conversationId": "doctor-probe", "lastUserInput": "doctor health check"}),
        "PreToolUse": json.dumps(
            {
                "conversationId": "doctor-probe",
                "workspacePaths": [str(cwd)],
                "toolCall": {"name": "read_file", "args": {"Path": str(cwd / "README.md")}},
            }
        ),
        "Stop": json.dumps({"terminationReason": "USER_CANCELED", "executionNum": 0}),
    }
    if event_name not in probe_payloads:
        return True, "path exists (skipped live execution for PostToolUse)"
    proc = subprocess.run(
        cmd,
        cwd=cwd,
        shell=True,
        input=probe_payloads[event_name],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=5,
        check=False,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "").strip().splitlines()[-1:]
        detail = err[0] if err else f"exit {proc.returncode}"
        return False, f"exited {proc.returncode}: {detail}"
    out = proc.stdout.strip()
    if out:
        try:
            parsed = json.loads(out)
            if not isinstance(parsed, dict):
                return False, "hook stdout JSON is not an object"
        except json.JSONDecodeError as exc:
            return False, f"hook stdout is not valid JSON: {exc.msg}"
    return True, "executed cleanly from real cwd and emitted valid JSON"


def _audit_hooks(
    root: Path,
    global_config_dir: Path | None,
    execute_hooks: bool,
    findings: list[DiagnosticFinding],
) -> dict[str, int]:
    hook_files: list[Path] = [root / ".agents" / "hooks.json"]
    plugins_dir = root / ".agents" / "plugins"
    if plugins_dir.is_dir():
        hook_files.extend(sorted(plugins_dir.glob("*/hooks.json")))
    if global_config_dir is not None:
        if not global_config_dir.is_dir():
            findings.append(
                DiagnosticFinding(
                    category="portability",
                    severity="INFO",
                    subject=str(global_config_dir),
                    detail="global config dir absent; workspace-only hook audit ran",
                )
            )
        elif (global_config_dir / "hooks.json").is_file():
            hook_files.append(global_config_dir / "hooks.json")

    counts = {"checked": 0, "failed": 0, "disabled": 0}
    crucible_wired_events: set[str] = set()

    for hf in hook_files:
        if not hf.is_file():
            findings.append(
                DiagnosticFinding(
                    category="hooks",
                    severity="WARN",
                    subject=str(hf),
                    detail="hooks.json not found",
                )
            )
            continue
        try:
            data = json.loads(hf.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            findings.append(
                DiagnosticFinding(
                    category="hooks",
                    severity="FAIL",
                    subject=str(hf),
                    detail=f"invalid hooks.json: {exc}",
                )
            )
            counts["failed"] += 1
            continue

        hook_cwd = hf.parent
        rel_hf = str(hf.relative_to(root)).replace("\\", "/") if hf.is_relative_to(root) else str(hf)
        for hook_name, hook_cfg in data.items():
            if not isinstance(hook_cfg, dict):
                continue
            if hook_cfg.get("enabled", True) is False:
                counts["disabled"] += 1
                continue
            for ev in ("SessionStart", "PreInvocation", "PostInvocation", "PreToolUse", "PostToolUse", "Stop"):
                is_grouped = ev in ("PreToolUse", "PostToolUse")
                for entry in hook_cfg.get(ev) or []:
                    if not isinstance(entry, dict):
                        counts["failed"] += 1
                        findings.append(
                            DiagnosticFinding(
                                category="hooks",
                                severity="FAIL",
                                subject=f"{rel_hf}::{hook_name}.{ev}",
                                detail=f"{ev} entry must be a JSON object, got {type(entry).__name__}",
                            )
                        )
                        continue
                    if is_grouped and "hooks" not in entry:
                        counts["failed"] += 1
                        findings.append(
                            DiagnosticFinding(
                                category="hooks",
                                severity="FAIL",
                                subject=f"{rel_hf}::{hook_name}.{ev}",
                                detail=f"{ev} requires grouped {{matcher, hooks}} object, got flat handler",
                            )
                        )
                        continue
                    if not is_grouped and ("hooks" in entry or "matcher" in entry):
                        counts["failed"] += 1
                        findings.append(
                            DiagnosticFinding(
                                category="hooks",
                                severity="FAIL",
                                subject=f"{rel_hf}::{hook_name}.{ev}",
                                detail=f"{ev} requires flat handler objects (no 'matcher'/'hooks' wrapper)",
                            )
                        )
                        continue
                    cmds = (
                        [h.get("command", "") for h in entry.get("hooks", [])]
                        if is_grouped
                        else [entry.get("command", "")]
                    )
                    for cmd in cmds:
                        counts["checked"] += 1
                        if hf == root / ".agents" / "hooks.json":
                            crucible_wired_events.add(ev)
                        script_arg = _extract_python_script_arg(cmd)
                        if script_arg is not None:
                            sp = Path(script_arg)
                            resolved = sp if sp.is_absolute() else (hook_cwd / sp).resolve()
                            if not resolved.is_file():
                                counts["failed"] += 1
                                findings.append(
                                    DiagnosticFinding(
                                        category="hooks",
                                        severity="FAIL",
                                        subject=f"{rel_hf}::{hook_name}.{ev}",
                                        detail=f"command '{cmd}' from cwd='{hook_cwd}' resolves to missing '{resolved}'",
                                        remediation="Use relative 'scripts/crucible_gate.py ...' inside .agents/hooks.json.",
                                    )
                                )
                                continue
                        if execute_hooks:
                            ok, msg = _probe_hook_command(cmd, hook_cwd, ev)
                            if not ok:
                                counts["failed"] += 1
                                findings.append(
                                    DiagnosticFinding(
                                        category="hooks",
                                        severity="FAIL",
                                        subject=f"{rel_hf}::{hook_name}.{ev}",
                                        detail=msg,
                                    )
                                )
                                continue
                        findings.append(
                            DiagnosticFinding(
                                category="hooks",
                                severity="PASS",
                                subject=f"{rel_hf}::{hook_name}.{ev}",
                                detail=f"ok from cwd='{hook_cwd}'",
                            )
                        )

    missing_events = {"SessionStart", "PreToolUse"} - crucible_wired_events
    if missing_events:
        findings.append(
            DiagnosticFinding(
                category="hooks",
                severity="WARN",
                subject=".agents/hooks.json",
                detail=f"crucible_gate.py events not wired: {', '.join(sorted(missing_events))}",
                remediation="Wire SessionStart and PreToolUse in .agents/hooks.json.",
            )
        )
    return counts


def _audit_links_and_bindings(root: Path, index: CapabilityIndex, findings: list[DiagnosticFinding]) -> dict[str, int]:
    chatgpt_bound = 0
    chatgpt_external = 0
    chatgpt_unbound = 0
    drive_total = 0

    if (root / "Knowledge").is_dir():
        for sid, bstatus in index.chatgpt_bindings.items():
            if not bstatus.ok:
                findings.append(
                    DiagnosticFinding(
                        category="bindings",
                        severity="FAIL",
                        subject=f"chatgpt_skill:{sid}",
                        detail=f"'{bstatus.label}' missing local target(s): {', '.join(bstatus.missing_targets)}",
                    )
                )

    for md_file in sorted(root.rglob("*.md")):
        if ".git" in md_file.parts:
            continue
        text = md_file.read_text(encoding="utf-8", errors="replace")
        rel = str(md_file.relative_to(root)).replace("\\", "/")

        for url in BARE_URL_RE.findall(text):
            if "drive.google.com" in url:
                drive_total += 1
            elif "chatgpt.com" in url or "chat.openai.com" in url:
                parsed = urlparse(url)
                qs = parse_qs(parsed.query)
                if parsed.path.startswith("/skills") and "skill_id" in qs:
                    sid = qs["skill_id"][0].lower()
                    bstatus = index.chatgpt_bindings.get(sid)
                    if bstatus and bstatus.ok:
                        chatgpt_bound += 1
                    else:
                        chatgpt_unbound += 1
                        findings.append(
                            DiagnosticFinding(
                                category="links",
                                severity="FAIL",
                                subject=rel,
                                detail=f"unbound ChatGPT skill URL: {url}",
                                remediation="Add local binding in CHATGPT_SKILL_BINDINGS or replace with local relative path.",
                            )
                        )
                else:
                    chatgpt_external += 1

        if rel in CANONICAL_LOCAL_FIRST_FILES:
            broken_local: list[str] = []
            for _, target in MD_LINK_RE.findall(text):
                if target.startswith(("http://", "https://", "mailto:", "#")):
                    continue
                clean_target = unquote(target.split("#", 1)[0])
                target_path = (md_file.parent / clean_target).resolve()
                if not target_path.exists():
                    domain_name = clean_target.strip("/")
                    if (
                        rel == "README.md"
                        and domain_name in {"Calgary Public Library", "Personal Work", "Graphs"}
                        and target_path == (root / domain_name).resolve()
                    ):
                        findings.append(
                            DiagnosticFinding(
                                category="portability",
                                severity="INFO",
                                subject=rel,
                                detail=f"empty domain directory absent in fresh checkout: {target}",
                            )
                        )
                        continue
                    broken_local.append(target)
            if broken_local:
                findings.append(
                    DiagnosticFinding(
                        category="links",
                        severity="FAIL",
                        subject=rel,
                        detail=f"broken local Markdown links: {', '.join(broken_local)}",
                    )
                )
            else:
                findings.append(
                    DiagnosticFinding(
                        category="links",
                        severity="PASS",
                        subject=rel,
                        detail="all local relative Markdown links resolve on disk",
                    )
                )

    if chatgpt_unbound == 0:
        findings.append(
            DiagnosticFinding(
                category="bindings",
                severity="PASS",
                subject="chatgpt-skills",
                detail=f"all {chatgpt_bound} ChatGPT skill link occurrences map to verified local files ({chatgpt_external} receipt URL(s) marked external-only)",
            )
        )
    return {
        "chatgpt_bound": chatgpt_bound,
        "chatgpt_external_only": chatgpt_external,
        "chatgpt_unbound": chatgpt_unbound,
        "drive_links": drive_total,
    }


def _audit_duplicates_and_storage(
    root: Path,
    global_config_dir: Path | None,
    findings: list[DiagnosticFinding],
) -> dict[str, Any]:
    metrics: dict[str, Any] = {}

    # 1. Media Agency duplicate copy check
    k_ma = root / "Knowledge" / "Media Agency"
    p_ma = root / "Project" / "Media Agency"
    identical = 0
    diverged: list[str] = []
    if k_ma.is_dir() and p_ma.is_dir():
        for pf in sorted(p_ma.glob("*.md")):
            kf = k_ma / pf.name
            if not kf.is_file():
                continue
            kh = hashlib.sha256(kf.read_bytes()).hexdigest()
            ph = hashlib.sha256(pf.read_bytes()).hexdigest()
            if kh == ph:
                identical += 1
            else:
                diverged.append(pf.name)
    metrics["media_agency_identical"] = identical
    metrics["media_agency_diverged"] = len(diverged)
    if diverged:
        findings.append(
            DiagnosticFinding(
                category="duplicates",
                severity="WARN",
                subject="Project/Media Agency vs Knowledge/Media Agency",
                detail=f"{len(diverged)} duplicate file(s) diverged ({identical} identical), creating split-brain edits",
                remediation="Designate Knowledge/Media Agency as canonical and replace or archive the stale Project/Media Agency copy.",
            )
        )

    # 2. Drive lock dirs inside git working tree
    drive_locks = [name for name in (".tmp.drivedownload", ".tmp.driveupload") if (root / name).exists()]
    metrics["drive_sync_locks"] = drive_locks
    if drive_locks:
        findings.append(
            DiagnosticFinding(
                category="storage",
                severity="WARN",
                subject=",".join(drive_locks),
                detail="Drive sync temp folders present inside Git repo (Git + OneDrive + Drive concurrency risk)",
            )
        )

    # 3. Root governance files
    missing_root = [name for name in ("AGENTS.md", ".agents/acceptance.lock.json") if not (root / name).is_file()]
    metrics["missing_root_governance"] = missing_root
    if missing_root:
        if "AGENTS.md" in missing_root:
            rem = "Restore AGENTS.md at the repository root."
        else:
            rem = "Restore .agents/acceptance.lock.json to enforce required_files and python_syntax."
        findings.append(
            DiagnosticFinding(
                category="governance",
                severity="WARN",
                subject="root",
                detail=f"missing protected governance files: {', '.join(missing_root)}",
                remediation=rem,
            )
        )

    # 4. Global Antigravity config hygiene (read-only observations)
    if global_config_dir and global_config_dir.is_dir():
        is_git = (global_config_dir / ".git").exists()
        bak_files = [p.name for p in global_config_dir.iterdir() if p.is_file() and (".bak" in p.name or "backup" in p.name)]
        scripts_bak = [p.name for p in (global_config_dir / "scripts").glob("*.bak*") if (global_config_dir / "scripts").is_dir()]
        dead_js = (global_config_dir / "scripts" / "pre_tool_guard.js").is_file()

        dup_mcps: list[str] = []
        mcp_path = global_config_dir / "mcp_config.json"
        cfg_path = global_config_dir / "config.json"
        if mcp_path.is_file() and cfg_path.is_file():
            try:
                mcp_servers = set((json.loads(mcp_path.read_text(encoding="utf-8")).get("mcpServers") or {}).keys())
                plugins = json.loads(cfg_path.read_text(encoding="utf-8")).get("plugins") or {}
                enabled_plugins = {k for k, v in plugins.items() if isinstance(v, dict) and v.get("enabled", True)}
                dup_mcps = sorted(mcp_servers & enabled_plugins)
            except (OSError, json.JSONDecodeError):
                pass

        metrics["global_config_git"] = is_git
        metrics["global_bak_count"] = len(bak_files) + len(scripts_bak)
        metrics["global_dup_mcps"] = dup_mcps
        if not is_git or bak_files or scripts_bak or dead_js or dup_mcps:
            findings.append(
                DiagnosticFinding(
                    category="host_config",
                    severity="WARN",
                    subject=str(global_config_dir),
                    detail=(
                        f"git={is_git}, bak_files={len(bak_files) + len(scripts_bak)}, "
                        f"unreferenced_pre_tool_guard_js={dead_js}, duplicate_mcp_entries={dup_mcps}"
                    ),
                )
            )
    return metrics


def run_doctor(
    root: Path,
    *,
    global_config_dir: Path | None = DEFAULT_GLOBAL_CONFIG_DIR,
    execute_hooks: bool = True,
) -> DoctorReport:
    """Run closed-loop verification over hooks, bindings, links, duplicates, and storage."""
    root = root.resolve()
    index = build_index(root, global_config_dir=global_config_dir)
    findings: list[DiagnosticFinding] = []

    hook_metrics = _audit_hooks(root, global_config_dir, execute_hooks, findings)
    link_metrics = _audit_links_and_bindings(root, index, findings)
    storage_metrics = _audit_duplicates_and_storage(root, global_config_dir, findings)
    primitive_count = validate_primitives_registry(root, findings)

    metrics: dict[str, Any] = {
        "index_build_ms": round(index.build_ms, 2),
        "indexed_total": len(index.entries),
        "indexed_counts": index.counts_by_kind,
        "primitives_validated": primitive_count,
        "skill_frontmatter_bytes": index.skill_frontmatter_bytes,
        **hook_metrics,
        **link_metrics,
        **storage_metrics,
    }
    return DoctorReport(root=str(root), findings=findings, metrics=metrics)


def _format_doctor_text(report: DoctorReport, *, verbose: bool = False) -> str:
    m = report.metrics
    lines = [
        f"Crucible Doctor ({report.root})",
        (
            f"Index: {m['indexed_total']} capabilities in {m['index_build_ms']}ms "
            f"(procedures={m['indexed_counts'].get('procedure', 0)}, "
            f"roles={m['indexed_counts'].get('role', 0)}, "
            f"knowledge={m['indexed_counts'].get('knowledge', 0)}, "
            f"projects={m['indexed_counts'].get('project', 0)}, "
            f"exhibits={m['indexed_counts'].get('exhibit', 0)}, "
            f"skills={m['indexed_counts'].get('skill', 0)}, "
            f"skill_frontmatter={m['skill_frontmatter_bytes']}B)"
        ),
        f"Checks: {report.pass_count} PASS | {report.warn_count} WARN | {report.fail_count} FAIL",
        "",
    ]
    for f in report.findings:
        if not verbose and f.severity == "PASS":
            continue
        lines.append(f"[{f.severity}] {f.category} · {f.subject}: {f.detail}")
        if f.remediation:
            lines.append(f"       fix -> {f.remediation}")
    return "\n".join(lines)
