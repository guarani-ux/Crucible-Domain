"""Deterministic GitHub repository sieve (`melt-diff` and no-clone `melt-scan`)."""

from __future__ import annotations

import base64
import json
import re
import subprocess
from pathlib import Path
from typing import Any

from .models import (
    ACTIVE_HUB_REPOS,
    ASSET_OR_BINARY_EXTS,
    CODE_EXTS,
    ENTRYPOINT_BASENAMES,
    IGNORED_TREE_DIRS,
    MANIFEST_FILENAMES,
    MAX_MELT_SCAN_REPOS,
    MAX_README_EXCERPT_CHARS,
    MAX_SAMPLE_PATHS,
    MAX_STDOUT_BYTES_PER_REPO,
    MONTH_NAME_TO_NUM,
    STUB_DISK_KB_THRESHOLD,
)


def _discover_melted_exhibits(root: Path) -> tuple[dict[str, dict[str, str]], str]:
    """Return mapping of lowercase repo slug -> exhibit metadata and intake ISO date."""
    arch_dir = root / "Knowledge" / "Repository Archaeology"
    exhibit_date = "2026-11-15"
    index_md = arch_dir / "00-Exhibit_Index.md"
    if index_md.is_file():
        head_text = index_md.read_text(encoding="utf-8", errors="replace")[:600]
        m_date = re.search(
            r"\b(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s*(\d{4})\b",
            head_text,
            re.IGNORECASE,
        )
        if m_date:
            month_num = MONTH_NAME_TO_NUM[m_date.group(1).lower()]
            day_num = f"{int(m_date.group(2)):02d}"
            exhibit_date = f"{m_date.group(3)}-{month_num}-{day_num}"

    melted: dict[str, dict[str, str]] = {}
    if not arch_dir.is_dir():
        return melted, exhibit_date

    for md_file in sorted(arch_dir.glob("*.md")):
        if md_file.name.startswith("00-"):
            continue
        m_name = re.match(r"^(\d{2})-(.+)\.md$", md_file.name)
        if not m_name:
            continue
        ex_id = f"A{m_name.group(1)}"
        slug = m_name.group(2).strip().lower()
        rel_path = md_file.relative_to(root).as_posix()
        melted[slug] = {
            "exhibit_id": ex_id,
            "slug": slug,
            "path": rel_path,
            "exhibit_date": exhibit_date,
        }
    return melted, exhibit_date


def _discover_registered_github_repos(root: Path) -> set[str]:
    """Return lowercase GitHub repo names listed in Project/Project_Register.md."""
    reg_file = root / "Project" / "Project_Register.md"
    if not reg_file.is_file():
        return set()
    text = reg_file.read_text(encoding="utf-8", errors="replace")
    found: set[str] = set()
    for match in re.finditer(r"https://github\.com/[^/\s)]+/([^/\s)#]+)", text):
        found.add(match.group(1).strip().lower())
    return found


