#!/usr/bin/env python3
"""Gate 2: Independent Adversarial Judgment Panel & Persistent Judgment Lessons.

Evaluates a document ONLY after it clears Gate 1 (Flow AST + 6-Role Floor + Strategic Charter).
Judges the actual editorial, operational, strategic, political, equity, reconciliation,
accessibility, and brand-voice judgment of the document as an independent cold-receiver
buying room, emitting a binding SIGN_OFF / REVISE / KILL verdict and persisting reusable
Judgment Lessons per document type.
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

from .doc_flow_engine import load_organization_charter

DEFAULT_RUBRICS_REL = Path(".agents") / "bench" / "judgment_rubrics.yaml"
DEFAULT_LESSONS_REL = Path(".agents") / "ml_judgment_lessons.json"

VALID_VERDICTS = ("SIGN_OFF", "REVISE", "KILL")


@dataclass
class JudgmentVerdict:
    ok: bool
    verdict: str  # SIGN_OFF | REVISE | KILL | UNAVAILABLE
    judgment_score: float
    weakest_quote: str = ""
    top_executive_objection: str = ""
    required_cut: str = ""
    actionable_fix: str = ""
    reusable_judgment_lesson: str = ""
    org_voice_flags: list[str] = field(default_factory=list)
    criteria_scores: dict[str, float] = field(default_factory=dict)
    raw_error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def load_judgment_rubrics(repo_root: Path) -> dict[str, Any]:
    """Load Gate 2 form + cross-cutting org/political/brand-voice judgment rubrics from YAML."""
    path = Path(repo_root) / DEFAULT_RUBRICS_REL
    if not path.is_file():
        return {"cross_cutting_org_and_brand_voice": [], "forms": {}}
    import yaml  # type: ignore

    raw = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or {}
    return raw if isinstance(raw, dict) else {"cross_cutting_org_and_brand_voice": [], "forms": {}}


def load_judgment_lessons(repo_root: Path, form_id: str, *, limit: int = 4) -> list[str]:
    """Retrieve the most recent reusable editorial/political/brand-voice lessons for a document type."""
    p = Path(repo_root) / DEFAULT_LESSONS_REL
    if not p.is_file():
        return []
    try:
        raw = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        if not isinstance(raw, dict):
            return []
        entry = raw.get(form_id, {})
        lessons = entry.get("lessons", []) if isinstance(entry, dict) else []
        return [str(x) for x in lessons[-limit:]]
    except Exception:
        return []


def record_judgment_lesson(
    repo_root: Path,
    form_id: str,
    verdict: JudgmentVerdict,
) -> None:
    """Persist reusable judgment lessons and recent objections per document type."""
    p = Path(repo_root) / DEFAULT_LESSONS_REL
    data: dict[str, Any] = {}
    if p.is_file():
        try:
            loaded = json.loads(p.read_text(encoding="utf-8", errors="replace"))
            if isinstance(loaded, dict):
                data = loaded
        except Exception:
            data = {}
    entry = data.setdefault(form_id, {"lessons": [], "recent_verdicts": []})
    lessons: list[str] = entry.setdefault("lessons", [])
    lesson = verdict.reusable_judgment_lesson.strip()
    if lesson and lesson not in lessons:
        lessons.append(lesson)
        if len(lessons) > 12:
            del lessons[:-12]
    recents: list[dict[str, Any]] = entry.setdefault("recent_verdicts", [])
    recents.append(
        {
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "verdict": verdict.verdict,
            "judgment_score": verdict.judgment_score,
            "top_executive_objection": verdict.top_executive_objection[:180],
            "required_cut": verdict.required_cut[:140],
        }
    )
    if len(recents) > 20:
        del recents[:-20]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def build_adversarial_judge_prompt(
    text: str,
    form_id: str,
    *,
    repo_root: Path,
    use_case_intent: str = "",
) -> str:
    """Build a strict cold-receiver adversarial critique prompt for Gate 2."""
    rubrics = load_judgment_rubrics(repo_root)
    charter = load_organization_charter(repo_root=repo_root)
    cross = rubrics.get("cross_cutting_org_and_brand_voice", [])
    form_cfg = (rubrics.get("forms") or {}).get(form_id, {})
    buying_room = form_cfg.get(
        "buying_room",
        ["Media Production Manager", "Marketing Manager", "Communications Strategist", "Marketing & Engagement Director", "Communications Director", "CEO"],
    )
    form_criteria = form_cfg.get("criteria", [])
    ai_trap = form_cfg.get("ai_trap", "Surface-level compliance with weak real-world judgment.")

    lines = [
        "You are an INDEPENDENT COLD-RECEIVER ADVERSARIAL BUYING PANEL. You did NOT write this draft.",
        "Your job is to catch real editorial, operational, strategic, political, equity, reconciliation, accessibility, and brand-voice flaws that mechanical checklists miss.",
        "Do NOT flatter. Do NOT give SIGN_OFF unless a real seasoned executive/manager would actually approve and act on this document today with zero clarifying emails.",
        "",
        f"Organization: {charter.org_name} | Strategic Plan: {charter.strategic_plan_name}",
        f"Mission: {charter.mission}",
        f"Vision North Star: {charter.vision_north_star}",
        f"Values: {', '.join(charter.values)} | Commitments: {', '.join(charter.commitments)}",
        f"Document Type: {form_id}",
        f"Buying Room Evaluating This Document: {', '.join(buying_room)}",
    ]
    if use_case_intent:
        lines.append(f"Assigned Use Case: {use_case_intent}")
    lines.append(f"#1 AI Trap to Watch For: {ai_trap}")
    lines.append("")
    lines.append("=== CROSS-CUTTING ORGANIZATIONAL, POLITICAL & BRAND VOICE CRITERIA ===")
    for item in cross:
        lines.append(f"- {item['id']}: {item['criterion']}")
    lines.append("")
    lines.append(f"=== FORM-SPECIFIC JUDGMENT CRITERIA ({form_id}) ===")
    for item in form_criteria:
        lines.append(f"- {item['id']}: {item['criterion']}")
    lines.extend(
        [
            "",
            "Return ONLY valid JSON (no prose outside JSON) with these exact keys:",
            "{",
            '  "verdict": "SIGN_OFF" | "REVISE" | "KILL",',
            '  "judgment_score": <float 0.00 to 1.00>,',
            '  "weakest_quote": "<exact short quote from the draft that is weakest or risks pushback>",',
            '  "top_executive_objection": "<the #1 concrete objection a buyer in the room would raise>",',
            '  "required_cut": "<one concrete sentence/bullet/detail to CUT for subtractive craft, or none>",',
            '  "actionable_fix": "<one concrete instruction to make the next revision genuinely better>",',
            '  "reusable_judgment_lesson": "<one reusable rule for writing better future docs of this type>",',
            '  "org_voice_flags": ["<any equity/reconciliation/accessibility/political/brand-voice flag, or empty list>"],',
            '  "criteria_scores": {"<criterion_id>": <float 0.0 to 1.0>}',
            "}",
            "",
            "Rules for verdict:",
            "- SIGN_OFF only if judgment_score >= 0.82 AND org_voice_flags is empty AND zero serious executive/feasibility objections remain.",
            "- REVISE if salvageable with targeted changes (score 0.50-0.81 or minor org/voice/logic gap).",
            "- KILL if fundamentally unconvincing, unshootable, politically risky, off-voice, or AI slop (score < 0.50).",
            "",
            "=== CANDIDATE DOCUMENT ===",
            text.strip()[:8000],
        ]
    )
    return "\n".join(lines) + "\n"


def parse_judge_response(raw_output: str) -> JudgmentVerdict:
    """Strictly parse the Gate 2 JSON critique; never invent SIGN_OFF on malformed output."""
    cleaned = raw_output.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", cleaned, flags=re.DOTALL | re.IGNORECASE)
    if fence:
        cleaned = fence.group(1).strip()
    else:
        start = cleaned.find("{")
        end = cleaned.rfind("}")
        if start >= 0 and end > start:
            cleaned = cleaned[start : end + 1]

    try:
        parsed = json.loads(cleaned)
    except Exception as exc:
        return JudgmentVerdict(
            ok=False,
            verdict="UNAVAILABLE",
            judgment_score=0.0,
            raw_error=f"judge_json_parse_error: {exc}",
        )
    if not isinstance(parsed, dict):
        return JudgmentVerdict(
            ok=False,
            verdict="UNAVAILABLE",
            judgment_score=0.0,
            raw_error="judge_json_not_object",
        )

    verdict = str(parsed.get("verdict", "")).strip().upper()
    if verdict not in VALID_VERDICTS:
        return JudgmentVerdict(
            ok=False,
            verdict="UNAVAILABLE",
            judgment_score=0.0,
            raw_error=f"invalid_judge_verdict: {verdict!r}",
        )

    try:
        score = max(0.0, min(1.0, round(float(parsed.get("judgment_score", 0.0)), 3)))
    except (TypeError, ValueError):
        score = 0.0

    flags = [str(x).strip() for x in (parsed.get("org_voice_flags") or []) if str(x).strip()]
    crit_raw = parsed.get("criteria_scores") or {}
    crit_scores: dict[str, float] = {}
    if isinstance(crit_raw, dict):
        for k, v in crit_raw.items():
            try:
                crit_scores[str(k)] = max(0.0, min(1.0, round(float(v), 3)))
            except (TypeError, ValueError):
                continue

    # Enforce strict SIGN_OFF invariant even if the critic was overly lenient
    if verdict == "SIGN_OFF" and (score < 0.82 or bool(flags)):
        verdict = "REVISE"

    return JudgmentVerdict(
        ok=(verdict == "SIGN_OFF"),
        verdict=verdict,
        judgment_score=score,
        weakest_quote=str(parsed.get("weakest_quote", "")).strip(),
        top_executive_objection=str(parsed.get("top_executive_objection", "")).strip(),
        required_cut=str(parsed.get("required_cut", "")).strip(),
        actionable_fix=str(parsed.get("actionable_fix", "")).strip(),
        reusable_judgment_lesson=str(parsed.get("reusable_judgment_lesson", "")).strip(),
        org_voice_flags=flags,
        criteria_scores=crit_scores,
    )


def run_adversarial_judgment(
    text: str,
    form_id: str,
    *,
    repo_root: Path,
    worker_fn: Callable[..., tuple[bool, str]],
    timeout_s: float = 90.0,
    use_case_intent: str = "",
    persist_lesson: bool = True,
) -> JudgmentVerdict:
    """Invoke an independent cold-receiver critic pass (Gate 2) and persist reusable judgment lessons."""
    prompt = build_adversarial_judge_prompt(
        text, form_id, repo_root=repo_root, use_case_intent=use_case_intent
    )
    try:
        ok, raw = worker_fn(prompt, repo_root, timeout_s, effort="medium")
    except TypeError:
        ok, raw = worker_fn(prompt, repo_root, timeout_s)

    if not ok:
        return JudgmentVerdict(
            ok=False,
            verdict="UNAVAILABLE",
            judgment_score=0.0,
            raw_error=raw[:240],
        )

    verdict = parse_judge_response(raw)
    if persist_lesson and verdict.verdict in VALID_VERDICTS:
        record_judgment_lesson(repo_root, form_id, verdict)
    return verdict
