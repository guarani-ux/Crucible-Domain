#!/usr/bin/env python3
"""Component 4 & 5: Controlled Paired A/B Outcome Ratchet & 3-Axis Inspection Dashboard.

Eliminates blind lesson accumulation. Every proposed judgment lesson starts as CANDIDATE,
is tested on the next paired trial of the exact same (form_id, use_case_id), and is:
  - PROMOTED to ACTIVE only if the target Root Axis improves by >= +0.05 (or verdict flips to SIGN_OFF)
    without either other axis regressing by > 0.05;
  - QUARANTINED otherwise (recorded with exact delta so failed advice is never repeated).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

DEFAULT_RATCHET_REL = Path(".agents") / "ml_outcome_ratchet.json"

AXIS_KEYS = ("axis_1_integrity", "axis_2_rhetorical_force", "axis_3_executability")


def _default_state() -> dict[str, Any]:
    return {
        "version": "1.0",
        "forms": {},
        "experiments": [],
    }


def load_ratchet_state(repo_root: Path) -> dict[str, Any]:
    p = Path(repo_root) / DEFAULT_RATCHET_REL
    if p.is_file():
        try:
            raw = json.loads(p.read_text(encoding="utf-8", errors="replace"))
            if isinstance(raw, dict):
                raw.setdefault("forms", {})
                raw.setdefault("experiments", [])
                return raw
        except Exception:
            pass
    return _default_state()


def save_ratchet_state(repo_root: Path, state: dict[str, Any]) -> None:
    p = Path(repo_root) / DEFAULT_RATCHET_REL
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def get_active_promoted_lessons(repo_root: Path, form_id: str, *, limit: int = 5) -> list[str]:
    """Return ONLY lessons that passed paired A/B promotion (plus at most 1 active CANDIDATE under test)."""
    state = load_ratchet_state(repo_root)
    f_rec = state.get("forms", {}).get(form_id, {})
    promoted = [str(x["lesson"]) for x in f_rec.get("promoted_lessons", []) if isinstance(x, dict) and x.get("lesson")]
    cand = f_rec.get("pending_candidate")
    out = promoted[-limit:]
    if isinstance(cand, dict) and cand.get("lesson") and str(cand["lesson"]) not in out:
        out.append(f"[TESTING CANDIDATE] {cand['lesson']}")
    return out


def record_paired_outcome(
    repo_root: Path,
    *,
    form_id: str,
    use_case_id: str,
    axis_scores: dict[str, float],
    verdict: str,
    weakest_engine: str = "",
    proposed_lesson: str = "",
    min_gain: float = 0.05,
    max_regression: float = 0.05,
) -> dict[str, Any]:
    """Record a 3-Axis observation, evaluate any pending CANDIDATE on a paired (form, use_case), and ratchet."""
    state = load_ratchet_state(repo_root)
    f_rec = state["forms"].setdefault(
        form_id,
        {
            "baseline_axes": None,
            "latest_axes": None,
            "runs": 0,
            "sign_offs": 0,
            "promoted_lessons": [],
            "quarantined_lessons": [],
            "pending_candidate": None,
            "weakest_engine_counts": {},
        },
    )

    clean_axes = {k: round(float(axis_scores.get(k, 0.0)), 3) for k in AXIS_KEYS}
    f_rec["runs"] = int(f_rec.get("runs", 0)) + 1
    if verdict == "SIGN_OFF":
        f_rec["sign_offs"] = int(f_rec.get("sign_offs", 0)) + 1
    if f_rec["baseline_axes"] is None:
        f_rec["baseline_axes"] = dict(clean_axes)
    f_rec["latest_axes"] = dict(clean_axes)
    if weakest_engine:
        we = f_rec.setdefault("weakest_engine_counts", {})
        we[weakest_engine] = int(we.get(weakest_engine, 0)) + 1

    ratchet_event: dict[str, Any] = {"action": "observed", "form_id": form_id, "use_case_id": use_case_id}

    # Evaluate pending candidate if this is a paired follow-up on the same (form_id, use_case_id)
    cand = f_rec.get("pending_candidate")
    if isinstance(cand, dict) and cand.get("use_case_id") == use_case_id:
        before_axes = cand["before_axes"]
        target_axis = cand["target_axis"]
        deltas = {k: round(clean_axes[k] - float(before_axes.get(k, 0.0)), 3) for k in AXIS_KEYS}
        target_delta = deltas[target_axis]
        other_min_delta = min(deltas[k] for k in AXIS_KEYS if k != target_axis)
        flipped_to_signoff = (cand.get("before_verdict") != "SIGN_OFF") and (verdict == "SIGN_OFF")

        improved = (target_delta >= min_gain or flipped_to_signoff) and (other_min_delta >= -max_regression)
        exp_rec = {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "form_id": form_id,
            "use_case_id": use_case_id,
            "lesson": cand["lesson"],
            "target_axis": target_axis,
            "before_axes": before_axes,
            "after_axes": clean_axes,
            "deltas": deltas,
            "before_verdict": cand.get("before_verdict"),
            "after_verdict": verdict,
            "decision": "PROMOTED" if improved else "QUARANTINED",
        }
        state["experiments"].append(exp_rec)
        if len(state["experiments"]) > 100:
            del state["experiments"][:-100]

        if improved:
            f_rec["promoted_lessons"].append(
                {"lesson": cand["lesson"], "target_axis": target_axis, "delta": target_delta, "deltas": deltas}
            )
            ratchet_event = {"action": "PROMOTED", **exp_rec}
        else:
            f_rec["quarantined_lessons"].append(
                {
                    "lesson": cand["lesson"],
                    "target_axis": target_axis,
                    "delta": target_delta,
                    "reason": f"target_delta={target_delta:+.3f}, min_other_delta={other_min_delta:+.3f}",
                }
            )
            ratchet_event = {"action": "QUARANTINED", **exp_rec}
        f_rec["pending_candidate"] = None

    # Stage a new candidate lesson if draft did not SIGN_OFF and lesson hasn't already been promoted/quarantined
    clean_lesson = proposed_lesson.strip()
    if clean_lesson and verdict != "SIGN_OFF" and f_rec.get("pending_candidate") is None:
        known = {x["lesson"] for x in f_rec["promoted_lessons"] if isinstance(x, dict)} | {
            x["lesson"] for x in f_rec["quarantined_lessons"] if isinstance(x, dict)
        }
        if clean_lesson not in known:
            weakest_axis = min(AXIS_KEYS, key=lambda k: clean_axes[k])
            f_rec["pending_candidate"] = {
                "lesson": clean_lesson,
                "use_case_id": use_case_id,
                "target_axis": weakest_axis,
                "before_axes": clean_axes,
                "before_verdict": verdict,
                "staged_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            }
            if ratchet_event["action"] == "observed":
                ratchet_event = {
                    "action": "STAGED_CANDIDATE",
                    "form_id": form_id,
                    "use_case_id": use_case_id,
                    "target_axis": weakest_axis,
                    "lesson": clean_lesson,
                }

    save_ratchet_state(repo_root, state)
    return ratchet_event


def build_outcome_matrix(repo_root: Path) -> dict[str, Any]:
    """Build the inspectable 3-Axis x 5-Engine x 8-Form Outcome Matrix for `bench inspect`."""
    state = load_ratchet_state(repo_root)
    forms_out: dict[str, Any] = {}
    total_promoted = 0
    total_quarantined = 0
    bottlenecks: list[tuple[float, str, str]] = []

    for fid, rec in sorted(state.get("forms", {}).items()):
        base = rec.get("baseline_axes") or {k: 0.0 for k in AXIS_KEYS}
        lat = rec.get("latest_axes") or {k: 0.0 for k in AXIS_KEYS}
        deltas = {k: round(float(lat.get(k, 0.0)) - float(base.get(k, 0.0)), 3) for k in AXIS_KEYS}
        weak_ax = min(AXIS_KEYS, key=lambda k: float(lat.get(k, 0.0)))
        bottlenecks.append((float(lat.get(weak_ax, 0.0)), fid, weak_ax))
        prom = rec.get("promoted_lessons", [])
        quar = rec.get("quarantined_lessons", [])
        total_promoted += len(prom)
        total_quarantined += len(quar)
        we_counts = rec.get("weakest_engine_counts", {})
        top_we = max(we_counts.items(), key=lambda x: x[1])[0] if we_counts else ""
        forms_out[fid] = {
            "runs": rec.get("runs", 0),
            "sign_offs": rec.get("sign_offs", 0),
            "baseline_axes": base,
            "latest_axes": lat,
            "net_deltas": deltas,
            "weakest_axis": weak_ax,
            "top_weakest_engine": top_we,
            "promoted_count": len(prom),
            "quarantined_count": len(quar),
            "has_pending_candidate": rec.get("pending_candidate") is not None,
        }

    bottlenecks.sort(key=lambda x: x[0])
    top_bn = (
        {"form_id": bottlenecks[0][1], "axis": bottlenecks[0][2], "score": bottlenecks[0][0]}
        if bottlenecks
        else None
    )
    return {
        "ok": True,
        "forms_tracked": len(forms_out),
        "total_promoted_lessons": total_promoted,
        "total_quarantined_lessons": total_quarantined,
        "total_experiments": len(state.get("experiments", [])),
        "top_bottleneck": top_bn,
        "forms": forms_out,
        "recent_experiments": state.get("experiments", [])[-5:],
    }
