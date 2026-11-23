#!/usr/bin/env python3
"""Outcome ledger, Beta-Bernoulli capability priors, and git-churn risk escalation."""

from __future__ import annotations

import json
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LEDGER_REL_PATH = Path("Knowledge") / "outcome_ledger.json"
LEDGER_SCHEMA_VERSION = 1
MAX_LEDGER_EVENTS = 200
VALID_VERDICTS = frozenset({"PASS", "FAIL", "REVERT"})
FIX_COMMIT_RE = re.compile(r"\b(?:fix|revert|hotfix|bug|broken|patch|harden)\b", re.IGNORECASE)
REFEREE_PREFIXES = (
    ".agents/scripts/crucible_gate.py",
    ".agents/scripts/crucible/",
    ".agents/scripts/test_quality_gate.py",
    ".agents/scripts/mutation_gate.py",
    ".github/workflows/",
)


def _norm_path(path: str) -> str:
    cleaned = path.strip().replace("\\", "/")
    while cleaned.startswith("./"):
        cleaned = cleaned[2:]
    return cleaned.lstrip("/")


def empty_ledger() -> dict[str, Any]:
    """Return a clean initialized outcome ledger matching schema v1."""
    return {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "updated_at": "",
        "capability_priors": {},
        "file_risk": {},
        "events": [],
    }


def validate_ledger(data: Any) -> list[str]:
    """Validate outcome_ledger.json structure; return list of human-readable errors."""
    if not isinstance(data, dict):
        return ["root must be a JSON object"]
    errors: list[str] = []
    if data.get("schema_version") != LEDGER_SCHEMA_VERSION:
        errors.append(f"schema_version must equal {LEDGER_SCHEMA_VERSION}")

    priors = data.get("capability_priors")
    if not isinstance(priors, dict):
        errors.append("capability_priors must be an object")
    else:
        for cap_id, rec in priors.items():
            if not isinstance(cap_id, str) or not cap_id.strip():
                errors.append("capability_priors keys must be non-empty strings")
                continue
            if not isinstance(rec, dict):
                errors.append(f"capability_priors[{cap_id}] must be an object")
                continue
            alpha = rec.get("alpha")
            beta = rec.get("beta")
            trials = rec.get("trials")
            vp = rec.get("verified_passes")
            vf = rec.get("verified_fails")
            if not isinstance(alpha, (int, float)) or isinstance(alpha, bool) or alpha <= 0:
                errors.append(f"capability_priors[{cap_id}].alpha must be > 0")
            if not isinstance(beta, (int, float)) or isinstance(beta, bool) or beta <= 0:
                errors.append(f"capability_priors[{cap_id}].beta must be > 0")
            for k_name, k_val in (("trials", trials), ("verified_passes", vp), ("verified_fails", vf)):
                if not isinstance(k_val, int) or isinstance(k_val, bool) or k_val < 0:
                    errors.append(f"capability_priors[{cap_id}].{k_name} must be an integer >= 0")

    file_risk = data.get("file_risk")
    if not isinstance(file_risk, dict):
        errors.append("file_risk must be an object")
    else:
        for fpath, rec in file_risk.items():
            if not isinstance(fpath, str) or not fpath.strip():
                errors.append("file_risk keys must be non-empty strings")
                continue
            if not isinstance(rec, dict):
                errors.append(f"file_risk[{fpath}] must be an object")
                continue
            commits = rec.get("commits")
            fix_commits = rec.get("fix_commits")
            risk_score = rec.get("risk_score")
            if not isinstance(commits, int) or isinstance(commits, bool) or commits < 0:
                errors.append(f"file_risk[{fpath}].commits must be an integer >= 0")
            if not isinstance(fix_commits, int) or isinstance(fix_commits, bool) or fix_commits < 0:
                errors.append(f"file_risk[{fpath}].fix_commits must be an integer >= 0")
            if (
                not isinstance(risk_score, (int, float))
                or isinstance(risk_score, bool)
                or not (0.0 <= float(risk_score) <= 1.0)
            ):
                errors.append(f"file_risk[{fpath}].risk_score must be within [0.0, 1.0]")

    events = data.get("events")
    if not isinstance(events, list):
        errors.append("events must be a list")
    else:
        for idx, ev in enumerate(events):
            if not isinstance(ev, dict):
                errors.append(f"events[{idx}] must be an object")
                continue
            if ev.get("verdict") not in VALID_VERDICTS:
                errors.append(f"events[{idx}].verdict must be one of {sorted(VALID_VERDICTS)}")
            src = ev.get("source")
            if not isinstance(src, str) or not src.strip():
                errors.append(f"events[{idx}].source must be a non-empty string")

    return errors