def fetch_github_repos(owner: str = "guarani-ux", timeout_sec: int = 15) -> list[dict[str, Any]]:
    """Fetch repository inventory via read-only `gh repo list`."""
    proc = subprocess.run(
        [
            "gh",
            "repo",
            "list",
            owner,
            "--limit",
            "200",
            "--json",
            "name,description,isPrivate,isArchived,pushedAt,primaryLanguage,diskUsage",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_sec,
        check=False,
    )
    if proc.returncode != 0:
        err = (proc.stderr or proc.stdout or "gh repo list failed").strip()
        raise RuntimeError(f"gh repo list failed (rc={proc.returncode}): {err[:240]}")
    data = json.loads(proc.stdout or "[]")
    if not isinstance(data, list):
        raise RuntimeError("gh repo list did not return a JSON array")
    return data


def compute_melt_diff(
    root: Path,
    repos_data: list[dict[str, Any]],
) -> dict[str, Any]:
    """Deterministically subtract already-melted exhibits and hubs from GitHub inventory."""
    melted_map, exhibit_date = _discover_melted_exhibits(root)
    registered = _discover_registered_github_repos(root)

    melted: list[dict[str, Any]] = []
    stale_melted: list[dict[str, Any]] = []
    active_hubs: list[dict[str, Any]] = []
    unmelted: list[dict[str, Any]] = []
    skip_stubs: list[dict[str, Any]] = []

    sorted_repos = sorted(
        repos_data,
        key=lambda r: (str(r.get("pushedAt") or ""), str(r.get("name") or "").lower()),
        reverse=True,
    )

    for raw in sorted_repos:
        name = str(raw.get("name") or "").strip()
        if not name:
            continue
        norm = name.lower()
        pushed_at = str(raw.get("pushedAt") or "")[:10]
        disk_kb = int(raw.get("diskUsage") or 0)
        is_archived = bool(raw.get("isArchived"))
        is_private = bool(raw.get("isPrivate"))
        lang_obj = raw.get("primaryLanguage")
        language = str(lang_obj.get("name") or "-") if isinstance(lang_obj, dict) else "-"
        description = str(raw.get("description") or "").strip()[:160]
        in_register = norm in registered

        base_row: dict[str, Any] = {
            "name": name,
            "pushed_date": pushed_at,
            "language": language,
            "disk_kb": disk_kb,
            "visibility": "archived" if is_archived else ("private" if is_private else "public"),
            "in_project_register": in_register,
            "description": description,
        }

        if norm in melted_map:
            ex = melted_map[norm]
            is_stale = bool(pushed_at and pushed_at > ex["exhibit_date"])
            status = "STALE_MELTED" if is_stale else "MELTED"
            row = {
                **base_row,
                "status": status,
                "exhibit_id": ex["exhibit_id"],
                "exhibit_path": ex["path"],
                "exhibit_date": ex["exhibit_date"],
            }
            if is_stale:
                stale_melted.append(row)
            else:
                melted.append(row)
        elif norm in ACTIVE_HUB_REPOS:
            active_hubs.append({**base_row, "status": "ACTIVE_HUB"})
        elif is_archived or disk_kb <= STUB_DISK_KB_THRESHOLD:
            reason = "archived" if is_archived else f"disk_kb={disk_kb}<={STUB_DISK_KB_THRESHOLD}"
            skip_stubs.append({**base_row, "status": "SKIP_STUB", "skip_reason": reason})
        else:
            unmelted.append({**base_row, "status": "UNMELTED"})

    melted.sort(key=lambda r: str(r.get("exhibit_id") or ""))
    stale_melted.sort(key=lambda r: str(r.get("exhibit_id") or ""))

    return {
        "root": str(root.resolve()),
        "exhibit_baseline_date": exhibit_date,
        "counts": {
            "total_github": len(sorted_repos),
            "melted": len(melted),
            "stale_melted": len(stale_melted),
            "active_hub": len(active_hubs),
            "unmelted": len(unmelted),
            "skip_stub": len(skip_stubs),
            "unregistered_on_github": sum(
                1 for r in (unmelted + skip_stubs + active_hubs) if not r["in_project_register"]
            ),
        },
        "stale_melted": stale_melted,
        "melted": melted,
        "active_hub": active_hubs,
        "unmelted": unmelted,
        "skip_stub": skip_stubs,
    }


def _format_melt_diff_text(report: dict[str, Any]) -> str:
    c = report["counts"]
    lines = [
        f"Crucible Melt Diff (baseline={report['exhibit_baseline_date']})",
        (
            f"GitHub Total: {c['total_github']} | Melted: {c['melted']} | Stale Melted: {c['stale_melted']} | "
            f"Active Hub: {c['active_hub']} | Unmelted Queue: {c['unmelted']} | Auto-Skip Stubs: {c['skip_stub']}"
        ),
    ]
    if report["stale_melted"]:
        lines.append("\n[STALE_MELTED] Pushed after exhibit date (re-verify changes):")
        for r in report["stale_melted"]:
            lines.append(
                f"  - {r['exhibit_id']} {r['name']} (pushed={r['pushed_date']} > {r['exhibit_date']}, {r['disk_kb']}KB)"
            )
    lines.append(f"\n[UNMELTED] High-signal candidates ({len(report['unmelted'])}):")
    for idx, r in enumerate(report["unmelted"], 1):
        reg_tag = "" if r["in_project_register"] else " [NEW_ON_GITHUB]"
        desc = f" — {r['description']}" if r["description"] else ""
        lines.append(
            f"  {idx:2d}. {r['name']:26s} | {r['pushed_date']} | {r['language']:10s} | {r['disk_kb']:7d}KB{reg_tag}{desc}"
        )
    if report["skip_stub"]:
        stub_names = ", ".join(f"{r['name']}({r['disk_kb']}KB)" for r in report["skip_stub"])
        lines.append(f"\n[SKIP_STUB] ({len(report['skip_stub'])}): {stub_names}")
    return "\n".join(lines)


def _clean_readme_excerpt(readme_text: str) -> str:
    """Return a compact, single-line excerpt <= MAX_README_EXCERPT_CHARS without dumping raw markdown."""
    kept: list[str] = []
    for raw_line in readme_text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("```") or line.startswith("![") or line.startswith("<"):
            continue
        line = re.sub(r"^#+\s*", "", line).strip()
        if line:
            kept.append(line)
        if sum(len(x) for x in kept) >= MAX_README_EXCERPT_CHARS:
            break
    joined = " · ".join(kept)
    return joined[:MAX_README_EXCERPT_CHARS]


def _is_test_path(rel_path: str) -> bool:
    norm = rel_path.replace("\\", "/").lower()
    base = norm.rsplit("/", 1)[-1]
    return (
        "/tests/" in f"/{norm}"
        or "/test/" in f"/{norm}"
        or base.startswith("test_")
        or base.endswith(("_test.py", ".test.ts", ".test.tsx", ".spec.ts", ".spec.js"))
    )


def analyze_repo_tree_payload(
    repo_name: str,
    tree_payload: dict[str, Any],
    readme_text: str = "",
) -> dict[str, Any]:
    """Deterministically extract a bounded structural Ore Card from a GitHub git/trees payload."""
    if tree_payload.get("error_status") == 409 or tree_payload.get("empty_repo"):
        return {
            "repo": repo_name,
            "triage_verdict": "EMPTY_REPO",
            "reason": "Repository has an empty Git tree (0 commits/blobs).",
            "total_blobs": 0,
            "code_files": 0,
            "test_files": 0,
            "doc_files": 0,
            "ignored_or_asset_files": 0,
            "top_dirs": [],
            "manifests": [],
            "entrypoints": [],
            "sample_paths": [],
            "readme_excerpt": "",
        }

    if tree_payload.get("error"):
        return {
            "repo": repo_name,
            "triage_verdict": "ERROR",
            "reason": str(tree_payload.get("error"))[:220],
            "total_blobs": 0,
            "code_files": 0,
            "test_files": 0,
            "doc_files": 0,
            "ignored_or_asset_files": 0,
            "top_dirs": [],
            "manifests": [],
            "entrypoints": [],
            "sample_paths": [],
            "readme_excerpt": "",
        }

    raw_tree = tree_payload.get("tree")
    if not isinstance(raw_tree, list):
        raw_tree = []

    total_blobs = 0
    code_files = 0
    test_files = 0
    doc_files = 0
    ignored_or_asset_files = 0
    top_dirs_set: set[str] = set()
    manifests: list[str] = []
    entrypoints: list[str] = []
    sample_paths: list[str] = []

    for item in raw_tree:
        if not isinstance(item, dict) or item.get("type") != "blob":
            continue
        path_str = str(item.get("path") or "").strip()
        if not path_str:
            continue
        total_blobs += 1
        parts = path_str.split("/")
        if len(parts) > 1:
            top_dirs_set.add(parts[0])

        lower_parts = [p.lower() for p in parts]
        base_lower = lower_parts[-1]

        if any(p in IGNORED_TREE_DIRS for p in lower_parts[:-1]) or base_lower.endswith(ASSET_OR_BINARY_EXTS):
            ignored_or_asset_files += 1
            continue

        if base_lower in MANIFEST_FILENAMES and path_str not in manifests and len(manifests) < 8:
            manifests.append(path_str)

        if (
            base_lower in ENTRYPOINT_BASENAMES
            or (len(parts) <= 3 and base_lower.endswith((".py", ".ts", ".rs")) and not _is_test_path(path_str))
        ) and len(entrypoints) < 10:
            entrypoints.append(path_str)

        if _is_test_path(path_str):
            test_files += 1
        elif base_lower.endswith(CODE_EXTS):
            code_files += 1
        elif base_lower.endswith((".md", ".txt", ".rst")):
            doc_files += 1

        if len(sample_paths) < MAX_SAMPLE_PATHS:
            sample_paths.append(path_str)

    has_skill_md = any(p.lower().endswith("skill.md") for p in entrypoints + sample_paths)
    if total_blobs == 0:
        verdict = "EMPTY_REPO"
        reason = "No blob entries found in repository tree."
    elif code_files == 0 and test_files == 0 and not has_skill_md:
        verdict = "SKIP_ASSET_OR_STUB"
        reason = f"0 code/test files across {total_blobs} blobs (docs={doc_files}, assets/ignored={ignored_or_asset_files})."
    elif code_files > 0 and test_files == 0 and doc_files == 0 and not has_skill_md and len(manifests) <= 1:
        verdict = "SKIP_SCAFFOLD"
        reason = f"Untested/undocumented scaffold ({code_files} code file(s), 0 tests, 0 docs); verify manually before melting."
    else:
        verdict = "MELT_READY"
        reason = (
            f"{code_files} code file(s), {test_files} test file(s), "
            f"{len(manifests)} manifest(s), {len(entrypoints)} entrypoint(s)."
        )

    return {
        "repo": repo_name,
        "triage_verdict": verdict,
        "reason": reason,
        "truncated_tree": bool(tree_payload.get("truncated")),
        "total_blobs": total_blobs,
        "code_files": code_files,
        "test_files": test_files,
        "doc_files": doc_files,
        "ignored_or_asset_files": ignored_or_asset_files,
        "top_dirs": sorted(top_dirs_set)[:8],
        "manifests": manifests,
        "entrypoints": entrypoints,
        "sample_paths": sample_paths,
        "readme_excerpt": _clean_readme_excerpt(readme_text),
    }


def _fetch_repo_tree_and_readme(owner: str, repo: str, timeout_sec: int = 15) -> tuple[dict[str, Any], str]:
    """Perform at most 2 read-only `gh api` calls (tree + readme) without cloning."""
    tree_proc = subprocess.run(
        ["gh", "api", f"repos/{owner}/{repo}/git/trees/HEAD?recursive=1"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_sec,
        check=False,
    )
    if tree_proc.returncode != 0:
        err_text = (tree_proc.stderr or tree_proc.stdout or "").strip()
        if "409" in err_text or "Git Repository is empty" in err_text:
            return {"error_status": 409, "empty_repo": True}, ""
        return {"error": f"gh api tree failed (rc={tree_proc.returncode}): {err_text[:180]}"}, ""

    try:
        tree_data = json.loads(tree_proc.stdout or "{}")
    except json.JSONDecodeError as exc:
        return {"error": f"invalid tree JSON: {exc}"}, ""

    readme_proc = subprocess.run(
        ["gh", "api", f"repos/{owner}/{repo}/readme", "--jq", ".content"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout_sec,
        check=False,
    )
    readme_text = ""
    if readme_proc.returncode == 0 and readme_proc.stdout.strip():
        try:
            readme_text = base64.b64decode(readme_proc.stdout.strip()).decode("utf-8", errors="replace")
        except (ValueError, OSError) as exc:
            readme_text = f"[readme decode warning: {exc}]"

    return (tree_data if isinstance(tree_data, dict) else {"error": "unexpected tree payload"}), readme_text


def run_melt_scan(
    repos: list[str],
    *,
    owner: str = "guarani-ux",
    fixtures: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Scan 1..MAX_MELT_SCAN_REPOS repositories without cloning and return bounded Ore Cards."""
    cleaned = [r.strip() for r in repos if r.strip()]
    if not cleaned:
        raise ValueError("melt-scan requires at least 1 repository name.")
    if len(cleaned) > MAX_MELT_SCAN_REPOS:
        raise ValueError(
            f"melt-scan batch cap exceeded: got {len(cleaned)} repos, max is {MAX_MELT_SCAN_REPOS} per call "
            "to prevent token burn and rate-limit exhaustion."
        )

    results: list[dict[str, Any]] = []
    for repo_name in cleaned:
        if fixtures is not None:
            fix = fixtures.get(repo_name) or fixtures.get(repo_name.lower())
            if fix is None:
                card = analyze_repo_tree_payload(repo_name, {"error": f"No offline fixture for '{repo_name}'"})
            else:
                card = analyze_repo_tree_payload(
                    repo_name,
                    fix.get("tree_payload", fix),
                    str(fix.get("readme_text") or ""),
                )
        else:
            tree_payload, readme_text = _fetch_repo_tree_and_readme(owner, repo_name)
            card = analyze_repo_tree_payload(repo_name, tree_payload, readme_text)
        results.append(card)

    return {
        "owner": owner,
        "scanned_count": len(results),
        "max_batch_cap": MAX_MELT_SCAN_REPOS,
        "results": results,
    }


def _format_melt_scan_text(scan_report: dict[str, Any]) -> str:
    header = (
        f"Crucible Melt Scan ({scan_report['scanned_count']}/{scan_report['max_batch_cap']} repos, "
        f"cap<={MAX_STDOUT_BYTES_PER_REPO}B/repo)"
    )
    blocks: list[str] = [header]
    for item in scan_report["results"]:
        lines = [
            f"\n[{item['triage_verdict']}] {item['repo']} — {item['reason']}",
            (
                f"  Counts: blobs={item['total_blobs']} | code={item['code_files']} | "
                f"tests={item['test_files']} | docs={item['doc_files']} | assets/ignored={item['ignored_or_asset_files']}"
            ),
        ]
        if item["top_dirs"]:
            lines.append(f"  Top dirs: {', '.join(item['top_dirs'])}")
        if item["manifests"]:
            lines.append(f"  Manifests: {', '.join(item['manifests'])}")
        if item["entrypoints"]:
            lines.append(f"  Entrypoints: {', '.join(item['entrypoints'][:8])}")
        if item["readme_excerpt"]:
            lines.append(f"  README: {item['readme_excerpt']}")
        block = "\n".join(lines)
        if len(block.encode("utf-8")) > MAX_STDOUT_BYTES_PER_REPO:
            block = block.encode("utf-8")[: MAX_STDOUT_BYTES_PER_REPO - 3].decode("utf-8", errors="ignore") + "..."
        blocks.append(block)
    return "\n".join(blocks)
