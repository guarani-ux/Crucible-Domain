#!/usr/bin/env python3
"""In-RAM ML engine for terminal test-launch ranking and diff/code review.

Runs 100% locally in RAM (zero LLM API calls, zero persistent model files):
1. rank_tests_for_changes: Combines AST import graph, git co-change probabilities,
   and TF-IDF cosine similarity to rank pytest files by failure likelihood.
2. review_changes_in_ram: Scores changed files using IsolationForest structural
   baselines, AST complexity, and missing git co-change partner detection.
"""

from __future__ import annotations

import ast
import hashlib
import json
import math
import os
import re
import subprocess
import tempfile
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    f1_score,
    precision_score,
    recall_score,
)
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.model_selection import StratifiedKFold


def _git_changed_files(root: Path) -> tuple[list[str], str]:
    """Return (repo-relative changed paths, source_label) from working tree or HEAD~1."""
    proc = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    dirty: list[str] = []
    if proc.returncode == 0:
        for line in proc.stdout.splitlines():
            if len(line) >= 4:
                path_part = line[3:].strip()
                if " -> " in path_part:
                    path_part = path_part.split(" -> ", 1)[1].strip()
                if path_part:
                    dirty.append(path_part.replace("\\", "/").removeprefix("./"))
    if dirty:
        return sorted(set(dirty)), "working_tree"

    head_proc = subprocess.run(
        ["git", "-C", str(root), "diff", "--name-only", "HEAD~1", "HEAD"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if head_proc.returncode == 0:
        committed = [
            ln.strip().replace("\\", "/").removeprefix("./")
            for ln in head_proc.stdout.splitlines()
            if ln.strip()
        ]
        if committed:
            return sorted(set(committed)), "head_commit"
    return [], "clean"


def _git_numstat_history(root: Path, max_commits: int = 80) -> tuple[Counter[str], Counter[tuple[str, str]]]:
    """Build repo-relative file churn and symmetric co-change pair counts in RAM."""
    proc = subprocess.run(
        ["git", "-C", str(root), "log", f"-n{max_commits}", "--numstat", "--pretty=format:__C__"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    file_freq: Counter[str] = Counter()
    pair_freq: Counter[tuple[str, str]] = Counter()
    if proc.returncode != 0:
        return file_freq, pair_freq

    cur_files: list[str] = []
    for raw in proc.stdout.splitlines():
        if raw == "__C__":
            if cur_files:
                uniq = sorted(set(cur_files))
                for f in uniq:
                    file_freq[f] += 1
                if len(uniq) <= 20:
                    for i in range(len(uniq)):
                        for j in range(i + 1, len(uniq)):
                            pair_freq[(uniq[i], uniq[j])] += 1
                cur_files = []
        elif "\t" in raw:
            cols = raw.split("\t")
            if len(cols) == 3:
                rel = cols[2].strip().replace("\\", "/").removeprefix("./")
                if rel:
                    cur_files.append(rel)
    if cur_files:
        uniq = sorted(set(cur_files))
        for f in uniq:
            file_freq[f] += 1
        if len(uniq) <= 20:
            for i in range(len(uniq)):
                for j in range(i + 1, len(uniq)):
                    pair_freq[(uniq[i], uniq[j])] += 1
    return file_freq, pair_freq


def _cyclomatic_complexity(node: ast.AST) -> int:
    branches = (ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler, ast.With, ast.Try, ast.BoolOp, ast.IfExp)
    return 1 + sum(1 for n in ast.walk(node) if isinstance(n, branches))


def _scan_python_modules(root: Path, scan_dir: Path) -> list[dict[str, Any]]:
    """Scan Python modules under scan_dir with repo-relative paths and AST metrics."""
    if not scan_dir.is_dir():
        return []
    root_res = root.resolve()
    modules: list[dict[str, Any]] = []
    for py_file in sorted(scan_dir.rglob("*.py")):
        if any(p in py_file.parts for p in ("__pycache__", ".pytest_cache", "Archive", ".worktrees")):
            continue
        try:
            src = py_file.read_text(encoding="utf-8")
            tree = ast.parse(src, filename=str(py_file))
        except (OSError, SyntaxError, UnicodeError):
            continue
        try:
            rel_path = py_file.resolve().relative_to(root_res).as_posix()
        except ValueError:
            rel_path = py_file.resolve().as_posix()

        imported_names: set[str] = set()
        referenced_names: set[str] = set()
        funcs = 0
        max_cc = 1
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    imported_names.update(alias.name.split("."))
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported_names.update(node.module.split("."))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                funcs += 1
                referenced_names.add(node.name)
                cc = _cyclomatic_complexity(node)
                if cc > max_cc:
                    max_cc = cc
            elif isinstance(node, ast.Name):
                referenced_names.add(node.id)
            elif isinstance(node, ast.Attribute):
                referenced_names.add(node.attr)

        modules.append(
            {
                "rel_path": rel_path,
                "stem": py_file.stem,
                "loc": len(src.splitlines()),
                "funcs": funcs,
                "imports": len(imported_names),
                "imported_names": sorted(imported_names),
                "referenced_names": referenced_names,
                "max_cc": max_cc,
                "text": f"{rel_path} {' '.join(sorted(imported_names))} {ast.get_docstring(tree) or ''}",
            }
        )
    return modules


_HUNK_RE = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


def extract_changed_symbols(root: Path, changed_files: list[str]) -> dict[str, list[str]]:
    """Map changed Python files to exact enclosing AST function/class symbols touched in git diff."""
    root = root.resolve()
    py_files = [f for f in changed_files if f.endswith(".py")]
    if not py_files:
        return {}

    touched_lines: dict[str, set[int]] = defaultdict(set)
    proc = subprocess.run(
        ["git", "-C", str(root), "diff", "-U0", "--", *py_files],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode == 0:
        cur_file = ""
        for raw in proc.stdout.splitlines():
            if raw.startswith("+++ b/"):
                cur_file = raw[6:].strip().replace("\\", "/").removeprefix("./")
            elif cur_file and raw.startswith("@@ "):
                m = _HUNK_RE.match(raw)
                if m:
                    start = int(m.group(1))
                    count = int(m.group(2)) if m.group(2) is not None else 1
                    for ln in range(start, start + max(1, count)):
                        touched_lines[cur_file].add(ln)

    symbols_by_file: dict[str, list[str]] = {}
    for rel in py_files:
        fpath = root / rel
        if not fpath.is_file():
            continue
        try:
            src = fpath.read_text(encoding="utf-8")
            tree = ast.parse(src, filename=str(fpath))
        except (OSError, SyntaxError, UnicodeError):
            continue
        lines = touched_lines.get(rel)
        syms: list[str] = []
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                if not lines:
                    syms.append(node.name)
                else:
                    end_ln = getattr(node, "end_lineno", node.lineno)
                    if any(node.lineno <= ln <= end_ln for ln in lines):
                        syms.append(node.name)
        if syms:
            symbols_by_file[rel] = sorted(set(syms))[:15]
    return symbols_by_file


def _pair_count(pair_freq: Counter[tuple[str, str]], a: str, b: str) -> int:
    if a == b:
        return 0
    lo, hi = (a, b) if a < b else (b, a)
    return pair_freq.get((lo, hi), 0)


HISTORY_REL_PATH = Path(".agents") / "ml_history.jsonl"
CURATED_REL_PATH = Path(".agents") / "ml_curated.jsonl"
_TEST_FILE_RE = re.compile(r"(test_[A-Za-z0-9_]+\.py)")


def _classify_domain(row: dict[str, Any]) -> str:
    """Classify a history row into crucible_engine, writers_room, story_lane, or general."""
    blob = " ".join(
        [
            str(row.get("test_name") or ""),
            str(row.get("why") or ""),
            " ".join(row.get("changed_files") or []),
        ]
    ).lower()
    if "writers" in blob or "writers-room" in blob or "writersroom" in blob:
        return "writers_room"
    if "story" in blob or "story-lane" in blob or "storylane" in blob:
        return "story_lane"
    if "crucible_gate" in blob or "campaign_ir" in blob or "tx_patch" in blob or "verify_all" in blob:
        return "crucible_engine"
    return "general"


def curate_training_dataset(
    root: Path,
    history_path: Path | None = None,
    out_path: Path | None = None,
    max_imbalance_ratio: float = 4.0,
) -> dict[str, Any]:
    """Deterministically curate, deduplicate, balance, and score ml_history.jsonl for training."""
    t0 = time.perf_counter()
    root = root.resolve()
    src_path = history_path or (root / HISTORY_REL_PATH)
    dst_path = out_path or (root / CURATED_REL_PATH)
    _, _, raw_rows = _load_history_stats(src_path)

    seen_keys: set[tuple[str, str, int, str]] = set()
    deduped: list[dict[str, Any]] = []
    for r in raw_rows:
        domain = _classify_domain(r)
        key = (
            domain,
            str(r.get("test_name") or ""),
            int(r.get("outcome", 1)),
            str(r.get("what") or ""),
        )
        if key in seen_keys:
            continue
        seen_keys.add(key)
        deduped.append({**r, "domain": domain})

    fails = [r for r in deduped if int(r.get("outcome", 1)) == 0]
    passes = [r for r in deduped if int(r.get("outcome", 1)) == 1]

    # Cap majority class to max_imbalance_ratio * minority class when both exist
    if fails and passes:
        if len(fails) > int(len(passes) * max_imbalance_ratio):
            fails = fails[-int(len(passes) * max_imbalance_ratio):]
        elif len(passes) > int(len(fails) * max_imbalance_ratio):
            passes = passes[-int(len(fails) * max_imbalance_ratio):]

    curated = fails + passes
    dst_path.parent.mkdir(parents=True, exist_ok=True)
    with dst_path.open("w", encoding="utf-8") as fh:
        for r in curated:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    domain_counts = Counter(r["domain"] for r in curated)
    resolved_fails = sum(1 for r in fails if (r.get("how_resolved") or {}).get("resolved"))
    quality_ok = len(curated) >= 10 and len(fails) > 0 and len(passes) > 0

    return {
        "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        "raw_rows": len(raw_rows),
        "deduped_rows": len(deduped),
        "curated_rows": len(curated),
        "fail_rows": len(fails),
        "pass_rows": len(passes),
        "resolved_fail_rows": resolved_fails,
        "domain_counts": dict(domain_counts),
        "quality_gate_passed": quality_ok,
        "curated_path": str(dst_path),
    }


def _normalize_repo_rel(raw_path: str, root: Path) -> str:
    norm = raw_path.replace("\\", "/").strip()
    root_norm = root.resolve().as_posix().rstrip("/") + "/"
    if norm.lower().startswith(root_norm.lower()):
        return norm[len(root_norm):].removeprefix("./")
    return norm.removeprefix("./")


def _classify_blocker(content: str) -> tuple[str, str, str]:
    """Return (what_category, phase, why_snippet) from a failure/block output."""
    if "TQ-05" in content:
        cat, phase = "tq05_test_quality", "pre_tool_hook"
    elif "stale artifact" in content or "depends_on_sha256" in content:
        cat, phase = "stale_sha256", "strict_gate"
    elif "CRUCIBLE_ALLOWED_ROOTS" in content or "sandbox" in content.lower():
        cat, phase = "sandbox_block", "pre_tool_hook"
    elif "AssertionError" in content:
        cat, phase = "assertion_error", "test_run"
    elif "ImportError" in content or "ModuleNotFoundError" in content:
        cat, phase = "import_error", "test_run"
    elif "SyntaxError" in content:
        cat, phase = "syntax_error", "test_run"
    elif "TIMEOUT" in content or "timed out" in content.lower():
        cat, phase = "timeout", "test_run"
    else:
        cat, phase = "command_error", "cli_command"

    why = ""
    for ln in content.splitlines():
        s = ln.strip()
        if any(k in s for k in ("BLOCKED:", "AssertionError", "ImportError", "ModuleNotFoundError", "SyntaxError", "TQ-05", "E       ")):
            why = s[:160]
            break
    if not why:
        why = content.strip().splitlines()[0][:160] if content.strip() else cat
    return cat, phase, why


def extract_transcript_failures(
    root: Path,
    brain_root: Path | None = None,
    out_path: Path | None = None,
) -> dict[str, Any]:
    """Import test outcome records from an explicitly supplied transcript archive."""
    t0 = time.perf_counter()
    root = root.resolve()
    target_path = out_path or (root / HISTORY_REL_PATH)
    if brain_root is None:
        return {
            "elapsed_ms": 0.0, "conversations_scanned": 0, "rows_written": 0,
            "fail_rows": 0, "pass_rows": 0, "history_path": str(target_path),
            "status": "no_archive_selected",
        }
    b_root = brain_root
    if not b_root.is_dir():
        raise ValueError(f"Transcript archive is not a directory: {b_root}")
    target_path.parent.mkdir(parents=True, exist_ok=True)

    rows: list[dict[str, Any]] = []
    conv_count = 0
    if b_root.is_dir():
        for conv_dir in sorted(b_root.iterdir()):
            t_file = conv_dir / ".system_generated" / "logs" / "transcript.jsonl"
            if not t_file.is_file():
                continue
            conv_count += 1
            recent_edits: list[str] = []
            last_tool = ""
            pending_fail_indices: list[int] = []
            edits_since_fail: list[str] = []
            try:
                with t_file.open("r", encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        line = line.strip()
                        if not line:
                            continue
                        try:
                            step = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        for tc in step.get("tool_calls") or []:
                            last_tool = str(tc.get("name") or last_tool)
                            args = tc.get("arguments") or {}
                            if isinstance(args, dict) and isinstance(args.get("Path"), str):
                                rel = _normalize_repo_rel(args["Path"], root)
                                if rel and not rel.startswith("C:/"):
                                    recent_edits.append(rel)
                                    recent_edits = recent_edits[-8:]
                                    if pending_fail_indices:
                                        edits_since_fail.append(rel)
                        content = str(step.get("content") or "")
                        status = str(step.get("status") or "")
                        is_err = (
                            status == "ERROR"
                            or "Command exited with code 1" in content
                            or "FAILED " in content
                            or "BLOCKED:" in content
                        )
                        is_pass = "Command exited with code 0" in content and ("passed" in content or "ALL " in content)
                        if is_pass and pending_fail_indices:
                            fix_files = sorted(set(edits_since_fail))[:6]
                            for idx in pending_fail_indices:
                                rows[idx]["how_resolved"] = {"resolved": True, "fix_files": fix_files}
                            pending_fail_indices.clear()
                            edits_since_fail.clear()

                        if not (is_err or is_pass):
                            continue
                        matched_tests = sorted(set(_TEST_FILE_RE.findall(content)))
                        if not matched_tests and is_err:
                            matched_tests = ["gate_or_command"]
                        what, phase, why = _classify_blocker(content) if is_err else ("test_pass", "test_run", "passed")
                        for test_name in matched_tests:
                            row_idx = len(rows)
                            rows.append(
                                {
                                    "source": "transcript",
                                    "conversation_id": conv_dir.name,
                                    "when": {"timestamp": step.get("created_at", ""), "phase": phase},
                                    "what": what,
                                    "where": {"files": sorted(set(recent_edits)), "tool": last_tool},
                                    "why": why,
                                    "how_resolved": {"resolved": not is_err, "fix_files": []},
                                    "changed_files": sorted(set(recent_edits)),
                                    "test_name": test_name,
                                    "outcome": 0 if is_err else 1,
                                }
                            )
                            if is_err:
                                pending_fail_indices.append(row_idx)
            except OSError:
                continue

    if rows:
        with target_path.open("w", encoding="utf-8") as out_fh:
            for r in rows:
                out_fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    fail_count = sum(1 for r in rows if r["outcome"] == 0)
    pass_count = sum(1 for r in rows if r["outcome"] == 1)
    return {
        "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        "conversations_scanned": conv_count,
        "rows_written": len(rows),
        "fail_rows": fail_count,
        "pass_rows": pass_count,
        "history_path": str(target_path),
    }


def record_verify_outcomes(
    root: Path,
    changed_files: list[str],
    results: list[tuple[str, int]],
    out_path: Path | None = None,
) -> int:
    """Append live verify_all.ps1 check outcomes to .agents/ml_history.jsonl."""
    target_path = out_path or (root / HISTORY_REL_PATH)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with target_path.open("a", encoding="utf-8") as fh:
        for check_name, rc in results:
            row = {
                "source": "verify_all",
                "changed_files": changed_files,
                "test_name": check_name,
                "outcome": 1 if rc == 0 else 0,
            }
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
            written += 1
    return written


def _load_history_stats(history_path: Path) -> tuple[Counter[str], Counter[str], list[dict[str, Any]]]:
    """Load per-test fail/total counts and raw rows from ml_history.jsonl."""
    fails: Counter[str] = Counter()
    totals: Counter[str] = Counter()
    rows: list[dict[str, Any]] = []
    if not history_path.is_file():
        return fails, totals, rows
    try:
        with history_path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                tname = str(row.get("test_name") or "")
                outcome = int(row.get("outcome", 1))
                totals[tname] += 1
                if outcome == 0:
                    fails[tname] += 1
                rows.append(row)
    except OSError:
        pass
    return fails, totals, rows


def _featurize_rows(
    rows: list[dict[str, Any]],
    fails_counter: Counter[str],
    totals_counter: Counter[str],
) -> tuple[np.ndarray, np.ndarray]:
    """Featurize history rows using Laplace-smoothed historical failure rates."""
    X_list: list[list[float]] = []
    y_list: list[int] = []
    for r in rows:
        tname = str(r.get("test_name") or "")
        cfiles = r.get("changed_files") or []
        c_stems = {Path(cf).stem for cf in cfiles}
        direct = 1.0 if any(Path(cf).name == tname for cf in cfiles) else 0.0
        stem_hit = 1.0 if any(s in tname for s in c_stems) else 0.0
        f_rate = (fails_counter[tname] + 1.0) / (totals_counter[tname] + 2.0)
        X_list.append([direct, stem_hit, f_rate, float(len(cfiles))])
        y_list.append(1 if int(r.get("outcome", 1)) == 0 else 0)
    return np.array(X_list, dtype=float), np.array(y_list, dtype=int)


def _compute_ece(y_true: np.ndarray, y_prob: np.ndarray, n_bins: int = 5) -> float:
    """Compute n-bin Expected Calibration Error over [0.0, 1.0]."""
    if len(y_true) == 0:
        return 0.0
    bin_edges = np.linspace(0.0, 1.0, n_bins + 1)
    ece = 0.0
    n = float(len(y_true))
    for i in range(n_bins):
        lo, hi = bin_edges[i], bin_edges[i + 1]
        if i == 0:
            mask = (y_prob >= lo) & (y_prob <= hi)
        else:
            mask = (y_prob > lo) & (y_prob <= hi)
        count = int(np.sum(mask))
        if count > 0:
            acc = float(np.mean(y_true[mask]))
            conf = float(np.mean(y_prob[mask]))
            ece += (count / n) * abs(acc - conf)
    return round(float(ece), 4)


def fit_supervised_model(
    hist_fails: Counter[str],
    hist_totals: Counter[str],
    hist_rows: list[dict[str, Any]],
) -> tuple[LogisticRegression | None, str, float | None, dict[str, Any] | None]:
    """Fit LogisticRegression in RAM with leakage-free StratifiedKFold CV, provenance, and calibration."""
    if len(hist_rows) < 10:
        return None, "heuristic_bootstrap", None, None

    y_arr = np.array([1 if int(r.get("outcome", 1)) == 0 else 0 for r in hist_rows], dtype=int)
    if len(set(y_arr.tolist())) != 2:
        return None, "heuristic_bootstrap", None, None

    held_out: dict[str, Any] | None = None
    min_class = min(int(np.sum(y_arr == 0)), int(np.sum(y_arr == 1)))
    if min_class >= 2:
        n_splits = min(5, min_class)
        cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
        oof_preds = np.zeros(len(hist_rows), dtype=int)
        oof_probs = np.zeros(len(hist_rows), dtype=float)
        for train_idx, val_idx in cv.split(np.zeros(len(hist_rows)), y_arr):
            train_rows = [hist_rows[i] for i in train_idx]
            val_rows = [hist_rows[i] for i in val_idx]
            fold_fails: Counter[str] = Counter()
            fold_totals: Counter[str] = Counter()
            for r in train_rows:
                tname = str(r.get("test_name") or "")
                fold_totals[tname] += 1
                if int(r.get("outcome", 1)) == 0:
                    fold_fails[tname] += 1
            X_tr, y_tr = _featurize_rows(train_rows, fold_fails, fold_totals)
            X_val, _ = _featurize_rows(val_rows, fold_fails, fold_totals)
            fold_clf = LogisticRegression(max_iter=200, random_state=42)
            fold_clf.fit(X_tr, y_tr)
            oof_preds[val_idx] = fold_clf.predict(X_val)
            oof_probs[val_idx] = fold_clf.predict_proba(X_val)[:, 1]

        brier_score = round(float(brier_score_loss(y_arr, oof_probs)), 4)
        ece = _compute_ece(y_arr, oof_probs, n_bins=5)
        average_precision = round(float(average_precision_score(y_arr, oof_probs)), 4)
        baseline_ap = round(float(np.mean(y_arr)), 4)
        ranking_lift_ap = round(average_precision - baseline_ap, 4)
        dataset_sha256 = hashlib.sha256(
            json.dumps(hist_rows, sort_keys=True, ensure_ascii=False).encode("utf-8")
        ).hexdigest()
        held_out = {
            "folds": n_splits,
            "accuracy": round(float(np.mean(oof_preds == y_arr)), 3),
            "precision": round(float(precision_score(y_arr, oof_preds, zero_division=0)), 3),
            "recall": round(float(recall_score(y_arr, oof_preds, zero_division=0)), 3),
            "f1": round(float(f1_score(y_arr, oof_preds, zero_division=0)), 3),
            "brier_score": brier_score,
            "ece": ece,
            "average_precision": average_precision,
            "baseline_ap": baseline_ap,
            "ranking_lift_ap": ranking_lift_ap,
            "provenance": {
                "dataset_sha256": dataset_sha256,
                "row_count": len(hist_rows),
                "fail_count": int(np.sum(y_arr == 1)),
                "pass_count": int(np.sum(y_arr == 0)),
                "feature_schema": ["direct_match", "stem_hit", "laplace_fail_rate", "changed_file_count"],
                "random_state": 42,
                "leakage_free_cv": True,
            },
        }

    X_arr, y_full = _featurize_rows(hist_rows, hist_fails, hist_totals)
    clf = LogisticRegression(max_iter=200, random_state=42)
    clf.fit(X_arr, y_full)
    train_acc = round(float(clf.score(X_arr, y_full)), 3)
    return clf, "supervised_logistic", train_acc, held_out


def build_hot_state(root: Path) -> dict[str, Any]:
    """Pre-load AST index, git history, TF-IDF matrix, and trained ML models into RAM for <10ms serving."""
    t0 = time.perf_counter()
    root = root.resolve()
    tests_dir = root / ".agents" / "scripts" / "tests"
    test_modules = [
        m for m in _scan_python_modules(root, tests_dir)
        if Path(m["rel_path"]).name.startswith("test_")
    ]
    py_modules = _scan_python_modules(root, root / ".agents" / "scripts")
    file_freq, pair_freq = _git_numstat_history(root)
    hist_fails, hist_totals, hist_rows = _load_history_stats(root / HISTORY_REL_PATH)
    clf, model_mode, train_acc, held_out = fit_supervised_model(hist_fails, hist_totals, hist_rows)

    anomaly_by_rel: dict[str, tuple[bool, float]] = {}
    if len(py_modules) >= 5:
        feats = np.array(
            [[m["loc"], m["funcs"], m["imports"], m["max_cc"], file_freq.get(m["rel_path"], 0)] for m in py_modules],
            dtype=float,
        )
        iso = IsolationForest(contamination=0.15, random_state=42)
        preds = iso.fit_predict(feats)
        scores = iso.decision_function(feats)
        for m, pred, sc in zip(py_modules, preds, scores):
            anomaly_by_rel[m["rel_path"]] = (pred == -1, round(float(sc), 4))

    tfidf_vec: TfidfVectorizer | None = None
    tfidf_mat = None
    if test_modules:
        tfidf_vec = TfidfVectorizer(token_pattern=r"[A-Za-z0-9_]{2,}")
        tfidf_mat = tfidf_vec.fit_transform([m["text"] for m in test_modules])

    return {
        "root": root,
        "built_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        "test_modules": test_modules,
        "py_modules": py_modules,
        "file_freq": file_freq,
        "pair_freq": pair_freq,
        "hist_fails": hist_fails,
        "hist_totals": hist_totals,
        "hist_rows": hist_rows,
        "clf": clf,
        "model_mode": model_mode,
        "train_acc": train_acc,
        "held_out_metrics": held_out,
        "anomaly_by_rel": anomaly_by_rel,
        "tfidf_vec": tfidf_vec,
        "tfidf_mat": tfidf_mat,
    }


def rank_tests_for_changes(
    root: Path,
    changed_files: list[str] | None = None,
    hot_state: dict[str, Any] | None = None,
    changed_symbols: dict[str, list[str]] | None = None,
) -> dict[str, Any]:
    """Rank test files in RAM using symbol-level AST diff, imports, co-change, TF-IDF, and supervised ML."""
    t0 = time.perf_counter()
    root = root.resolve()
    if changed_files is not None:
        changes = [f.replace("\\", "/").removeprefix("./") for f in changed_files if f.strip()]
        change_source = "explicit"
    else:
        changes, change_source = _git_changed_files(root)

    if hot_state is not None:
        test_modules = hot_state["test_modules"]
        file_freq = hot_state["file_freq"]
        pair_freq = hot_state["pair_freq"]
        hist_fails = hot_state["hist_fails"]
        hist_totals = hot_state["hist_totals"]
        hist_rows = hot_state["hist_rows"]
        clf = hot_state["clf"]
        model_mode = hot_state["model_mode"]
        train_acc = hot_state["train_acc"]
        held_out = hot_state["held_out_metrics"]
    else:
        tests_dir = root / ".agents" / "scripts" / "tests"
        test_modules = [
            m for m in _scan_python_modules(root, tests_dir)
            if Path(m["rel_path"]).name.startswith("test_")
        ]
        file_freq, pair_freq = _git_numstat_history(root)
        hist_fails, hist_totals, hist_rows = _load_history_stats(root / HISTORY_REL_PATH)
        clf, model_mode, train_acc, held_out = fit_supervised_model(hist_fails, hist_totals, hist_rows)

    if not test_modules:
        return {
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            "change_source": change_source,
            "changed_files": changes,
            "ranked_tests": [],
        }

    changed_stems = {Path(c).stem for c in changes}
    sym_map = changed_symbols if changed_symbols is not None else (extract_changed_symbols(root, changes) if hot_state is None else {})
    all_changed_syms = {s for syms in sym_map.values() for s in syms}

    # TF-IDF similarity between combined change query (including symbols) and each test file
    tfidf_scores = np.zeros(len(test_modules), dtype=float)
    if changes:
        query_text = " ".join(f"{c} {Path(c).stem}" for c in changes) + " " + " ".join(sorted(all_changed_syms))
        if hot_state is not None and hot_state.get("tfidf_vec") is not None:
            q_mat = hot_state["tfidf_vec"].transform([query_text])
            tfidf_scores = cosine_similarity(q_mat, hot_state["tfidf_mat"]).ravel()
        else:
            corpus = [m["text"] for m in test_modules] + [query_text]
            vec = TfidfVectorizer(token_pattern=r"[A-Za-z0-9_]{2,}")
            mat = vec.fit_transform(corpus)
            tfidf_scores = cosine_similarity(mat[-1], mat[:-1]).ravel()

    ranked: list[dict[str, Any]] = []
    for idx, tm in enumerate(test_modules):
        t_path = tm["rel_path"]
        t_name = Path(t_path).name
        reasons: list[str] = []
        score = 0.0

        # 1. Direct test file modification
        direct_mod = 1.0 if t_path in changes else 0.0
        if direct_mod:
            score += 1.0
            reasons.append("modified_directly")

        # 2. AST import match against changed module stems
        imp_hits = sorted(changed_stems.intersection(tm["imported_names"]))
        if imp_hits:
            score += 0.65
            reasons.append(f"ast_imports({','.join(imp_hits[:3])})")

        # 2b. Symbol-level AST diff match (exact changed functions/classes referenced by test)
        sym_hits = sorted(all_changed_syms.intersection(tm.get("referenced_names") or set()))
        if sym_hits:
            score += 0.45
            reasons.append(f"ast_symbols({','.join(sym_hits[:3])})")

        # 3. Git co-change probability P(test | changed_file)
        best_co = 0
        best_prob = 0.0
        for c in changes:
            co = _pair_count(pair_freq, c, t_path)
            if co > 0:
                prob = co / max(1, file_freq.get(c, co))
                if co > best_co or prob > best_prob:
                    best_co = co
                    best_prob = prob
        if best_co > 0:
            score += min(0.55, 0.25 + 0.3 * best_prob)
            reasons.append(f"co_change({best_co}x, p={best_prob:.2f})")

        # 4. TF-IDF cosine similarity
        sim = float(tfidf_scores[idx])
        if sim >= 0.08:
            score += 0.35 * sim
            reasons.append(f"tfidf({sim:.2f})")

        # 5. Supervised historical failure probability (when trained)
        fail_rate = (hist_fails[t_name] + 1.0) / (hist_totals[t_name] + 2.0)
        if clf is not None:
            stem_hit = 1.0 if (imp_hits or sym_hits or any(s in t_name for s in changed_stems)) else 0.0
            fail_prob = float(clf.predict_proba(np.array([[direct_mod, stem_hit, fail_rate, float(len(changes))]], dtype=float))[0][1])
            score += 0.5 * fail_prob
            if fail_prob >= 0.35:
                reasons.append(f"ml_fail_prob({fail_prob:.2f})")

        # 6. Baseline churn tie-breaker
        churn = file_freq.get(t_path, 0)
        score += min(0.05, churn * 0.005)

        has_diff_signal = any(
            r.startswith(("modified_directly", "ast_imports", "ast_symbols", "co_change", "tfidf"))
            for r in reasons
        )
        tier = "impacted" if has_diff_signal and score >= 0.2 else "baseline"
        ranked.append(
            {
                "test_path": t_path,
                "score": round(score, 4),
                "tier": tier,
                "churn": churn,
                "reasons": reasons or ["baseline_coverage"],
            }
        )

    ranked.sort(key=lambda x: (-x["score"], x["test_path"]))
    return {
        "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        "model_mode": model_mode,
        "training_rows": len(hist_rows),
        "training_accuracy": train_acc,
        "held_out_metrics": held_out,
        "changed_symbols": sym_map,
        "change_source": change_source,
        "changed_files": changes,
        "impacted_count": sum(1 for r in ranked if r["tier"] == "impacted"),
        "ranked_tests": ranked,
    }


def review_changes_in_ram(
    root: Path,
    changed_files: list[str] | None = None,
    hot_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Score changed files in RAM for review priority, missing co-changes, and AST/IsolationForest signals."""
    t0 = time.perf_counter()
    root = root.resolve()
    if changed_files is not None:
        changes = [f.replace("\\", "/").removeprefix("./") for f in changed_files if f.strip()]
        change_source = "explicit"
    else:
        changes, change_source = _git_changed_files(root)

    if hot_state is not None:
        file_freq = hot_state["file_freq"]
        pair_freq = hot_state["pair_freq"]
        hist_rows = hot_state["hist_rows"]
        py_modules = hot_state["py_modules"]
        anomaly_by_rel = hot_state["anomaly_by_rel"]
    else:
        file_freq, pair_freq = _git_numstat_history(root)
        _, _, hist_rows = _load_history_stats(root / HISTORY_REL_PATH)
        py_modules = _scan_python_modules(root, root / ".agents" / "scripts")
        anomaly_by_rel = {}
        if len(py_modules) >= 5:
            feats = np.array(
                [[m["loc"], m["funcs"], m["imports"], m["max_cc"], file_freq.get(m["rel_path"], 0)] for m in py_modules],
                dtype=float,
            )
            iso = IsolationForest(contamination=0.15, random_state=42)
            preds = iso.fit_predict(feats)
            scores = iso.decision_function(feats)
            for m, pred, sc in zip(py_modules, preds, scores):
                anomaly_by_rel[m["rel_path"]] = (pred == -1, round(float(sc), 4))

    blockers_by_file: defaultdict[str, Counter[str]] = defaultdict(Counter)
    fixes_by_file: defaultdict[str, Counter[str]] = defaultdict(Counter)
    for r in hist_rows:
        if int(r.get("outcome", 1)) == 0 and r.get("what"):
            for cf in r.get("changed_files") or []:
                blockers_by_file[cf][str(r["what"])] += 1
                for ff in (r.get("how_resolved") or {}).get("fix_files") or []:
                    fixes_by_file[cf][str(ff)] += 1
    mod_by_rel = {m["rel_path"]: m for m in py_modules}
    sym_map = extract_changed_symbols(root, changes) if hot_state is None else {}

    # Build strong co-change expectation map (P(partner | file) >= 0.25 and co_changes >= 3)
    partners_of: defaultdict[str, list[tuple[str, int, float]]] = defaultdict(list)
    for (a, b), cnt in pair_freq.items():
        if cnt >= 3:
            pa = cnt / max(1, file_freq.get(a, cnt))
            pb = cnt / max(1, file_freq.get(b, cnt))
            if pa >= 0.25:
                partners_of[a].append((b, cnt, pa))
            if pb >= 0.25:
                partners_of[b].append((a, cnt, pb))

    change_set = set(changes)
    reviewed: list[dict[str, Any]] = []
    for rel in changes:
        signals: list[str] = []
        risk_score = 0.1
        churn = file_freq.get(rel, 0)

        # Check missing strong co-change partners (especially test files)
        missing_partners: list[dict[str, Any]] = []
        for partner, cnt, prob in sorted(partners_of.get(rel, []), key=lambda x: -x[1])[:3]:
            if partner not in change_set:
                missing_partners.append({"partner": partner, "co_changes": cnt, "probability": round(prob, 2)})
                risk_score += 0.25
                signals.append(f"missing_co_change_partner({partner}, {cnt}x, p={prob:.2f})")

        ast_info = mod_by_rel.get(rel)
        if ast_info:
            if ast_info["max_cc"] > 15:
                risk_score += 0.3
                signals.append(f"high_cc(max_cc={ast_info['max_cc']})")
            is_outlier, sc = anomaly_by_rel.get(rel, (False, 0.0))
            if is_outlier:
                risk_score += 0.25
                signals.append(f"isolation_forest_lead(score={sc})")

        if churn >= 10:
            risk_score += 0.15
            signals.append(f"high_churn({churn}x)")

        if rel in blockers_by_file:
            top_b, b_cnt = blockers_by_file[rel].most_common(1)[0]
            top_fix = fixes_by_file[rel].most_common(1)[0][0] if fixes_by_file[rel] else "n/a"
            signals.append(f"past_blocker({top_b} x{b_cnt}, fix={top_fix})")

        reviewed.append(
            {
                "rel_path": rel,
                "review_priority": round(min(1.0, risk_score), 2),
                "churn": churn,
                "max_cc": ast_info["max_cc"] if ast_info else None,
                "loc": ast_info["loc"] if ast_info else None,
                "changed_symbols": sym_map.get(rel, []),
                "missing_co_change_partners": missing_partners,
                "signals": signals or ["routine_change"],
                "lead_note": "Heuristic ML/git review signals only; inspect flagged files first.",
            }
        )

    reviewed.sort(key=lambda x: (-x["review_priority"], x["rel_path"]))
    return {
        "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        "change_source": change_source,
        "files_reviewed": len(reviewed),
        "high_priority_count": sum(1 for r in reviewed if r["review_priority"] >= 0.5),
        "reviewed_files": reviewed,
    }


def preflight_outcome_gate(
    root: Path,
    task_text: str = "",
    verify_cmd: str = "",
    changed_files: list[str] | None = None,
    hot_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Check outcome clarity first; if clear, emit ML-guided carry-through plan."""
    t0 = time.perf_counter()
    root = root.resolve()
    if changed_files is not None:
        changes = [f.replace("\\", "/").removeprefix("./") for f in changed_files if f.strip()]
    else:
        changes, _ = _git_changed_files(root)

    missing: list[str] = []
    realignment_prompts: list[str] = []

    words = [w for w in task_text.strip().split() if w]
    if len(words) < 3:
        missing.append("outcome_definition")
        realignment_prompts.append("Define the concrete target outcome in >= 3 words.")

    has_target = bool(changes) or any(tok in task_text for tok in (".py", ".ps1", ".md", "writers-room", "story-lane", "crucible_gate"))
    if not has_target:
        missing.append("target_scope")
        realignment_prompts.append("Specify target files, module, or spoke in scope.")

    rank_res = rank_tests_for_changes(root, changed_files=changes, hot_state=hot_state)
    has_verify = bool(verify_cmd.strip()) or rank_res["impacted_count"] > 0
    if not has_verify:
        missing.append("verification_criteria")
        realignment_prompts.append("Provide --verify-cmd or target files with impacted tests.")

    if missing:
        return {
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            "status": "REALIGNMENT_REQUIRED",
            "missing": missing,
            "realignment_prompts": realignment_prompts,
        }

    rev_res = review_changes_in_ram(root, changed_files=changes, hot_state=hot_state)
    impacted_tests = [r["test_path"] for r in rank_res["ranked_tests"] if r["tier"] == "impacted"]
    high_risk = [r for r in rev_res["reviewed_files"] if r["review_priority"] >= 0.35]

    return {
        "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        "status": "READY",
        "task": task_text.strip(),
        "target_files": changes,
        "verify_cmd": verify_cmd.strip() or "pwsh -File scripts/verify_all.ps1",
        "impacted_tests": impacted_tests,
        "high_risk_files": high_risk,
        "carry_through_plan": [
            f"1. Inspect {len(high_risk)} flagged file(s) and their past_blocker/missing_co_change signals.",
            f"2. Execute {len(impacted_tests)} ML-impacted test(s) first for fast failure feedback.",
            f"3. Run final verification: {verify_cmd.strip() or 'pwsh -File scripts/verify_all.ps1'}.",
        ],
    }


def _git_staged_files(root: Path) -> list[str]:
    """Return repo-relative paths currently staged in git index."""
    proc = subprocess.run(
        ["git", "-C", str(root), "diff", "--cached", "--name-only"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        return []
    return sorted({ln.strip().replace("\\", "/").removeprefix("./") for ln in proc.stdout.splitlines() if ln.strip()})


def compile_session_context(root: Path, hot_state: dict[str, Any] | None = None) -> dict[str, Any]:
    """Distill AST symbols + ML history + IR test-ranking into one high-signal session-start directive."""
    t0 = time.perf_counter()
    root = root.resolve()
    changes, source = _git_changed_files(root)
    if not changes:
        return {
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            "active_domain": "general",
            "change_source": source,
            "focus_files": [],
            "changed_symbols": [],
            "top_tests": [],
            "top_blocker": None,
            "summary_line": "Context Compiler (clean): active=general | ready for new assignment",
        }

    domain_votes = Counter(_classify_domain({"changed_files": [c]}) for c in changes)
    active_domain = domain_votes.most_common(1)[0][0]
    rank_res = rank_tests_for_changes(root, changed_files=changes, hot_state=hot_state)
    rev_res = review_changes_in_ram(root, changed_files=changes, hot_state=hot_state)

    top_tests = [Path(r["test_path"]).name for r in rank_res["ranked_tests"] if r["tier"] == "impacted"][:3]
    syms = sorted({s for lst in (rank_res.get("changed_symbols") or {}).values() for s in lst})[:4]
    top_blocker = None
    for item in rev_res["reviewed_files"]:
        for sig in item.get("signals") or []:
            if sig.startswith(("past_blocker(", "missing_co_change_partner(")):
                top_blocker = f"{Path(item['rel_path']).name}: {sig}"
                break
        if top_blocker:
            break

    parts = [f"Context Compiler ({source}): domain={active_domain}"]
    if syms:
        parts.append(f"syms={','.join(syms)}")
    if top_tests:
        parts.append(f"tests={','.join(top_tests)}")
    if top_blocker:
        parts.append(f"watch=[{top_blocker}]")

    return {
        "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        "active_domain": active_domain,
        "change_source": source,
        "focus_files": changes[:5],
        "changed_symbols": syms,
        "top_tests": top_tests,
        "top_blocker": top_blocker,
        "summary_line": " | ".join(parts),
    }


def assess_commit_risk(
    root: Path,
    staged_files: list[str] | None = None,
    hot_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Compute calibrated commit regression risk P(break) over staged files to steer pre-commit depth."""
    t0 = time.perf_counter()
    root = root.resolve()
    staged = staged_files if staged_files is not None else _git_staged_files(root)
    if not staged:
        return {
            "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            "staged_count": 0,
            "risk_prob": 0.0,
            "tier": "LOW",
            "enforce_strict": False,
            "impacted_tests": [],
            "advisories": [],
        }

    rev_res = review_changes_in_ram(root, changed_files=staged, hot_state=hot_state)
    rank_res = rank_tests_for_changes(root, changed_files=staged, hot_state=hot_state)

    max_prio = max((r["review_priority"] for r in rev_res["reviewed_files"]), default=0.1)
    has_py = any(f.endswith(".py") or f.endswith(".ps1") for f in staged)
    missing_partners = [
        f"{r['rel_path']} -> {p['partner']} ({p['co_changes']}x)"
        for r in rev_res["reviewed_files"]
        for p in r.get("missing_co_change_partners") or []
    ]
    impacted_tests = [r["test_path"] for r in rank_res["ranked_tests"] if r["tier"] == "impacted"][:4]

    risk_prob = min(
        0.99,
        round(
            0.55 * max_prio
            + (0.15 if has_py else 0.0)
            + (0.15 if missing_partners else 0.0)
            + min(0.14, 0.03 * len(impacted_tests)),
            3,
        ),
    )
    if risk_prob >= 0.55:
        tier = "HIGH"
    elif risk_prob >= 0.25:
        tier = "MEDIUM"
    else:
        tier = "LOW"

    advisories: list[str] = []
    if missing_partners:
        advisories.append(f"Missing co-change partner(s): {'; '.join(missing_partners[:2])}")
    if impacted_tests and tier in ("MEDIUM", "HIGH"):
        advisories.append(f"Priority tests: {', '.join(Path(t).name for t in impacted_tests)}")

    return {
        "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        "staged_count": len(staged),
        "risk_prob": risk_prob,
        "tier": tier,
        "enforce_strict": tier == "HIGH",
        "impacted_tests": impacted_tests,
        "advisories": advisories,
    }


def record_loop_outcome(
    root: Path,
    slice_id: str,
    target_paths: list[str],
    passed: bool,
    *,
    error_sha256: str = "",
    model_tier: str = "inherit",
    seconds: float = 0.0,
    out_path: Path | None = None,
) -> dict[str, Any]:
    """Append a single crucible-loop slice outcome to ml_history.jsonl for closed-loop ML routing."""
    target_path = out_path or (root / HISTORY_REL_PATH)
    target_path.parent.mkdir(parents=True, exist_ok=True)
    norm_files = [p.replace("\\", "/").removeprefix("./") for p in target_paths if p.strip()]
    row: dict[str, Any] = {
        "source": "crucible_loop",
        "slice_id": slice_id,
        "changed_files": norm_files,
        "test_name": f"slice:{slice_id}",
        "outcome": 1 if passed else 0,
        "error_sha256": error_sha256,
        "model_tier": model_tier,
        "seconds": round(float(seconds), 4),
    }
    with target_path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n")
    return row


def advise_slice_strategy(
    root: Path,
    slice_id: str,
    target_paths: list[str],
    *,
    history_path: Path | None = None,
) -> dict[str, Any]:
    """Recommend model tier and anti-Goodhart guardrails for a slice using historical loop/verify outcomes."""
    target_history = history_path or (root / HISTORY_REL_PATH)
    norm_targets = {p.replace("\\", "/").removeprefix("./") for p in target_paths if p.strip()}
    _, _, rows = _load_history_stats(target_history)

    prior_runs = 0
    prior_failures = 0
    err_counts: Counter[str] = Counter()
    slice_key = f"slice:{slice_id}"

    for row in rows:
        row_files = {
            str(f).replace("\\", "/").removeprefix("./")
            for f in (row.get("changed_files") or [])
            if isinstance(f, str)
        }
        same_slice = row.get("test_name") == slice_key or row.get("slice_id") == slice_id
        overlaps_file = bool(norm_targets and (norm_targets & row_files))
        if not (same_slice or overlaps_file):
            continue
        prior_runs += 1
        if int(row.get("outcome", 1)) == 0:
            prior_failures += 1
            eh = str(row.get("error_sha256", "") or "").strip()
            if eh:
                err_counts[eh] += 1

    if prior_runs > 0:
        # Laplace-smoothed empirical failure probability
        risk_score = (prior_failures + 1.0) / (prior_runs + 2.0)
    else:
        risk_score = 0.20

    recurring_errors = [eh for eh, cnt in err_counts.items() if cnt >= 2]
    if recurring_errors:
        risk_score = min(0.99, risk_score + 0.15)

    risk_score = round(min(max(risk_score, 0.0), 0.99), 3)

    if risk_score >= 0.65:
        recommended_model_tier = "pro"
    elif risk_score >= 0.35:
        recommended_model_tier = "inherit"
    else:
        recommended_model_tier = "flash"

    enable_withheld_holdout = risk_score >= 0.45
    enable_counterexample_ratchet = risk_score >= 0.50

    if prior_runs == 0:
        reason = "no prior failure history; defaulting to fast tier"
    elif recurring_errors:
        reason = (
            f"{prior_failures}/{prior_runs} prior failures with {len(recurring_errors)} recurring error cluster(s); "
            f"escalating to {recommended_model_tier} with holdout+ratchet guards"
        )
    else:
        reason = f"{prior_failures}/{prior_runs} prior failures -> risk={risk_score:.3f}, tier={recommended_model_tier}"

    return {
        "slice_id": slice_id,
        "risk_score": risk_score,
        "recommended_model_tier": recommended_model_tier,
        "enable_withheld_holdout": enable_withheld_holdout,
        "enable_counterexample_ratchet": enable_counterexample_ratchet,
        "prior_runs": prior_runs,
        "prior_failures": prior_failures,
        "recurring_error_hashes": sorted(recurring_errors),
        "reason": reason,
    }


BANDIT_STATE_REL_PATH = ".agents/ml_bandit_state.json"

CRAFT_INTERVENTION_INSTRUCTIONS: dict[str, str] = {
    "decision_first_scaffold": (
        "Open in lines 1-3 with the exact decision/recommendation requested, named decision owner, "
        "and separate confirmed facts from [UNKNOWN — OWNER TO CONFIRM] holds."
    ),
    "spoken_ear_counterpoint": (
        "Write an A/V beat table (`MM:SS-MM:SS | Audio | Video`) at <=150 WPM spoken cadence. "
        "Strip print-prose clichés and ensure narration adds meaning rather than repeating what camera shows."
    ),
    "evidence_hold_custody": (
        "Cite exact local file paths/dates for every factual claim, separate observed evidence from "
        "proposed hypotheses, and list transfer limits and next testable checks."
    ),
    "crew_table_completeness": (
        "Format operational windows/shots as scannable Markdown tables with explicit times/IDs, "
        "priority tiers, minimum usable thresholds, and fallback/stop owners."
    ),
    "channel_native_split": (
        "Give each channel (YouTube, Instagram, Newsletter) distinct native hook/format copy and separate "
        "CH-04 internal handoff, unlisted preview, and public rollout gates."
    ),
    "exemplar_parity_anchor": (
        "Match professional media-agency structural anatomy: concrete named moments, realistic asset/access "
        "boundaries, and zero-reconstruction next steps for the receiving colleague."
    ),
}


def load_bandit_state(root: Path, state_path: Path | None = None) -> dict[str, Any]:
    """Load persisted contextual bandit + diminishing-returns trajectory state."""
    p = state_path or (root / BANDIT_STATE_REL_PATH)
    if not p.is_file():
        return {"contexts": {}, "trajectories": {}}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("contexts", {})
            data.setdefault("trajectories", {})
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"contexts": {}, "trajectories": {}}


def save_bandit_state(root: Path, state: dict[str, Any], state_path: Path | None = None) -> None:
    """Atomically persist contextual bandit + trajectory state to JSON."""
    p = state_path or (root / BANDIT_STATE_REL_PATH)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=".bandit_", dir=str(p.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(payload)
        os.replace(tmp_name, p)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def select_craft_arm(
    root: Path,
    context_key: str,
    candidate_arms: list[str] | tuple[str, ...],
    *,
    state_path: Path | None = None,
    exploration_c: float = 0.75,
) -> dict[str, Any]:
    """Select the next craft intervention arm for context_key using UCB1 over observed form scores."""
    arms = [a for a in candidate_arms if a] or list(CRAFT_INTERVENTION_INSTRUCTIONS.keys())
    state = load_bandit_state(root, state_path)
    ctx_arms = state.get("contexts", {}).get(context_key, {})

    total_pulls = sum(int((ctx_arms.get(a) or {}).get("pulls", 0)) for a in arms)
    for arm in arms:
        rec = ctx_arms.get(arm) or {}
        if int(rec.get("pulls", 0)) == 0:
            return {
                "arm_id": arm,
                "instruction": CRAFT_INTERVENTION_INSTRUCTIONS.get(arm, ""),
                "ucb_score": float("inf"),
                "mean_reward": 0.0,
                "pulls": 0,
                "reason": f"cold-start exploration of untried arm '{arm}'",
            }

    best_arm = arms[0]
    best_ucb = -1.0
    best_mean = 0.0
    best_pulls = 0
    for arm in arms:
        rec = ctx_arms[arm]
        pulls = int(rec.get("pulls", 1))
        mean_r = float(rec.get("mean_reward", 0.0))
        ucb = mean_r + exploration_c * math.sqrt(math.log(max(1, total_pulls)) / pulls)
        if ucb > best_ucb:
            best_ucb = ucb
            best_arm = arm
            best_mean = mean_r
            best_pulls = pulls

    return {
        "arm_id": best_arm,
        "instruction": CRAFT_INTERVENTION_INSTRUCTIONS.get(best_arm, ""),
        "ucb_score": round(best_ucb, 4),
        "mean_reward": round(best_mean, 4),
        "pulls": best_pulls,
        "reason": f"UCB1 selected '{best_arm}' (mean={best_mean:.3f}, pulls={best_pulls}, ucb={best_ucb:.3f})",
    }


def update_craft_arm(
    root: Path,
    context_key: str,
    arm_id: str,
    score: float,
    *,
    passed: bool = True,
    target_key: str | None = None,
    state_path: Path | None = None,
) -> dict[str, Any]:
    """Update UCB1 bandit arm statistics and score trajectory after observing a round result."""
    state = load_bandit_state(root, state_path)
    contexts = state.setdefault("contexts", {})
    ctx_arms = contexts.setdefault(context_key, {})
    rec = ctx_arms.setdefault(arm_id, {"pulls": 0, "sum_reward": 0.0, "mean_reward": 0.0, "last_score": 0.0})

    clipped = max(0.0, min(1.0, float(score)))
    effective_reward = clipped if passed else round(clipped * 0.5, 4)

    rec["pulls"] = int(rec.get("pulls", 0)) + 1
    rec["sum_reward"] = round(float(rec.get("sum_reward", 0.0)) + effective_reward, 4)
    rec["mean_reward"] = round(rec["sum_reward"] / rec["pulls"], 4)
    rec["last_score"] = round(clipped, 4)

    traj_key = target_key or context_key
    trajs = state.setdefault("trajectories", {})
    hist = list(trajs.get(traj_key, []))
    hist.append(round(clipped, 4))
    trajs[traj_key] = hist[-25:]

    save_bandit_state(root, state, state_path)
    return {"context_key": context_key, "arm_id": arm_id, "arm_state": dict(rec), "trajectory": trajs[traj_key]}


def assess_diminishing_returns(
    score_history: list[float],
    *,
    min_delta: float = 0.03,
    window: int = 2,
    saturation_score: float = 0.92,
) -> dict[str, Any]:
    """Detect plateau / diminishing marginal gains on a continuous optimization trajectory."""
    if not score_history:
        return {"saturated": False, "reason": "no observations yet", "recent_delta": 0.0, "latest_score": 0.0}

    latest = float(score_history[-1])
    if len(score_history) >= 2 and min(float(score_history[-2]), latest) >= saturation_score:
        return {
            "saturated": True,
            "reason": f"reached saturation threshold for 2 rounds ({latest:.3f} >= {saturation_score:.2f})",
            "recent_delta": round(latest - float(score_history[-2]), 4),
            "latest_score": latest,
        }

    if len(score_history) < window + 1:
        delta = round(latest - float(score_history[-2]), 4) if len(score_history) >= 2 else latest
        return {
            "saturated": False,
            "reason": f"insufficient window ({len(score_history)}/{window + 1} samples)",
            "recent_delta": delta,
            "latest_score": latest,
        }

    recent = score_history[-(window + 1) :]
    deltas = [recent[i + 1] - recent[i] for i in range(window)]
    max_recent_gain = max(deltas)
    if max_recent_gain < min_delta:
        return {
            "saturated": True,
            "reason": f"diminishing returns over last {window} rounds (max gain {max_recent_gain:.3f} < {min_delta:.2f})",
            "recent_delta": round(deltas[-1], 4),
            "latest_score": latest,
        }

    return {
        "saturated": False,
        "reason": f"still improving (latest={latest:.3f}, delta={deltas[-1]:+.3f})",
        "recent_delta": round(deltas[-1], 4),
        "latest_score": latest,
    }


def select_next_frontier_target(
    root: Path,
    candidate_ids: list[str],
    *,
    state_path: Path | None = None,
    min_delta: float = 0.03,
    saturation_score: float = 0.92,
) -> dict[str, Any]:
    """Pick the next highest-leverage unsaturated target, rotating away from saturated forms/aspects."""
    if not candidate_ids:
        return {"selected_id": None, "all_saturated": True, "frontier": []}

    state = load_bandit_state(root, state_path)
    trajs = state.get("trajectories", {})

    frontier: list[dict[str, Any]] = []
    unsaturated: list[dict[str, Any]] = []
    for cid in candidate_ids:
        hist = [float(x) for x in trajs.get(cid, [])]
        dr = assess_diminishing_returns(hist, min_delta=min_delta, saturation_score=saturation_score)
        entry = {
            "id": cid,
            "runs": len(hist),
            "latest_score": dr["latest_score"],
            "saturated": dr["saturated"],
            "reason": dr["reason"],
        }
        frontier.append(entry)
        if not dr["saturated"]:
            unsaturated.append(entry)

    if not unsaturated:
        # All targets saturated: pick the lowest-scoring one for periodic regression verification
        chosen = min(frontier, key=lambda e: (e["latest_score"], e["runs"]))
        return {
            "selected_id": chosen["id"],
            "all_saturated": True,
            "reason": f"all {len(frontier)} targets saturated; re-verifying lowest score ({chosen['id']})",
            "frontier": frontier,
        }

    # Prioritize unvisited targets first, then lowest latest score still making gains
    chosen = min(unsaturated, key=lambda e: (0 if e["runs"] == 0 else 1, e["latest_score"], e["runs"]))
    return {
        "selected_id": chosen["id"],
        "all_saturated": False,
        "reason": f"frontier focus -> '{chosen['id']}' ({chosen['reason']})",
        "frontier": frontier,
    }


LEARNED_POLICIES_REL_PATH = ".agents/ml_learned_policies.json"


def _atomic_write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(data, indent=2, sort_keys=True, ensure_ascii=False) + "\n"
    fd, tmp_name = tempfile.mkstemp(prefix=".mlpol_", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(payload)
        os.replace(tmp_name, path)
    except Exception:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
        raise


def load_learned_policies(root: Path, policy_path: Path | None = None) -> dict[str, Any]:
    """Load persistent cross-session learned rules, difficulty levels, and 5-element mastery per form/target."""
    p = policy_path or (root / LEARNED_POLICIES_REL_PATH)
    if p.is_file():
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                raw.setdefault("targets", {})
                raw.setdefault("forms", {})
                return raw
        except (OSError, json.JSONDecodeError):
            pass
    return {"targets": {}, "forms": {}}


def get_domain_mastery_context(
    root: Path,
    target_key: str,
    form_id: str,
    *,
    policy_path: Path | None = None,
) -> dict[str, Any]:
    """Retrieve persisted difficulty level, prior diagnosis, and top learned rules for a target/form."""
    data = load_learned_policies(root, policy_path)
    t_rec = data["targets"].get(target_key, {})
    f_rec = data["forms"].get(form_id, {})
    return {
        "difficulty_level": int(t_rec.get("difficulty_level", 1)),
        "weakest_element": str(t_rec.get("weakest_element", "")),
        "last_diagnosis": str(t_rec.get("last_diagnosis", "")),
        "element_averages": dict(f_rec.get("element_averages", {})),
        "learned_rules": list(f_rec.get("learned_rules", []))[:4],
    }


def record_domain_mastery(
    root: Path,
    target_key: str,
    form_id: str,
    *,
    score: float,
    passed: bool,
    arm_id: str,
    element_scores: dict[str, float] | None,
    weakest_element: str,
    diagnosis: str,
    mastery_tip: str = "",
    saturated: bool = False,
    policy_path: Path | None = None,
    bandit_state_path: Path | None = None,
) -> dict[str, Any]:
    """Persist cross-restart mastery telemetry, promote winning craft rules, and escalate difficulty on saturation."""
    p = policy_path or (root / LEARNED_POLICIES_REL_PATH)
    data = load_learned_policies(root, p)
    t_rec = data["targets"].setdefault(
        target_key,
        {"form_id": form_id, "difficulty_level": 1, "runs": 0, "best_score": 0.0},
    )
    t_rec["form_id"] = form_id
    t_rec["runs"] = int(t_rec.get("runs", 0)) + 1
    t_rec["best_score"] = round(max(float(t_rec.get("best_score", 0.0)), float(score)), 4)
    t_rec["last_score"] = round(float(score), 4)
    t_rec["weakest_element"] = weakest_element
    t_rec["last_diagnosis"] = diagnosis

    escalated_to: int | None = None
    cur_level = int(t_rec.get("difficulty_level", 1))
    if saturated and cur_level < 3 and float(score) >= 0.72:
        cur_level += 1
        t_rec["difficulty_level"] = cur_level
        escalated_to = cur_level
        # Reset local plateau trajectory at the new difficulty level so continuous runs keep exploring
        b_state = load_bandit_state(root, bandit_state_path)
        if target_key in b_state.get("trajectories", {}):
            b_state["trajectories"][target_key] = []
            save_bandit_state(root, b_state, bandit_state_path)

    f_rec = data["forms"].setdefault(
        form_id,
        {"runs": 0, "element_averages": {}, "learned_rules": []},
    )
    f_rec["runs"] = int(f_rec.get("runs", 0)) + 1
    if element_scores:
        prev_avgs = f_rec.setdefault("element_averages", {})
        alpha = 0.35
        for el, val in element_scores.items():
            if el in prev_avgs:
                prev_avgs[el] = round((1.0 - alpha) * float(prev_avgs[el]) + alpha * float(val), 4)
            else:
                prev_avgs[el] = round(float(val), 4)

    if passed and float(score) >= 0.80:
        inst = CRAFT_INTERVENTION_INSTRUCTIONS.get(arm_id, "").strip()
        candidate_rule = f"[{arm_id}] {inst}" if inst else arm_id
        if mastery_tip:
            candidate_rule = f"{candidate_rule} Focus: {mastery_tip}"
        rules = list(f_rec.get("learned_rules", []))
        if candidate_rule not in rules:
            rules.append(candidate_rule)
            f_rec["learned_rules"] = rules[-6:]

    _atomic_write_json(p, data)
    return {
        "target_key": target_key,
        "form_id": form_id,
        "difficulty_level": cur_level,
        "escalated_to": escalated_to,
        "learned_rules_count": len(f_rec.get("learned_rules", [])),
    }