def load_ledger(root: Path) -> dict[str, Any]:
    """Load Knowledge/outcome_ledger.json or return empty_ledger() if missing."""
    path = root / LEDGER_REL_PATH
    if not path.is_file():
        return empty_ledger()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid JSON in {LEDGER_REL_PATH.as_posix()}: {exc}") from exc
    errs = validate_ledger(data)
    if errs:
        raise ValueError(f"invalid schema in {LEDGER_REL_PATH.as_posix()}: {'; '.join(errs[:4])}")
    return data


def save_ledger(root: Path, ledger: dict[str, Any]) -> Path:
    """Validate and atomically persist outcome_ledger.json with LF line endings."""
    errs = validate_ledger(ledger)
    if errs:
        raise ValueError(f"refusing to save invalid ledger: {'; '.join(errs[:4])}")
    target = root / LEDGER_REL_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = target.with_name(f".{target.name}.{os.getpid()}.tmp")
    payload = json.dumps(ledger, indent=2, ensure_ascii=False) + "\n"
    try:
        with tmp_path.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write(payload)
        os.replace(tmp_path, target)
    finally:
        tmp_path.unlink(missing_ok=True)
    return target


def capability_posterior_multiplier(ledger: dict[str, Any] | None, cap_id: str) -> float:
    """Compute bounded [0.75, 1.25] Beta posterior multiplier for lexical routing."""
    if not ledger or not isinstance(ledger, dict):
        return 1.0
    priors = ledger.get("capability_priors")
    if not isinstance(priors, dict):
        return 1.0
    rec = priors.get(cap_id)
    if not isinstance(rec, dict):
        return 1.0
    trials = rec.get("trials", 0)
    if not isinstance(trials, int) or trials < 1:
        return 1.0
    alpha = float(rec.get("alpha", 1.0))
    beta = float(rec.get("beta", 1.0))
    if alpha <= 0 or beta <= 0:
        return 1.0
    mean = alpha / (alpha + beta)
    return round(max(0.75, min(1.25, 1.0 + 0.5 * (mean - 0.5))), 4)


