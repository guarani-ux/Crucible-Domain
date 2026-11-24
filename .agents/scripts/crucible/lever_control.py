#!/usr/bin/env python3
"""Layers 3 & 4: Discrete Control Lever Registry & Compact Steering-Wheel Telemetry Packet.

Zero LLM tokens. Loads parameterized control levers from `.agents/bench/levers.yaml`,
scans local deliverables through Layers 1 & 2 (Flow AST + 6-Role Board + 40-Feature ML),
emits a compact ~200-token steering packet for human or on-demand LLM decision-making,
and deterministically applies pulled levers into `.agents/ml_learned_policies.json`.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .doc_ml_scorer import load_or_train_model, score_document_ml


DEFAULT_LEVERS_REL = Path(".agents") / "bench" / "levers.yaml"
DEFAULT_POLICIES_REL = Path(".agents") / "ml_learned_policies.json"
DEFAULT_LEVER_LOG_REL = Path(".agents") / "bench_lever_log.jsonl"

FORM_INFER_MAP: dict[str, str] = {
    "av-script": "av_script",
    "av_script": "av_script",
    "brief": "production_brief",
    "research": "research_note",
    "bottleneck-radar": "research_note",
    "treatment": "treatment",
    "call-sheet": "call_sheet",
    "call_sheet": "call_sheet",
    "shot-list": "shot_list",
    "shot_list": "shot_list",
    "executive-summary": "leadership_report",
    "content-calendar": "content_calendar",
}


def load_lever_registry(repo_root: Path) -> dict[str, dict[str, Any]]:
    """Load the discrete lever registry from `.agents/bench/levers.yaml`."""
    path = Path(repo_root) / DEFAULT_LEVERS_REL
    if not path.is_file():
        return {}
    import yaml  # type: ignore

    raw = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or {}
    out: dict[str, dict[str, Any]] = {}
    for item in raw.get("levers", []):
        if isinstance(item, dict) and item.get("id"):
            out[str(item["id"])] = item
    return out


def pull_lever(
    repo_root: Path,
    lever_id: str,
    *,
    form_id: str = "all",
    reason: str = "manual_or_steering_pull",
) -> dict[str, Any]:
    """Deterministically apply a discrete lever into `.agents/ml_learned_policies.json` and log it."""
    registry = load_lever_registry(repo_root)
    if lever_id not in registry:
        raise ValueError(f"Unknown lever '{lever_id}'. Available: {sorted(registry.keys())}")
    lever = registry[lever_id]
    rule_text = f"[LEVER:{lever_id}] {lever['policy_rule']}"

    pol_path = Path(repo_root) / DEFAULT_POLICIES_REL
    policies: dict[str, Any] = {}
    if pol_path.is_file():
        try:
            policies = json.loads(pol_path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            policies = {}
    if not isinstance(policies, dict):
        policies = {}

    target_forms = (
        [form_id]
        if form_id and form_id != "all"
        else [
            "production_brief",
            "leadership_report",
            "av_script",
            "research_note",
            "treatment",
            "call_sheet",
            "shot_list",
            "content_calendar",
        ]
    )
    updated_forms: list[str] = []
    for fid in target_forms:
        entry = policies.setdefault(fid, {"rules": [], "active_levers": []})
        if not isinstance(entry, dict):
            entry = {"rules": [], "active_levers": []}
            policies[fid] = entry
        rules = entry.setdefault("rules", [])
        active = entry.setdefault("active_levers", [])
        if rule_text not in rules:
            rules.append(rule_text)
        if lever_id not in active:
            active.append(lever_id)
        updated_forms.append(fid)

    pol_path.parent.mkdir(parents=True, exist_ok=True)
    pol_path.write_text(json.dumps(policies, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    log_row = {
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "lever_id": lever_id,
        "form_id": form_id,
        "reason": reason,
        "updated_forms": updated_forms,
    }
    log_path = Path(repo_root) / DEFAULT_LEVER_LOG_REL
    with log_path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(log_row, ensure_ascii=False) + "\n")

    return {"ok": True, **log_row, "policy_rule": lever["policy_rule"]}


def _infer_form(path: Path) -> str | None:
    key = f"{path.parent.name}/{path.name}".lower()
    for pat, fid in FORM_INFER_MAP.items():
        if pat in key:
            return fid
    return None


def build_steering_packet(
    repo_root: Path,
    *,
    auto_apply: bool = False,
    max_levers: int = 3,
) -> dict[str, Any]:
    """Scan local deliverables offline and build a compact ~200-token steering-wheel packet."""
    t0 = time.perf_counter()
    registry = load_lever_registry(repo_root)
    model = load_or_train_model(repo_root)

    runs_dir = Path(repo_root) / ".agents" / "bench_runs"
    candidates: list[tuple[Path, str]] = []
    if runs_dir.is_dir():
        for p in sorted(runs_dir.rglob("*.md")):
            fid = _infer_form(p)
            if fid:
                candidates.append((p, fid))

    total = 0
    passed = 0
    form_stats: dict[str, dict[str, Any]] = {}
    role_blocks: dict[str, int] = {}
    lever_hits: dict[str, int] = {}
    neg_driver_hits: dict[str, int] = {}

    for p, fid in candidates:
        text = p.read_text(encoding="utf-8", errors="replace")
        res = score_document_ml(text, fid, repo_root=repo_root, model=model)
        total += 1
        is_ok = bool(res["ok"])
        if is_ok:
            passed += 1
        st = form_stats.setdefault(fid, {"pass": 0, "total": 0, "prob_sum": 0.0})
        st["total"] += 1
        st["pass"] += int(is_ok)
        st["prob_sum"] += float(res["buy_in_probability"])
        for br in res["blocking_roles"]:
            role_blocks[br] = role_blocks.get(br, 0) + 1
        for lv in res["recommended_levers"]:
            if lv in registry:
                lever_hits[lv] = lever_hits.get(lv, 0) + 1
        for drv in res["top_negative_drivers"][:2]:
            feat = str(drv["feature"])
            neg_driver_hits[feat] = neg_driver_hits.get(feat, 0) + 1

    ranked_levers = sorted(lever_hits.items(), key=lambda kv: -kv[1])[:max_levers]
    weakest_forms = sorted(
        [(fid, round(st["prob_sum"] / st["total"], 3), st["pass"], st["total"]) for fid, st in form_stats.items()],
        key=lambda x: x[1],
    )[:3]

    applied: list[dict[str, Any]] = []
    if auto_apply:
        for lv_id, _cnt in ranked_levers:
            applied.append(pull_lever(repo_root, lv_id, form_id="all", reason="bench_steer_auto_apply"))

    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
    pass_rate = round(passed / total, 4) if total else 1.0
    compact_prompt_brief = (
        f"OFFLINE STEERING PACKET ({total} docs, {elapsed_ms}ms, 0 tokens): "
        f"buy_in_ready={passed}/{total} ({pass_rate:.0%}) | "
        f"weakest_forms={[f'{f}:{p:.2f}({ok}/{n})' for f, p, ok, n in weakest_forms]} | "
        f"top_blocking_roles={sorted(role_blocks.items(), key=lambda x: -x[1])[:4]} | "
        f"top_neg_features={sorted(neg_driver_hits.items(), key=lambda x: -x[1])[:4]} | "
        f"recommended_levers={[lv for lv, _ in ranked_levers]}"
    )

    return {
        "ok": True,
        "elapsed_ms": elapsed_ms,
        "docs_scanned": total,
        "buy_in_ready": passed,
        "pass_rate": pass_rate,
        "weakest_forms": [
            {"form_id": f, "avg_buy_in_prob": p, "passed": ok, "total": n}
            for f, p, ok, n in weakest_forms
        ],
        "top_blocking_roles": sorted(role_blocks.items(), key=lambda x: -x[1]),
        "top_negative_features": sorted(neg_driver_hits.items(), key=lambda x: -x[1])[:5],
        "recommended_levers": [
            {"lever_id": lv, "hits": cnt, "rule": registry[lv]["policy_rule"]}
            for lv, cnt in ranked_levers
        ],
        "applied_levers": applied,
        "compact_steering_brief": compact_prompt_brief,
    }
