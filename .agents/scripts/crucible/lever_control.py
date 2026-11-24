#!/usr/bin/env python3
"""Layers 3 & 4: Discrete Control Lever Registry & Compact Steering-Wheel Telemetry Packet.

Zero LLM tokens. Loads parameterized control levers from `.agents/bench/levers.yaml`,
scans local deliverables through Layers 1 & 2 (Flow AST + 6-Role Board + 40-Feature ML),
emits a compact ~200-token steering packet for human or on-demand LLM decision-making,
and deterministically applies pulled levers into `.agents/ml_learned_policies.json`.
"""

from __future__ import annotations

import hashlib
import itertools
import json
import time
from pathlib import Path
from typing import Any

from .doc_flow_engine import (
    GOLDEN_SPECIMENS,
    MUTATION_CATALOG,
    evaluate_document_flow,
    evaluate_stakeholder_board,
)
from .doc_ml_scorer import load_or_train_model, score_document_ml
from .form_diagnostics import diagnose_form_deliverable


DEFAULT_LEVERS_REL = Path(".agents") / "bench" / "levers.yaml"
DEFAULT_POLICIES_REL = Path(".agents") / "ml_learned_policies.json"
DEFAULT_LEVER_LOG_REL = Path(".agents") / "bench_lever_log.jsonl"
DEFAULT_TRIAL_STATE_REL = Path(".agents") / "bench_trial_state.json"
DEFAULT_TRIAL_TEL_REL = Path(".agents") / "bench_trial_telemetry.jsonl"

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


def _build_combinatorial_trial_pool(repo_root: Path) -> list[dict[str, Any]]:
    """Build deterministic, non-redundant pool of real-corpus + 1/2/3-fault stacked benchmark trials."""
    pool: list[dict[str, Any]] = []

    # 1. Real saved deliverables from bench_runs/ and Calgary Public Library/
    real_sources: list[tuple[str, Path, str]] = []
    cpl_map = [
        ("cpl:pitch_brief", Path("Calgary Public Library/youtube-series-pitch/06_stakeholder_pitch_brief.md"), "production_brief"),
        ("cpl:five_series", Path("Calgary Public Library/youtube-series-pitch/03_five_series_pitch.md"), "treatment"),
        ("cpl:ep01_script", Path("Calgary Public Library/pilot-a-the-next-question-ep01/01_av_script_v1.md"), "av_script"),
        ("cpl:ep01_call_sheet", Path("Calgary Public Library/pilot-a-the-next-question-ep01/02_capture_plan_and_call_sheet.md"), "call_sheet"),
    ]
    for label, rel, fid in cpl_map:
        p = repo_root / rel
        if p.is_file():
            real_sources.append((label, p, fid))

    runs_dir = repo_root / ".agents" / "bench_runs"
    if runs_dir.is_dir():
        for p in sorted(runs_dir.rglob("*.md")):
            fid = _infer_form(p)
            if fid:
                real_sources.append((f"run:{p.parent.parent.name}/{p.parent.name}", p, fid))

    for label, p, fid in real_sources:
        txt = p.read_text(encoding="utf-8", errors="replace")
        fp = hashlib.sha256(f"real|{fid}|{txt}".encode("utf-8")).hexdigest()[:16]
        pool.append(
            {
                "trial_id": fp,
                "kind": "real_corpus",
                "specimen": label,
                "form_id": fid,
                "target_duration_s": None,
                "mutations": (),
                "text": txt,
                "expected_pass": None,
            }
        )

    # 2. Golden specimens + 1-fault, 2-fault, and 3-fault stacked combinations
    for spec_id, spec in GOLDEN_SPECIMENS.items():
        fid = spec["form_id"]
        target_dur = spec.get("target_duration_s")
        base_text = spec["text"]
        applicable = [
            (m_name, m_fn)
            for m_name, (forms, m_fn) in MUTATION_CATALOG.items()
            if fid in forms and not (m_name == "truncate_runtime_half" and (target_dur is None or target_dur < 60))
        ]
        # Tier 1: single faults, Tier 2: 2-fault combos, Tier 3: 3-fault combos
        for combo_len in (1, 2, 3):
            for combo in itertools.combinations(applicable, combo_len):
                names = tuple(c[0] for c in combo)
                fp = hashlib.sha256(f"mut|{spec_id}|{'+'.join(names)}".encode("utf-8")).hexdigest()[:16]
                pool.append(
                    {
                        "trial_id": fp,
                        "kind": f"stacked_{combo_len}f",
                        "specimen": spec_id,
                        "form_id": fid,
                        "target_duration_s": target_dur,
                        "mutations": names,
                        "base_text": base_text,
                        "mut_fns": tuple(c[1] for c in combo),
                        "expected_pass": False,
                    }
                )
    return pool