def refresh_file_risk_from_git(root: Path, *, max_commits: int = 100) -> dict[str, dict[str, Any]]:
    """Estimate smoothed fix/revert churn risk per file from local git log."""
    proc = subprocess.run(
        ["git", "log", f"-n{max_commits}", "--name-only", "--format=COMMIT:%H %s"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        return {}

    counts: dict[str, list[int]] = {}
    is_fix_commit = False
    for raw_line in proc.stdout.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("COMMIT:"):
            subject = line[7:].split(" ", 1)[1] if " " in line[7:] else ""
            is_fix_commit = bool(FIX_COMMIT_RE.search(subject))
            continue
        rel = _norm_path(line)
        if not rel:
            continue
        bucket = counts.setdefault(rel, [0, 0])
        bucket[0] += 1
        if is_fix_commit:
            bucket[1] += 1

    risk_map: dict[str, dict[str, Any]] = {}
    for rel, (commits, fix_commits) in sorted(counts.items()):
        risk_score = round((fix_commits + 1.0) / (commits + 3.0), 4)
        risk_map[rel] = {
            "commits": commits,
            "fix_commits": fix_commits,
            "risk_score": risk_score,
        }
    return risk_map


def record_outcome(
    root: Path,
    *,
    source: str,
    verdict: str,
    capabilities: list[str] | None = None,
    files: list[str] | None = None,
    commit: str = "",
    refresh_git: bool = False,
) -> dict[str, Any]:
    """Update Beta capability priors, optional git file risk, and bounded event log."""
    norm_verdict = verdict.strip().upper()
    if norm_verdict not in VALID_VERDICTS:
        raise ValueError(f"verdict must be one of {sorted(VALID_VERDICTS)}, got {verdict!r}")
    norm_source = source.strip()
    if not norm_source:
        raise ValueError("source must be a non-empty string")

    ledger = load_ledger(root)
    priors = ledger["capability_priors"]
    cap_list = [c.strip() for c in (capabilities or []) if c and c.strip()]
    for cap_id in cap_list:
        rec = priors.setdefault(
            cap_id,
            {"alpha": 1.0, "beta": 1.0, "trials": 0, "verified_passes": 0, "verified_fails": 0},
        )
        if norm_verdict == "PASS":
            rec["alpha"] = round(float(rec["alpha"]) + 1.0, 4)
            rec["verified_passes"] = int(rec["verified_passes"]) + 1
        else:
            rec["beta"] = round(float(rec["beta"]) + 1.0, 4)
            rec["verified_fails"] = int(rec["verified_fails"]) + 1
        rec["trials"] = int(rec["trials"]) + 1

    if refresh_git:
        git_risk = refresh_file_risk_from_git(root)
        if git_risk:
            ledger["file_risk"] = git_risk

    norm_files = [_norm_path(f) for f in (files or []) if f and _norm_path(f)]
    if norm_files and norm_verdict != "PASS":
        file_risk = ledger["file_risk"]
        for rel in norm_files:
            entry = file_risk.setdefault(rel, {"commits": 0, "fix_commits": 0, "risk_score": 0.3333})
            entry["commits"] = int(entry["commits"]) + 1
            entry["fix_commits"] = int(entry["fix_commits"]) + 1
            entry["risk_score"] = round((entry["fix_commits"] + 1.0) / (entry["commits"] + 3.0), 4)

    now_iso = datetime.now(timezone.utc).isoformat()
    ledger["updated_at"] = now_iso
    ledger["events"].append(
        {
            "observed_at": now_iso,
            "source": norm_source,
            "verdict": norm_verdict,
            "commit": commit.strip(),
            "capabilities": cap_list,
            "files": norm_files,
        }
    )
    if len(ledger["events"]) > MAX_LEDGER_EVENTS:
        ledger["events"] = ledger["events"][-MAX_LEDGER_EVENTS:]

    save_ledger(root, ledger)
    return ledger


def assess_risk(ledger: dict[str, Any], files: list[str], *, threshold: float = 0.45) -> dict[str, Any]:
    """Score candidate files using historical churn risk and referee boundary rules."""
    file_risk = ledger.get("file_risk", {}) if isinstance(ledger, dict) else {}
    assessed: list[dict[str, Any]] = []
    high_risk_files: list[str] = []
    referee_touched: list[str] = []

    for raw in files:
        rel = _norm_path(raw)
        if not rel:
            continue
        rec = file_risk.get(rel)
        score = float(rec["risk_score"]) if isinstance(rec, dict) and "risk_score" in rec else 0.25
        is_referee = any(rel == prefix or rel.startswith(prefix) for prefix in REFEREE_PREFIXES)
        if is_referee:
            referee_touched.append(rel)
        if score >= threshold:
            high_risk_files.append(rel)
        assessed.append(
            {
                "path": rel,
                "risk_score": round(score, 4),
                "high_risk": score >= threshold,
                "referee_boundary": is_referee,
                "commits": int(rec.get("commits", 0)) if isinstance(rec, dict) else 0,
                "fix_commits": int(rec.get("fix_commits", 0)) if isinstance(rec, dict) else 0,
            }
        )

    escalate = bool(high_risk_files or referee_touched)
    return {
        "threshold": threshold,
        "escalate": escalate,
        "recommended_action": (
            "ESCALATE: run mutation_gate.py + full pytest"
            if escalate
            else "STANDARD: run check + pytest"
        ),
        "high_risk_files": high_risk_files,
        "referee_touched": referee_touched,
        "files": assessed,
    }
