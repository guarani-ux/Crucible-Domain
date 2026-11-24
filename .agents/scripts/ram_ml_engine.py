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
import json
import re
import subprocess
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.ensemble import IsolationForest
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import f1_score, precision_score, recall_score
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.model_selection import StratifiedKFold, cross_val_predict


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


DEFAULT_BRAIN_ROOT = Path.home() / ".gemini" / "antigravity" / "brain"
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
    """Scan Antigravity transcript.jsonl files for 5W1H + Resolution failure/pass records."""
    t0 = time.perf_counter()
    root = root.resolve()
    b_root = brain_root or DEFAULT_BRAIN_ROOT
    target_path = out_path or (root / HISTORY_REL_PATH)
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


def fit_supervised_model(
    hist_fails: Counter[str],
    hist_totals: Counter[str],
    hist_rows: list[dict[str, Any]],
) -> tuple[LogisticRegression | None, str, float | None, dict[str, Any] | None]:
    """Fit LogisticRegression in RAM and compute held-out StratifiedKFold precision/recall/F1."""
    if len(hist_rows) < 10:
        return None, "heuristic_bootstrap", None, None

    X_train: list[list[float]] = []
    y_train: list[int] = []
    for r in hist_rows:
        tname = str(r.get("test_name") or "")
        cfiles = r.get("changed_files") or []
        c_stems = {Path(cf).stem for cf in cfiles}
        direct = 1.0 if any(Path(cf).name == tname for cf in cfiles) else 0.0
        stem_hit = 1.0 if any(s in tname for s in c_stems) else 0.0
        f_rate = hist_fails[tname] / max(1, hist_totals[tname])
        X_train.append([direct, stem_hit, f_rate, float(len(cfiles))])
        y_train.append(1 if int(r.get("outcome", 1)) == 0 else 0)

    if len(set(y_train)) != 2:
        return None, "heuristic_bootstrap", None, None

    X_arr = np.array(X_train, dtype=float)
    y_arr = np.array(y_train, dtype=int)
    clf = LogisticRegression(max_iter=200, random_state=42)
    clf.fit(X_arr, y_arr)
    train_acc = round(float(clf.score(X_arr, y_arr)), 3)

    held_out: dict[str, Any] | None = None
    min_class = min(int(np.sum(y_arr == 0)), int(np.sum(y_arr == 1)))
    if min_class >= 2:
        n_splits = min(5, min_class)
        cv = StratifiedKFold(n_splits=n_splits, shuffle=True, random_state=42)
        y_pred = cross_val_predict(LogisticRegression(max_iter=200, random_state=42), X_arr, y_arr, cv=cv)
        held_out = {
            "folds": n_splits,
            "accuracy": round(float(np.mean(y_pred == y_arr)), 3),
            "precision": round(float(precision_score(y_arr, y_pred, zero_division=0)), 3),
            "recall": round(float(recall_score(y_arr, y_pred, zero_division=0)), 3),
            "f1": round(float(f1_score(y_arr, y_pred, zero_division=0)), 3),
        }
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
        fail_rate = hist_fails[t_name] / max(1, hist_totals[t_name])
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