def run_offline_trial_loop(
    repo_root: Path,
    *,
    rounds: int = 10,
    batch_size: int = 24,
    drr_threshold: float = 0.98,
    reset: bool = False,
) -> dict[str, Any]:
    """Run non-redundant offline benchmark trials until rounds complete or Total Diminishing Returns Ratio (DRR) triggers."""
    t0 = time.perf_counter()
    state_path = Path(repo_root) / DEFAULT_TRIAL_STATE_REL
    tel_path = Path(repo_root) / DEFAULT_TRIAL_TEL_REL

    state: dict[str, Any] = {
        "seen_trial_ids": [],
        "seen_discovery_keys": [],
        "recent_yields": [],
        "total_trials_ever": 0,
        "total_discoveries_ever": 0,
    }
    if not reset and state_path.is_file():
        try:
            loaded = json.loads(state_path.read_text(encoding="utf-8", errors="replace"))
            if isinstance(loaded, dict):
                state.update(loaded)
        except Exception:
            pass

    seen_ids = set(state.get("seen_trial_ids", []))
    seen_disc = set(state.get("seen_discovery_keys", []))
    recent_yields: list[float] = [float(x) for x in state.get("recent_yields", [])]

    pool = _build_combinatorial_trial_pool(repo_root)
    unseen = [item for item in pool if item["trial_id"] not in seen_ids]
    model = load_or_train_model(repo_root)

    round_summaries: list[dict[str, Any]] = []
    rubric_weakest_by_form: dict[str, dict[str, int]] = {}
    rubric_levers_by_form: dict[str, dict[str, int]] = {}
    stopped_reason = "rounds_completed"
    drr = 0.0
    cursor = 0

    for r_idx in range(1, max(1, rounds) + 1):
        batch = unseen[cursor : cursor + max(1, batch_size)]
        cursor += len(batch)
        if not batch:
            stopped_reason = "frontier_exhausted"
            drr = 1.0
            break

        new_disc_this_round = 0
        surviving_mutants = 0
        ml_disagreements = 0
        real_failures = 0

        for item in batch:
            seen_ids.add(item["trial_id"])
            fid = item["form_id"]
            target_dur = item["target_duration_s"]
            if "text" in item:
                text = item["text"]
            else:
                text = item["base_text"]
                for fn in item["mut_fns"]:
                    text = fn(text)

            diag = diagnose_form_deliverable(text, fid, repo_root=repo_root, strict_cpl_mandates=True)
            fe = evaluate_document_flow(text, fid, target_duration_s=target_dur)
            bd = evaluate_stakeholder_board(text, fid, flow_eval=fe, target_duration_s=target_dur, repo_root=repo_root)
            ml = score_document_ml(text, fid, repo_root=repo_root, target_duration_s=target_dur, model=model)
            board_ok = fe.passed and bd.buy_in_ready

            # Track per-form 5-element writing rubric weakest element & adjustment levers
            w_el = diag.weakest_element or diag.weakest_aspect
            if w_el:
                f_els = rubric_weakest_by_form.setdefault(fid, {})
                f_els[w_el] = f_els.get(w_el, 0) + 1
            for lv in dict.fromkeys(fe.recommended_levers + bd.recommended_levers):
                f_lvs = rubric_levers_by_form.setdefault(fid, {})
                f_lvs[lv] = f_lvs.get(lv, 0) + 1

            # Track novel discoveries (unique failure signatures never seen before)
            if item["expected_pass"] is False and board_ok:
                surviving_mutants += 1
                dk = f"survivor:{fid}:{'+'.join(item['mutations'])}"
                if dk not in seen_disc:
                    seen_disc.add(dk)
                    new_disc_this_round += 1

            if (ml["verdict"] == "PASS") != board_ok:
                ml_disagreements += 1
                dk = f"ml_gap:{fid}:{item['kind']}:{','.join(bd.blocking_roles)}"
                if dk not in seen_disc:
                    seen_disc.add(dk)
                    new_disc_this_round += 1

            if item["kind"] == "real_corpus" and not board_ok:
                real_failures += 1
                dk = f"real_blocker:{fid}:{w_el}:{','.join(bd.blocking_roles)}:{','.join(bd.recommended_levers[:2])}"
                if dk not in seen_disc:
                    seen_disc.add(dk)
                    new_disc_this_round += 1

        n_trials = len(batch)
        novelty_yield = round(new_disc_this_round / max(1, n_trials), 4)
        recent_yields.append(novelty_yield)
        window = recent_yields[-3:]
        rolling_yield = sum(window) / len(window)
        drr = round(max(0.0, min(1.0, 1.0 - rolling_yield)), 4)

        r_rec = {
            "round": r_idx,
            "trials": n_trials,
            "new_discoveries": new_disc_this_round,
            "novelty_yield": novelty_yield,
            "drr": drr,
            "surviving_mutants": surviving_mutants,
            "ml_disagreements": ml_disagreements,
            "real_failures": real_failures,
            "remaining_frontier": max(0, len(unseen) - cursor),
        }
        round_summaries.append(r_rec)
        tel_path.parent.mkdir(parents=True, exist_ok=True)
        with tel_path.open("a", encoding="utf-8", newline="\n") as tf:
            tf.write(json.dumps({"timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), **r_rec}) + "\n")

        if len(recent_yields) >= 3 and drr >= drr_threshold:
            stopped_reason = "diminishing_returns_reached"
            break

    state["seen_trial_ids"] = sorted(seen_ids)
    state["seen_discovery_keys"] = sorted(seen_disc)
    state["recent_yields"] = recent_yields[-12:]
    state["total_trials_ever"] = len(seen_ids)
    state["total_discoveries_ever"] = len(seen_disc)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    rubric_adjustments: dict[str, dict[str, Any]] = {}
    for fid in sorted(set(rubric_weakest_by_form) | set(rubric_levers_by_form)):
        top_el = max(rubric_weakest_by_form.get(fid, {}).items(), key=lambda x: x[1])[0] if rubric_weakest_by_form.get(fid) else ""
        top_lv = sorted(rubric_levers_by_form.get(fid, {}).items(), key=lambda x: -x[1])[:2]
        rubric_adjustments[fid] = {
            "weakest_rubric_element": top_el,
            "top_adjustment_levers": [lv for lv, _ in top_lv],
        }

    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
    return {
        "ok": True,
        "elapsed_ms": elapsed_ms,
        "rounds_executed": len(round_summaries),
        "stopped_reason": stopped_reason,
        "drr": drr,
        "drr_threshold": drr_threshold,
        "total_pool_size": len(pool),
        "total_trials_ever": len(seen_ids),
        "remaining_frontier": max(0, len(unseen) - cursor),
        "total_unique_discoveries": len(seen_disc),
        "rubric_adjustments_by_form": rubric_adjustments,
        "rounds": round_summaries,
    }
