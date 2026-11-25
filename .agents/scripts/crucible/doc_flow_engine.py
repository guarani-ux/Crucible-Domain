#!/usr/bin/env python3
"""Offline Document Information-Flow AST, 8-form Flow State Machines, and Zero-LLM Mutation Fuzzer.

Zero cloud quota, zero LLM calls. Parses Markdown deliverables into an ordered
Section & Block AST, evaluates per-form information-flow invariants, emits
discrete control-lever recommendations, and stress-tests all 8 forms with a
deterministic mutation fuzzer.
"""

from __future__ import annotations

import math
import random
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable


STOPWORDS = frozenset(
    {
        "the", "and", "for", "with", "that", "this", "from", "into", "over",
        "your", "our", "are", "was", "were", "have", "has", "had", "not",
        "but", "can", "will", "just", "than", "then", "them", "they", "their",
        "you", "out", "about", "all", "one", "two", "how", "who", "what",
        "when", "where", "why", "its", "her", "his", "she", "him", "here",
    }
)

SLOP_PATTERNS = (
    r"\bin today'?s fast-paced\b",
    r"\bdelve into\b",
    r"\btapestry\b",
    r"\bgame-?changer\b",
    r"\bsynergy\b",
    r"\bleverage our\b",
    r"\bseamless(?:ly)?\b",
    r"\btransformative journey\b",
    r"\bunlock the power\b",
)

TIMECODE_SPAN_RE = re.compile(r"(\d{1,2}):(\d{2})\s*[-–]\s*(\d{1,2}):(\d{2})")
TIMECODE_ROW_RE = re.compile(
    r"^\|\s*(?:[^|]*\|\s*)?(\d{1,2}):(\d{2})\s*[-–]\s*(\d{1,2}):(\d{2})\s*\|\s*(.*?)\s*\|\s*(.*?)\s*\|"
)
CITATION_RE = re.compile(
    r"(?:[\w./-]+\.(?:md|py|json|yaml|yml|csv|docx|pdf)\b|\b(?:GROUND_TRUTH|MW-\d{2}|MP-\d{2}|MK-\d{2}|CD-\d{2}|CH-\d{2}|OP-\d{2}|K-[A-Z]+-\d{2})\b)"
)
HOLD_LINE_RE = re.compile(r"(\[UNKNOWN|TBD\b|OPEN HOLD|PENDING\b|HOLD:)", re.IGNORECASE)
OWNER_HINT_RE = re.compile(
    r"\b(owner|producer|director|lead|manager|editor|host|librarian|communications|comms|service owner|programme owner|program owner|confirm(?:ed)? by|assigned to|@[\w-]+)\b",
    re.IGNORECASE,
)
MANDATE_LENS_TRAP_RE = re.compile(
    r"(?:official\s+(?:2027[-–]2030\s+)?)?mandates?\b[^.\n]{0,80}\b(Grow|Books\s*&\s*Reading|Community)\b",
    re.IGNORECASE,
)
MANDATE_NEGATION_RE = re.compile(
    r"\b(distinct from|never label|not official|not a mandate|separate from|rather than|unlike|do not confuse|kept separate)\b",
    re.IGNORECASE,
)


def has_mandate_lens_trap(text: str) -> bool:
    """Return True if text labels an internal editorial lens as an official mandate (ignoring explicit disclaimers)."""
    for ln in text.splitlines():
        if MANDATE_LENS_TRAP_RE.search(ln) and not MANDATE_NEGATION_RE.search(ln):
            return True
    return False
UNAUTHORIZED_RELEASE_RE = re.compile(
    r"\b(approved for release|asana updated|published live|g06 cleared|cleared for broadcast)\b",
    re.IGNORECASE,
)


@dataclass
class TimecodeBeat:
    start_s: int
    end_s: int
    duration_s: int
    audio: str
    video: str
    audio_words: int
    beat_wpm: float
    av_overlap: float


@dataclass
class DocSection:
    level: int
    heading: str
    slug: str
    start_line: int
    end_line: int
    position_ratio: float
    body: str
    word_count: int
    citations: list[str] = field(default_factory=list)
    hold_lines: list[str] = field(default_factory=list)
    holds_with_owner: int = 0


@dataclass
class DocumentAST:
    total_lines: int
    total_words: int
    sections: list[DocSection]
    tables: list[list[list[str]]]
    timecode_beats: list[TimecodeBeat]
    citations: list[str]
    hold_count: int
    holds_with_owner: int
    slop_hits: int
    avg_sentence_words: float


@dataclass
class FlowEvaluation:
    form_id: str
    flow_score: float
    passed: bool
    violations: list[str]
    section_flow: list[str]
    features: dict[str, Any]
    recommended_levers: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _content_tokens(text: str) -> set[str]:
    return {
        t
        for t in re.findall(r"[a-z]{3,}", text.lower())
        if t not in STOPWORDS
    }


def _hold_has_named_owner(line: str) -> bool:
    """Return True if a hold line names an actual owner/role outside the [UNKNOWN ...] placeholder tag."""
    stripped = re.sub(r"\[UNKNOWN[^\]]*\]", "", line, flags=re.IGNORECASE)
    return bool(OWNER_HINT_RE.search(stripped))


def _jaccard_overlap(a: str, b: str) -> float:
    ta, tb = _content_tokens(a), _content_tokens(b)
    if not ta or not tb:
        return 0.0
    union = ta | tb
    return round(len(ta & tb) / len(union), 3) if union else 0.0


def parse_document_ast(text: str) -> DocumentAST:
    """Parse a Markdown document into an ordered Section & Block AST."""
    lines = text.splitlines()
    total_lines = max(1, len(lines))
    sections: list[DocSection] = []

    current_level = 0
    current_heading = "_preamble"
    current_start = 0
    current_buf: list[str] = []

    def _flush(end_idx: int) -> None:
        body = "\n".join(current_buf).strip()
        if current_heading == "_preamble" and not body:
            return
        words = len(re.findall(r"\b[\w'-]+\b", body))
        cites = CITATION_RE.findall(body)
        hold_lines = [
            ln.strip()
            for ln in current_buf
            if not ln.lstrip().startswith("#") and HOLD_LINE_RE.search(ln)
        ]
        owned = sum(1 for ln in hold_lines if _hold_has_named_owner(ln))
        sections.append(
            DocSection(
                level=current_level,
                heading=current_heading,
                slug=_slugify(current_heading),
                start_line=current_start,
                end_line=end_idx,
                position_ratio=round(current_start / total_lines, 3),
                body=body,
                word_count=words,
                citations=cites,
                hold_lines=hold_lines,
                holds_with_owner=owned,
            )
        )

    for idx, line in enumerate(lines):
        m = re.match(r"^(#{1,4})\s+(.*)$", line.strip())
        if m:
            _flush(idx)
            current_level = len(m.group(1))
            current_heading = m.group(2).strip()
            current_start = idx
            current_buf = []
        else:
            current_buf.append(line)
    _flush(len(lines))

    # Extract Markdown pipe tables
    tables: list[list[list[str]]] = []
    cur_table: list[list[str]] = []
    for line in lines:
        s = line.strip()
        if s.startswith("|") and s.endswith("|") and s.count("|") >= 3:
            cells = [c.strip() for c in s.strip("|").split("|")]
            # Skip separator rows like | --- | --- |
            if all(re.fullmatch(r":?-{2,}:?", c.replace(" ", "")) for c in cells if c):
                continue
            cur_table.append(cells)
        else:
            if cur_table:
                tables.append(cur_table)
                cur_table = []
    if cur_table:
        tables.append(cur_table)

    # Extract contiguous A/V timecode beats
    beats: list[TimecodeBeat] = []
    for line in lines:
        tm = TIMECODE_ROW_RE.match(line.strip())
        if not tm:
            continue
        start_s = int(tm.group(1)) * 60 + int(tm.group(2))
        end_s = int(tm.group(3)) * 60 + int(tm.group(4))
        audio = tm.group(5).strip()
        video = tm.group(6).strip()
        dur_s = end_s - start_s
        audio_words = len(re.findall(r"\b[\w'-]+\b", audio))
        beat_wpm = round((audio_words / dur_s) * 60.0, 1) if dur_s > 0 else 999.0
        beats.append(
            TimecodeBeat(
                start_s=start_s,
                end_s=end_s,
                duration_s=dur_s,
                audio=audio,
                video=video,
                audio_words=audio_words,
                beat_wpm=beat_wpm,
                av_overlap=_jaccard_overlap(audio, video),
            )
        )

    all_cites = CITATION_RE.findall(text)
    hold_lines_all = [
        ln.strip()
        for ln in lines
        if not ln.lstrip().startswith("#") and HOLD_LINE_RE.search(ln)
    ]
    holds_owned_all = sum(1 for ln in hold_lines_all if _hold_has_named_owner(ln))
    slop_hits = sum(len(re.findall(p, text, flags=re.IGNORECASE)) for p in SLOP_PATTERNS)

    sentences = [s.strip() for s in re.split(r"[.!?]+", re.sub(r"\|.*?\|", " ", text)) if len(s.strip()) > 3]
    if sentences:
        avg_sent = round(sum(len(re.findall(r"\b[\w'-]+\b", s)) for s in sentences) / len(sentences), 2)
    else:
        avg_sent = 0.0

    return DocumentAST(
        total_lines=total_lines,
        total_words=len(re.findall(r"\b[\w'-]+\b", text)),
        sections=sections,
        tables=tables,
        timecode_beats=beats,
        citations=all_cites,
        hold_count=len(hold_lines_all),
        holds_with_owner=holds_owned_all,
        slop_hits=slop_hits,
        avg_sentence_words=avg_sent,
    )


def _find_first_position(text: str, pattern: str) -> float:
    """Return relative line position [0.0, 1.0] of the first match, or 1.0 if absent."""
    lines = text.splitlines()
    if not lines:
        return 1.0
    rx = re.compile(pattern, re.IGNORECASE)
    for idx, ln in enumerate(lines):
        if rx.search(ln):
            return round(idx / max(1, len(lines)), 3)
    return 1.0


def evaluate_document_flow(
    text: str,
    form_id: str,
    *,
    target_duration_s: int | None = None,
    strict_cpl_mandates: bool = True,
) -> FlowEvaluation:
    """Evaluate per-form information-flow invariants and emit discrete lever recommendations."""
    ast = parse_document_ast(text)
    lower = text.lower()
    violations: list[str] = []
    levers: list[str] = []
    checks_passed = 0
    checks_total = 0

    def _check(ok: bool, violation: str, lever: str) -> None:
        nonlocal checks_passed, checks_total
        checks_total += 1
        if ok:
            checks_passed += 1
        else:
            violations.append(violation)
            if lever and lever not in levers:
                levers.append(lever)

    # Global custody & craft invariants
    has_mandate_trap = has_mandate_lens_trap(text)
    if strict_cpl_mandates:
        _check(
            not has_mandate_trap,
            "cpl_mandate_lens_confusion: internal lens labeled as official 2027-2030 mandate",
            "mandate_boundary_guard",
        )
    has_unauth_release = bool(UNAUTHORIZED_RELEASE_RE.search(text))
    _check(
        not has_unauth_release,
        "unauthorized_release_claim: overclaims G06 release or Asana mutation",
        "authority_hold_guard",
    )
    _check(
        ast.slop_hits == 0,
        f"print_slop_detected: {ast.slop_hits} banned cliché(s)",
        "slop_stripper_pass",
    )

    hold_owner_ratio = (
        round(ast.holds_with_owner / ast.hold_count, 3) if ast.hold_count > 0 else 1.0
    )
    features: dict[str, Any] = {
        "total_words": ast.total_words,
        "section_count": len(ast.sections),
        "table_count": len(ast.tables),
        "citation_count": len(ast.citations),
        "hold_count": ast.hold_count,
        "hold_owner_ratio": hold_owner_ratio,
        "slop_hits": ast.slop_hits,
        "avg_sentence_words": ast.avg_sentence_words,
    }

    if form_id in ("production_brief", "leadership_report"):
        dec_pos = _find_first_position(text, r"\b(decision|recommend|approval|approve|ask|goal)\b")
        max_pos = 0.25 if form_id == "leadership_report" else 0.35
        features["decision_position_ratio"] = dec_pos
        _check(
            dec_pos <= max_pos,
            f"buried_decision: first decision cue at {dec_pos:.0%} of doc (limit <= {max_pos:.0%})",
            "section_order_lock:decision_first",
        )
        _check(
            len(ast.citations) >= 1,
            "missing_grounding_citation: no local source/ID cited",
            "citation_grounding_mode:strict",
        )
        _check(
            ast.hold_count >= 1 and hold_owner_ratio >= 0.75,
            f"unowned_holds: holds={ast.hold_count}, owner_coverage={hold_owner_ratio:.0%}",
            "hold_owner_policy:require_named_owner",
        )

    elif form_id == "av_script":
        beats = ast.timecode_beats
        features["beat_count"] = len(beats)
        _check(
            len(beats) >= 2,
            f"insufficient_timecode_beats: found {len(beats)} beat rows (need >= 2)",
            "av_table_scaffold:contiguous_beats",
        )
        contiguous = True
        prev_end = -1
        for b in beats:
            if b.duration_s <= 0 or (prev_end >= 0 and b.start_s < prev_end):
                contiguous = False
                break
            prev_end = b.end_s
        total_dur_s = beats[-1].end_s - beats[0].start_s if beats else 0
        max_wpm = max((b.beat_wpm for b in beats), default=0.0)
        avg_wpm = (
            round((sum(b.audio_words for b in beats) / total_dur_s) * 60.0, 1)
            if total_dur_s > 0
            else 0.0
        )
        avg_overlap = (
            round(sum(b.av_overlap for b in beats) / len(beats), 3) if beats else 0.0
        )
        max_beat_dur = max((b.duration_s for b in beats), default=0)

        features.update(
            {
                "timecode_contiguous": contiguous,
                "total_duration_s": total_dur_s,
                "max_beat_wpm": max_wpm,
                "avg_wpm": avg_wpm,
                "avg_av_overlap": avg_overlap,
                "max_beat_duration_s": max_beat_dur,
            }
        )
        _check(
            contiguous and len(beats) >= 2,
            "timecode_inversion_or_zero_duration: non-contiguous beat timestamps",
            "timecode_math_validator",
        )
        _check(
            avg_wpm <= 155.0 and max_wpm <= 175.0,
            f"wpm_overload: avg={avg_wpm} WPM, max_beat={max_wpm} WPM (limit <=155 avg / <=175 beat)",
            "wpm_budget_per_beat:150",
        )
        _check(
            avg_overlap <= 0.45,
            f"av_counterpoint_collapse: audio/video lexical overlap={avg_overlap:.2f} (limit <=0.45)",
            "av_counterpoint_cap:0.35",
        )
        if target_duration_s is not None and target_duration_s > 0:
            lo = target_duration_s * 0.80
            hi = target_duration_s * 1.20
            features["target_duration_s"] = target_duration_s
            _check(
                lo <= total_dur_s <= hi,
                f"duration_mismatch: script runs {total_dur_s}s vs target {target_duration_s}s",
                f"runtime_budget_lock:{target_duration_s}s",
            )
            if target_duration_s >= 120:
                _check(
                    max_beat_dur <= 90,
                    f"retention_reset_gap: longest beat is {max_beat_dur}s (limit <=90s for long-form)",
                    "chapter_retention_reset:60-90s",
                )

    elif form_id == "research_note":
        sig_pos = _find_first_position(text, r"\b(observed|signal|evidence|finding)\b")
        hyp_pos = _find_first_position(text, r"\b(hypothesis|bet|proposal|propose)\b")
        features["signal_position_ratio"] = sig_pos
        features["hypothesis_position_ratio"] = hyp_pos
        _check(
            sig_pos < hyp_pos and sig_pos < 0.60,
            f"evidence_order_inverted: signal@{sig_pos:.0%} vs hypothesis@{hyp_pos:.0%}",
            "section_order_lock:signal_before_hypothesis",
        )
        _check(
            len(ast.citations) >= 1,
            "missing_grounding_citation: research note lacks local source citation",
            "citation_grounding_mode:strict",
        )
        has_limits = bool(re.search(r"\b(limit|transfer|does not transfer|caveat|boundary)\b", lower))
        has_test = bool(re.search(r"\b(next test|experiment|falsif|measure|baseline)\b", lower))
        _check(
            has_limits and has_test,
            f"missing_research_rigor: transfer_limits={has_limits}, next_test={has_test}",
            "research_falsifiability_scaffold",
        )

    elif form_id == "treatment":
        prem_pos = _find_first_position(text, r"\b(premise|concept|hook|logline|pitch)\b")
        features["premise_position_ratio"] = prem_pos
        _check(
            prem_pos <= 0.35,
            f"buried_premise: premise/concept appears at {prem_pos:.0%} (limit <=35%)",
            "section_order_lock:premise_first",
        )
        has_visual = bool(re.search(r"\b(visual|camera|sound|tone|aesthetic|approach|act|arc)\b", lower))
        _check(
            has_visual,
            "missing_visual_narrative_plan: treatment lacks visual/arc cues",
            "treatment_visual_arc_scaffold",
        )
        _check(
            ast.hold_count >= 1,
            "missing_availability_separation: no pending location/clearance holds marked",
            "availability_vs_intent_split",
        )

    elif form_id == "call_sheet":
        data_rows = sum(max(0, len(t) - 1) for t in ast.tables)
        features["table_data_rows"] = data_rows
        _check(
            data_rows >= 2,
            f"missing_call_sheet_table: found {data_rows} table rows (need >=2)",
            "operational_table_lock:call_sheet",
        )
        has_core = all(
            re.search(p, lower)
            for p in (r"\b(call time|date|schedule)\b", r"\b(location|branch|address)\b", r"\b(crew|cast|host|role)\b")
        )
        _check(
            has_core,
            "missing_call_sheet_core_fields: requires call time/date, location, and crew/cast",
            "call_sheet_field_completeness",
        )

    elif form_id == "shot_list":
        data_rows = sum(max(0, len(t) - 1) for t in ast.tables)
        features["table_data_rows"] = data_rows
        _check(
            data_rows >= 3,
            f"missing_shot_table: found {data_rows} shot rows (need >=3)",
            "operational_table_lock:shot_list",
        )
        has_framing = bool(re.search(r"\b(ws|ms|cu|ecu|mcu|ots|b-roll|wide|medium|close-up)\b", lower))
        _check(
            has_framing,
            "missing_shot_framing_codes: no standard framing/size cues found",
            "shot_framing_standard",
        )

    elif form_id == "content_calendar":
        data_rows = sum(max(0, len(t) - 1) for t in ast.tables)
        features["table_data_rows"] = data_rows
        _check(
            data_rows >= 3,
            f"missing_calendar_table: found {data_rows} schedule rows (need >=3)",
            "operational_table_lock:content_calendar",
        )
        has_cadence = all(
            re.search(p, lower)
            for p in (r"\b(date|week|day)\b", r"\b(channel|youtube|instagram|platform)\b", r"\b(owner|status|hold)\b")
        )
        _check(
            has_cadence,
            "missing_calendar_core_fields: requires date/week, channel/platform, and owner/status",
            "calendar_cadence_fields",
        )

    flow_score = round(checks_passed / checks_total, 3) if checks_total else 1.0
    return FlowEvaluation(
        form_id=form_id,
        flow_score=flow_score,
        passed=(len(violations) == 0),
        violations=violations,
        section_flow=[f"H{s.level}:{s.heading}" for s in ast.sections if s.level > 0],
        features=features,
        recommended_levers=levers,
    )


# ---------------------------------------------------------------------------
# Portable Organization Strategic Charter (Strategic Plan, Mission, Vision, Service Promises)
# ---------------------------------------------------------------------------

OFFICIAL_MANDATE_RE = re.compile(
    r"\b(Collections|Experiences|Expertise|Spaces|Technology)\b"
)
VISION_2040_MISUSE_RE = re.compile(
    r"(?:\b(three in four|3 in 4)\b[^.\n]{0,60}\b(kpi|metric|target|video goal)\b|\b(kpi|metric|target|video goal)\b[^.\n]{0,60}\b(three in four|3 in 4)\b)",
    re.IGNORECASE,
)
STALE_PRIOR_PLAN_RE = re.compile(
    r"\b(current|active|2027[-–]2030)\s+(?:strategic\s+)?plan\b[^.\n]{0,80}\b(Everyone Belongs at the Library|2023[-–]2026|Create Purpose Together|Energize Lifelong Learning)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class OrganizationCharter:
    """Portable strategic-plan, mission, vision, values, commitments, and service-promise config."""

    org_name: str = "Calgary Public Library"
    strategic_plan_name: str = "A Better Tomorrow Through Stories (2027-2030)"
    mission: str = "Connect people to stories, knowledge, spaces, and tools for a better tomorrow."
    vision_north_star: str = "Three in four Calgarians choose the Library (Vision 2040 — institutional north star, not single-asset KPI)."
    official_mandates: tuple[str, ...] = ("Collections", "Experiences", "Expertise", "Spaces", "Technology")
    values: tuple[str, ...] = ("Curiosity", "Collaboration", "Equity and Belonging")
    commitments: tuple[str, ...] = ("Intellectual Freedom", "Truth and Reconciliation", "Intentional Innovation")
    service_promises: tuple[str, ...] = (
        "free",
        "library card",
        "patron",
        "accessible",
        "belonging",
        "curiosity",
        "innovation",
        "reconciliation",
        "intellectual freedom",
        "collaboration",
    )
    non_mandate_internal_lenses: tuple[str, ...] = ("Grow", "Books & Reading", "Community")


DEFAULT_CPL_CHARTER = OrganizationCharter()


def load_organization_charter(
    repo_root: Path | None = None,
    charter_path: Path | None = None,
) -> OrganizationCharter:
    """Load an OrganizationCharter from YAML if present; otherwise return the canonical CPL 2027-2030 charter."""
    path = charter_path
    if path is None and repo_root is not None:
        candidate = Path(repo_root) / ".agents" / "bench" / "org_charter.yaml"
        if candidate.is_file():
            path = candidate
    if path is None or not path.is_file():
        return DEFAULT_CPL_CHARTER
    try:
        import yaml  # type: ignore

        raw = yaml.safe_load(path.read_text(encoding="utf-8", errors="replace")) or {}
        if not isinstance(raw, dict):
            return DEFAULT_CPL_CHARTER
        return OrganizationCharter(
            org_name=str(raw.get("org_name") or DEFAULT_CPL_CHARTER.org_name),
            strategic_plan_name=str(raw.get("strategic_plan_name") or DEFAULT_CPL_CHARTER.strategic_plan_name),
            mission=str(raw.get("mission") or DEFAULT_CPL_CHARTER.mission),
            vision_north_star=str(raw.get("vision_north_star") or DEFAULT_CPL_CHARTER.vision_north_star),
            official_mandates=tuple(raw.get("official_mandates") or DEFAULT_CPL_CHARTER.official_mandates),
            values=tuple(raw.get("values") or DEFAULT_CPL_CHARTER.values),
            commitments=tuple(raw.get("commitments") or DEFAULT_CPL_CHARTER.commitments),
            service_promises=tuple(raw.get("service_promises") or DEFAULT_CPL_CHARTER.service_promises),
            non_mandate_internal_lenses=tuple(
                raw.get("non_mandate_internal_lenses") or DEFAULT_CPL_CHARTER.non_mandate_internal_lenses
            ),
        )
    except Exception:
        return DEFAULT_CPL_CHARTER


def _check_charter_alignment(text: str, charter: OrganizationCharter) -> dict[str, Any]:
    lower = text.lower()
    matched_mandates = [m for m in charter.official_mandates if re.search(rf"\b{re.escape(m)}\b", text)]
    matched_values = [v for v in charter.values if v.lower() in lower]
    matched_commitments = [c for c in charter.commitments if c.lower() in lower]
    matched_promises = [p for p in charter.service_promises if p.lower() in lower]
    stale_prior_plan = bool(STALE_PRIOR_PLAN_RE.search(text))
    vision_kpi_misuse = bool(VISION_2040_MISUSE_RE.search(text))
    lens_as_mandate = has_mandate_lens_trap(text)
    return {
        "org_name": charter.org_name,
        "strategic_plan": charter.strategic_plan_name,
        "matched_mandates": matched_mandates,
        "matched_values": matched_values,
        "matched_commitments": matched_commitments,
        "matched_service_promises": matched_promises,
        "stale_prior_plan_trap": stale_prior_plan,
        "vision_kpi_misuse": vision_kpi_misuse,
        "lens_as_mandate_trap": lens_as_mandate,
        "service_promise_grounded": bool(matched_promises or matched_values or matched_commitments),
    }


# ---------------------------------------------------------------------------
# 6-Role Organizational & Executive Buy-In Board (100% Offline Deterministic)
# ---------------------------------------------------------------------------


@dataclass
class RoleReview:
    role_id: str
    role_title: str
    relevance: str  # "approver" | "advisory"
    verdict: str    # "APPROVE" | "REVISE" | "HOLD"
    score: float
    passed_criteria: list[str]
    blockers: list[str]
    levers: list[str]


@dataclass
class BoardBuyInReport:
    form_id: str
    board_score: float
    buy_in_ready: bool
    blocking_roles: list[str]
    role_reviews: list[RoleReview]
    recommended_levers: list[str]
    charter_alignment: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


STAKEHOLDER_APPROVER_FORMS: dict[str, tuple[str, ...]] = {
    "media_production_manager": ("av_script", "call_sheet", "shot_list", "production_brief", "treatment"),
    "marketing_manager": ("content_calendar", "production_brief", "research_note", "av_script"),
    "communications_strategist": ("research_note", "production_brief", "leadership_report", "treatment", "av_script"),
    "marketing_and_engagement_director": ("production_brief", "leadership_report", "content_calendar", "research_note"),
    "communications_director": ("leadership_report", "production_brief", "research_note", "av_script", "content_calendar"),
    "ceo": ("leadership_report", "production_brief"),
}


def evaluate_stakeholder_board(
    text: str,
    form_id: str,
    *,
    flow_eval: FlowEvaluation | None = None,
    target_duration_s: int | None = None,
    strict_cpl_mandates: bool = True,
    charter: OrganizationCharter | None = None,
    repo_root: Path | None = None,
) -> BoardBuyInReport:
    """Evaluate a document through the 6 organizational & executive buy-in lenses and strategic charter."""
    active_charter = charter or load_organization_charter(repo_root=repo_root)
    fe = flow_eval or evaluate_document_flow(
        text,
        form_id,
        target_duration_s=target_duration_s,
        strict_cpl_mandates=strict_cpl_mandates,
    )
    charter_align = _check_charter_alignment(text, active_charter)
    lower = text.lower()
    feats = fe.features
    has_mandate_trap = charter_align["lens_as_mandate_trap"]
    has_unauth = bool(UNAUTHORIZED_RELEASE_RE.search(text))
    has_official_mandate = bool(charter_align["matched_mandates"])
    has_vision_misuse = charter_align["vision_kpi_misuse"]
    has_stale_plan = charter_align["stale_prior_plan_trap"]
    has_service_promise = charter_align["service_promise_grounded"]
    has_patron_action = bool(
        re.search(
            r"\b(patrons?|book|reserve|card|visit|click|action|next step|slot|session|calgarylibrary\.ca|reading list|bring|grab)\b",
            lower,
        )
    )
    has_channel_or_audience = bool(
        re.search(
            r"\b(youtube|instagram|reels|channel|patrons?|calgarians|audience|host|viewer|family|branch|kids|reader|builder|riders?|customers?|citizens?|users?|members?)\b",
            lower,
        )
    )
    has_production_specs = bool(
        re.search(
            r"\b(16:9|mp4|srt|caption|wpm|call time|location|camera|framing|ws|ms|cu|ecu|mcu|ots|audio|video|act 1|deliverable|runtime|duration)\b",
            lower,
        )
    )
    has_resource_or_scope = bool(
        re.search(
            r"\b(scope|budget|resource|slot|hours|phase|pilot|owner|capacity|tradeoff|baseline|deliverable|week|schedule)\b",
            lower,
        )
    )
    has_decision_top = feats.get("decision_position_ratio", _find_first_position(text, r"\b(decision|recommend|approve|premise|cold open|shot|week|date)\b")) <= 0.35

    def _run_role(
        role_id: str,
        title: str,
        checks: list[tuple[str, bool, bool, str]],  # (label, ok, is_hard_hold, lever)
    ) -> RoleReview:
        relevance = "approver" if form_id in STAKEHOLDER_APPROVER_FORMS.get(role_id, ()) else "advisory"
        passed_c: list[str] = []
        blockers: list[str] = []
        r_levers: list[str] = []
        hard_hold = False
        for label, ok, is_hold, lever in checks:
            if ok:
                passed_c.append(label)
            else:
                blockers.append(label)
                if is_hold:
                    hard_hold = True
                if lever and lever not in r_levers:
                    r_levers.append(lever)
        score = round(len(passed_c) / max(1, len(checks)), 3)
        if hard_hold:
            verdict = "HOLD"
        elif blockers:
            verdict = "REVISE"
        else:
            verdict = "APPROVE"
        return RoleReview(
            role_id=role_id,
            role_title=title,
            relevance=relevance,
            verdict=verdict,
            score=score,
            passed_criteria=passed_c,
            blockers=blockers,
            levers=r_levers,
        )

    reviews: list[RoleReview] = []

    # 1. Media Production Manager (shootability, timing, specs, technical QC, clearance holds)
    prod_timing_ok = (
        feats.get("timecode_contiguous", True)
        and feats.get("avg_wpm", 0.0) <= 155.0
        and feats.get("max_beat_wpm", 0.0) <= 175.0
        and feats.get("avg_av_overlap", 0.0) <= 0.45
        and not any(v.startswith("duration_mismatch") or v.startswith("retention_reset_gap") for v in fe.violations)
    )
    prod_table_ok = (
        feats.get("table_data_rows", 2) >= 2
        if form_id in ("call_sheet", "shot_list")
        else True
    )
    reviews.append(
        _run_role(
            "media_production_manager",
            "Media Production Manager",
            [
                ("shootable_specs_present", has_production_specs, True, "production_spec_scaffold"),
                ("timing_and_counterpoint_feasible", prod_timing_ok, True, "wpm_budget_per_beat:150"),
                ("operational_table_complete", prod_table_ok, True, "operational_table_lock"),
                ("clearances_and_holds_explicit", feats.get("hold_owner_ratio", 1.0) >= 0.75, False, "hold_owner_policy:require_named_owner"),
            ],
        )
    )

    # 2. Marketing Manager (audience clarity, patron action/CTA, channel fit, calendar discipline)
    cal_ok = feats.get("table_data_rows", 3) >= 3 if form_id == "content_calendar" else True
    reviews.append(
        _run_role(
            "marketing_manager",
            "Marketing Manager",
            [
                ("audience_or_channel_named", has_channel_or_audience, True, "audience_channel_spec"),
                ("immediate_patron_action_clear", has_patron_action or form_id in ("call_sheet", "shot_list", "treatment"), False, "patron_action_cta"),
                ("no_vision_2040_kpi_misuse", not has_vision_misuse, True, "vision_2040_kpi_guard"),
                ("schedule_and_owner_structured", cal_ok, True, "operational_table_lock:content_calendar"),
            ],
        )
    )

    # 3. Communications Strategist (evidence-before-hypothesis, citations, zero slop, transfer limits)
    order_ok = not any(v.startswith("evidence_order_inverted") for v in fe.violations)
    cite_ok = (feats.get("citation_count", 0) >= 1) if form_id in ("research_note", "production_brief", "leadership_report") else True
    rigor_ok = not any(v.startswith("missing_research_rigor") for v in fe.violations)
    reviews.append(
        _run_role(
            "communications_strategist",
            "Communications Strategist",
            [
                ("evidence_precedes_hypothesis", order_ok, True, "section_order_lock:signal_before_hypothesis"),
                ("source_citations_grounded", cite_ok, True, "citation_grounding_mode:strict"),
                ("zero_print_slop", feats.get("slop_hits", 0) == 0, False, "slop_stripper_pass"),
                ("transfer_limits_and_test_framed", rigor_ok, False, "research_falsifiability_scaffold"),
            ],
        )
    )

    # 4. Marketing and Engagement Director (portfolio/resource tradeoffs, owned holds, discoverability/retention)
    owned_holds_ok = (feats.get("hold_owner_ratio", 1.0) >= 0.75) and (
        feats.get("hold_count", 0) >= 1 if form_id in ("production_brief", "leadership_report") else True
    )
    reviews.append(
        _run_role(
            "marketing_and_engagement_director",
            "Marketing and Engagement Director",
            [
                ("scope_and_resource_bounded", has_resource_or_scope, False, "resource_tradeoff_frame"),
                ("holds_assigned_to_owners", owned_holds_ok, True, "hold_owner_policy:require_named_owner"),
                ("channel_audience_alignment", has_channel_or_audience, False, "audience_channel_spec"),
                ("flow_invariants_clean", fe.passed, False, "section_order_lock"),
            ],
        )
    )

    # 5. Communications Director (mandate vs lens hygiene, 2027-2030 plan currency, G06/Asana authority boundary)
    reviews.append(
        _run_role(
            "communications_director",
            "Communications Director",
            [
                ("official_mandate_hygiene", not (strict_cpl_mandates and has_mandate_trap), True, "mandate_boundary_guard"),
                ("current_strategic_plan_only", not has_stale_plan, True, "strategic_plan_currency_guard"),
                ("no_unauthorized_release_or_asana_claim", not has_unauth, True, "authority_hold_guard"),
                ("zero_corporate_slop", feats.get("slop_hits", 0) == 0, False, "slop_stripper_pass"),
                ("risk_and_permission_holds_owned", feats.get("hold_owner_ratio", 1.0) >= 0.75, False, "hold_owner_policy:require_named_owner"),
            ],
        )
    )

    # 6. CEO (decision-first brevity, 2027-2030 strategic mandate & service-promise alignment, zero vision-2040 overclaim)
    ceo_mandate_ok = (
        (has_official_mandate and not has_mandate_trap and not has_stale_plan)
        if form_id in ("leadership_report", "production_brief")
        else (not has_mandate_trap and not has_stale_plan)
    )
    ceo_promise_ok = has_service_promise or form_id in ("call_sheet", "shot_list", "treatment")
    reviews.append(
        _run_role(
            "ceo",
            "CEO",
            [
                ("decision_up_front", has_decision_top, True, "section_order_lock:decision_first"),
                ("strategic_plan_2027_2030_aligned", ceo_mandate_ok, True, "mandate_boundary_guard"),
                ("mission_and_service_promises_reflected", ceo_promise_ok, False, "service_promise_alignment"),
                ("no_unauthorized_commitments_or_vision_kpi_misuse", not has_unauth and not has_vision_misuse, True, "authority_hold_guard"),
                ("accountable_owners_named", feats.get("hold_owner_ratio", 1.0) >= 0.75, False, "hold_owner_policy:require_named_owner"),
            ],
        )
    )

    approver_reviews = [r for r in reviews if r.relevance == "approver"]
    blocking_roles = [r.role_id for r in approver_reviews if r.verdict in ("HOLD", "REVISE")]
    board_score = round(sum(r.score for r in reviews) / len(reviews), 3) if reviews else 1.0
    all_levers: list[str] = []
    for r in approver_reviews:
        for lv in r.levers:
            if lv not in all_levers:
                all_levers.append(lv)

    return BoardBuyInReport(
        form_id=form_id,
        board_score=board_score,
        buy_in_ready=(len(blocking_roles) == 0),
        blocking_roles=blocking_roles,
        role_reviews=reviews,
        recommended_levers=all_levers,
        charter_alignment=charter_align,
    )


# ---------------------------------------------------------------------------
# Offline Golden Corpus (all 8 forms + 30s/1m/3m/5m A/V scripts) & Mutation Fuzzer
# ---------------------------------------------------------------------------

GOLDEN_SPECIMENS: dict[str, dict[str, Any]] = {
    "production_brief": {
        "form_id": "production_brief",
        "text": (
            "# Episode 1 Production Brief — You Can Do That Here?\n\n"
            "## Decision Request\n"
            "Approve Episode 1 YouTube pre-flight scope for PITCH-YCD (free VHS digitization for Calgary patrons) under official 2027-2030 Experiences and Technology mandates.\n\n"
            "## Context & Grounding\n"
            "Grounded in `Calgary Public Library/GROUND_TRUTH.md` and the 213-video audit (`MW-01`).\n\n"
            "## Deliverables\n"
            "| Asset | Runtime | Format | Owner |\n"
            "| --- | --- | --- | --- |\n"
            "| Master Episode | 00:30 | 16:9 MP4 | Producer |\n"
            "| Captions | 00:30 | SRT | Editor |\n\n"
            "## Open Holds\n"
            "- [UNKNOWN — OWNER TO CONFIRM] Branch booking window — Owner: Programme Owner\n"
            "- [UNKNOWN — OWNER TO CONFIRM] Talent release signed — Owner: Producer\n"
        ),
    },
    "leadership_report": {
        "form_id": "leadership_report",
        "text": (
            "# CPL Video Pilot Executive Summary\n\n"
            "## Decision & Recommendation\n"
            "Recommend approving Phase 1 YouTube pilot capture for PITCH-YCD aligned with official 2027-2030 Experiences and Technology mandates to drive immediate patron action for free library services.\n\n"
            "## Evidence & Baseline\n"
            "Per `Calgary Public Library/GROUND_TRUTH.md`, current pilot metrics establish our baseline before release.\n\n"
            "## Open Risks & Holds\n"
            "- [UNKNOWN — OWNER TO CONFIRM] Final caption sign-off — Owner: Communications Manager\n"
        ),
    },
    "av_script_30s": {
        "form_id": "av_script",
        "target_duration_s": 30,
        "text": (
            "# A/V Script — Free VHS Digitization (30s)\n\n"
            "Aligned with official 2027-2030 Experiences and Technology mandates (`MW-04`).\n\n"
            "| Timecode | Audio | Video |\n"
            "| --- | --- | --- |\n"
            "| 00:00-00:10 | Got old family tapes gathering dust in a closet? | ECU dusty cardboard box opening; gloved hands lift a labeled 1994 VHS cassette. |\n"
            "| 00:10-00:22 | Your library card unlocks our transfer station for free. | MS Central Library studio desk; patron slides tape into converter deck; monitor waveform rises. |\n"
            "| 00:22-00:30 | Book a slot today and save those memories. | CU USB drive blinking green; lower-third URL graphic appears over smiling patron. |\n\n"
            "## Timing & Holds\n"
            "- Estimated cadence: ~110 WPM; captions checked.\n"
            "- [UNKNOWN — OWNER TO CONFIRM] Patron release form — Owner: Producer\n"
        ),
    },
    "av_script_1m": {
        "form_id": "av_script",
        "target_duration_s": 60,
        "text": (
            "# A/V Script — 1-Minute Central Library Studio Walkthrough\n\n"
            "Aligned with official 2027-2030 Spaces and Technology mandates (`MW-04`).\n\n"
            "| Timecode | Audio | Video |\n"
            "| --- | --- | --- |\n"
            "| 00:00-00:15 | Ever wanted studio sound without paying studio rent? | WS glass door swings open into acoustic booth; host taps condenser mic gently. |\n"
            "| 00:15-00:35 | Reserve two hours online with your card, check in at the desk, and plug in your laptop. | MCU kiosk QR scan; cut to librarian handing over keycard; insert XLR cable clicking into interface. |\n"
            "| 00:35-00:50 | Everything from podcasts to oral histories starts right here in the booth. | MS soundboard faders sliding up; peak meters glow emerald on dark console. |\n"
            "| 00:50-01:00 | Grab your card and reserve your first session at calgarylibrary.ca. | CU laptop export progress bar hits 100%; end-card QR graphic holds cleanly. |\n\n"
            "## Timing & Holds\n"
            "- [UNKNOWN — OWNER TO CONFIRM] Studio booking lead time — Owner: Service Owner\n"
        ),
    },
    "av_script_3m": {
        "form_id": "av_script",
        "target_duration_s": 180,
        "text": (
            "# A/V Script — 3-Minute Patron Story Mini-Doc\n\n"
            "Aligned with official 2027-2030 Experiences and Expertise mandates (`MW-04`).\n\n"
            "| Timecode | Audio | Video |\n"
            "| --- | --- | --- |\n"
            "| 00:00-00:30 | Act 1: For twenty years, Maria kept her grandfather's stories in a tin trunk. | ECU rusted latch clicks open; faded notebooks and cassette reels fill frame under warm lamp. |\n"
            "| 00:30-01:15 | She worried the magnetic tape would snap before her kids ever heard his voice. | MS kitchen table; Maria gently winds slack ribbon with a pencil; slow push-in on hands. |\n"
            "| 01:15-02:00 | Act 2: At Central Library, a specialist showed her how to calibrate the deck safely. | OTS digital media booth; staff member points to gain knob; oscilloscope trace stabilizes. |\n"
            "| 02:00-02:40 | Suddenly, a voice from 1978 filled the headphones, crisp and unmistakable. | CU Maria's eyes widen; silent reaction beat; waveform peaks dance across dark screen. |\n"
            "| 02:40-03:00 | Act 3: Now the whole family shares the archive online, preserved for free. | WS family gathered around tablet in sunlit living room; end card with booking link. |\n\n"
            "## Timing & Holds\n"
            "- [UNKNOWN — OWNER TO CONFIRM] Archival audio clearance — Owner: Producer\n"
        ),
    },
    "av_script_5m": {
        "form_id": "av_script",
        "target_duration_s": 300,
        "text": (
            "# A/V Script — 5-Minute Deep-Dive Episode (PITCH-YCD)\n\n"
            "Aligned with official 2027-2030 Collections, Spaces, and Technology mandates (`MW-04`).\n\n"
            "| Timecode | Audio | Video |\n"
            "| --- | --- | --- |\n"
            "| 00:00-00:30 | Cold Open: Most Calgarians walk past five thousand dollars of free gear every week. | Fast whip-pan across podcast booth, 3D printer bed, and VHS rack; bold kinetic chapter title. |\n"
            "| 00:30-01:30 | Chapter 1: First stop is the digitization bay where fragile home media gets rescued. | MS converter rack humming; close-up RCA cables; timer overlay counts real-time transfer. |\n"
            "| 01:30-02:30 | Chapter 2: Next door, soundproof suites turn kitchen-table ideas into broadcast audio. | Dolly shot past acoustic foam panels; host adjusts boom arm; compressor LED flashes amber. |\n"
            "| 02:30-03:30 | Chapter 3: Stuck on software? Drop-in specialists troubleshoot your project live. | OTS monitor showing timeline edit; librarian sketches workflow diagram on glass whiteboard. |\n"
            "| 03:30-04:30 | Chapter 4: Here is the three-step checklist so you walk in ready on day one. | Animated split-screen checklist graphic: card number, USB drive, booked confirmation email. |\n"
            "| 04:30-05:00 | Close: Pick one forgotten project this weekend and bring it through our doors. | WS Central Library atrium sunlight; patron waves at camera; clean subscribe and URL card. |\n\n"
            "## Timing & Holds\n"
            "- [UNKNOWN — OWNER TO CONFIRM] Branch filming permit — Owner: Director\n"
        ),
    },
    "research_note": {
        "form_id": "research_note",
        "text": (
            "# Research Note — PITCH-NQ Episode 2 Reader-Advisory Barriers\n\n"
            "## Observed Signal\n"
            "Per `Calgary Public Library/GROUND_TRUTH.md` and the 213-video audit (`2026-11-24`), patrons rarely discover specialist reader-advisory lists via long intros.\n\n"
            "## Hypothesis\n"
            "Opening with a 3-second patron question under official 2027-2030 Collections and Expertise mandates will raise click-through to curated reading lists.\n\n"
            "## Transfer Limits\n"
            "Findings from peer urban systems do not transfer blindly to smaller branch cohorts without baseline validation.\n\n"
            "## Next Test\n"
            "Run a two-variant thumbnail and hook experiment against our baseline CTR.\n"
        ),
    },
    "treatment": {
        "form_id": "treatment",
        "text": (
            "# Treatment — Deterministic Under Deadline\n\n"
            "## Premise & Concept\n"
            "A 3-minute short documentary following a local builder replacing fragile AI guesses with deterministic tools.\n\n"
            "## Visual Approach & Narrative Arc\n"
            "Act 1 opens on cramped late-night terminal screens; Act 2 contrasts tactile workbench sketches with clean green test passes; Act 3 lands on a calm morning handoff.\n\n"
            "## Availability & Open Holds\n"
            "- [UNKNOWN — OWNER TO CONFIRM] Workshop location release — Owner: Producer\n"
        ),
    },
    "call_sheet": {
        "form_id": "call_sheet",
        "text": (
            "# Call Sheet — PITCH-YCD Episode 1 Shoot\n\n"
            "Date: 2026-12-03 | Location: Central Library Digital Media Lab | Call Time: 08:30\n\n"
            "| Role | Name | Call Time | Notes |\n"
            "| --- | --- | --- | --- |\n"
            "| Director | [UNKNOWN — OWNER TO CONFIRM] | 08:30 | Owner: Producer |\n"
            "| Host | [UNKNOWN — OWNER TO CONFIRM] | 09:00 | Owner: Producer |\n"
            "| Camera Op | Assigned Crew | 08:30 | Bring lavalier kit |\n"
        ),
    },
    "shot_list": {
        "form_id": "shot_list",
        "text": (
            "# Shot List — PITCH-YCD Episode 1\n\n"
            "| Shot | Framing | Subject / Action | Duration |\n"
            "| --- | --- | --- | --- |\n"
            "| 01 | WS | Exterior Central Library entrance, morning light | 00:05 |\n"
            "| 02 | MS | Host enters digitization booth with VHS box | 00:08 |\n"
            "| 03 | CU | Cassette clicks into deck, monitor turns on | 00:06 |\n"
        ),
    },
    "content_calendar": {
        "form_id": "content_calendar",
        "text": (
            "# Pilot Content Calendar — Q1 Rollout\n\n"
            "Goal: Drive immediate patron action (book a free studio/VHS slot or curated reading list) across YouTube and Instagram.\n\n"
            "| Week | Channel | Deliverable | Owner | Status |\n"
            "| --- | --- | --- | --- | --- |\n"
            "| Week 1 | YouTube | PITCH-YCD Ep 1 Master | Producer | Hold: G06 pending |\n"
            "| Week 1 | Instagram | 15s Vertical Cutdown | Digital Marketing | Draft |\n"
            "| Week 2 | YouTube | PITCH-NQ Ep 1 Master | Series Producer | Pre-flight |\n"
        ),
    },
}


def _mut_bury_decision(text: str) -> str:
    lines = text.splitlines()
    filler = [f"Background operational paragraph {i} covering general branch history and archival notes." for i in range(18)]
    dec_lines = [ln for ln in lines if re.search(r"\b(decision|recommend|approval|approve)\b", ln, re.IGNORECASE)]
    rest = [ln for ln in lines if ln not in dec_lines]
    return "\n".join(rest[:2] + filler + rest[2:] + ["", "## Closing Note"] + dec_lines)


def _mut_strip_hold_owners(text: str) -> str:
    return re.sub(r"—\s*Owner:.*$", "", text, flags=re.MULTILINE)


def _mut_inject_lens_as_mandate(text: str) -> str:
    return text + "\n\nThis deliverable fulfills the official 2027-2030 mandates of Grow and Books & Reading.\n"


def _mut_invert_timecode(text: str) -> str:
    return re.sub(r"\|\s*00:10-00:22\s*\|", "| 00:25-00:12 |", text, count=1).replace("| 00:15-00:35 |", "| 00:40-00:20 |").replace("| 00:30-01:15 |", "| 01:20-00:40 |").replace("| 00:30-01:30 |", "| 01:40-00:50 |")


def _mut_bloat_beat_wpm(text: str) -> str:
    bloat = " ".join(["extraordinarily verbose spoken copy that exceeds breath limits"] * 12)
    return re.sub(
        r"^(\|\s*\d{2}:\d{2}-\d{2}:\d{2}\s*\|\s*)([^|]+)(\|)",
        lambda m: f"{m.group(1)}{m.group(2).strip()} {bloat} {m.group(3)}",
        text,
        count=1,
        flags=re.MULTILINE,
    )


def _mut_duplicate_audio_into_video(text: str) -> str:
    def _dup(m: re.Match[str]) -> str:
        return f"| {m.group(1)}:{m.group(2)}-{m.group(3)}:{m.group(4)} | {m.group(5)} | {m.group(5)} |"

    return "\n".join(TIMECODE_ROW_RE.sub(_dup, ln) for ln in text.splitlines())


def _mut_truncate_runtime_half(text: str) -> str:
    out: list[str] = []
    beat_seen = 0
    for ln in text.splitlines():
        if TIMECODE_ROW_RE.match(ln.strip()):
            beat_seen += 1
            if beat_seen > 2:
                continue
        out.append(ln)
    return "\n".join(out)


def _mut_hypothesis_before_signal(text: str) -> str:
    return (
        "# Research Note\n\n"
        "## Hypothesis\nWe propose a bold new thumbnail bet immediately.\n\n"
        "## Transfer Limits\nLimited to urban branches.\n\n"
        "## Next Test\nMeasure CTR baseline.\n\n"
        "## Observed Signal\nPer `Calgary Public Library/GROUND_TRUTH.md`, patrons skip long intros.\n"
    )


def _mut_strip_citations(text: str) -> str:
    return CITATION_RE.sub("local notes", text)


def _mut_drop_table_structure(text: str) -> str:
    return "\n".join(ln for ln in text.splitlines() if not ln.strip().startswith("|"))


def _mut_inject_unauthorized_release(text: str) -> str:
    return text + "\n\nStatus: approved for release and Asana updated.\n"


def _mut_inject_print_slop(text: str) -> str:
    return text + "\n\nIn today's fast-paced world, we delve into a transformative journey to unlock the power of synergy.\n"


def _mut_inject_stale_prior_plan(text: str) -> str:
    return text + "\n\nThis aligns with our current strategic plan, Everyone Belongs at the Library (2023-2026).\n"


def _mut_inject_vision_2040_kpi_misuse(text: str) -> str:
    return text + "\n\nOur single-video KPI target is three in four Calgarians choosing the Library.\n"


MUTATION_CATALOG: dict[str, tuple[tuple[str, ...], Callable[[str], str]]] = {
    "bury_decision_at_bottom": (("production_brief", "leadership_report"), _mut_bury_decision),
    "strip_hold_owners": (("production_brief", "leadership_report"), _mut_strip_hold_owners),
    "inject_lens_as_mandate": (("production_brief", "leadership_report", "av_script", "research_note"), _mut_inject_lens_as_mandate),
    "inject_stale_prior_plan": (("production_brief", "leadership_report", "research_note", "av_script"), _mut_inject_stale_prior_plan),
    "inject_vision_2040_kpi_misuse": (("production_brief", "leadership_report", "content_calendar", "av_script"), _mut_inject_vision_2040_kpi_misuse),
    "invert_timecode": (("av_script",), _mut_invert_timecode),
    "bloat_beat_wpm": (("av_script",), _mut_bloat_beat_wpm),
    "duplicate_audio_into_video": (("av_script",), _mut_duplicate_audio_into_video),
    "truncate_runtime_half": (("av_script",), _mut_truncate_runtime_half),
    "hypothesis_before_signal": (("research_note",), _mut_hypothesis_before_signal),
    "strip_citations": (("research_note", "production_brief", "leadership_report"), _mut_strip_citations),
    "drop_table_structure": (("call_sheet", "shot_list", "content_calendar"), _mut_drop_table_structure),
    "inject_unauthorized_release": (("production_brief", "leadership_report", "call_sheet", "content_calendar"), _mut_inject_unauthorized_release),
    "inject_print_slop": (("production_brief", "leadership_report", "av_script", "research_note", "treatment", "call_sheet", "shot_list", "content_calendar"), _mut_inject_print_slop),
}


def run_offline_fuzz_suite(
    *,
    rounds: int = 1,
    seed: int = 42,
) -> dict[str, Any]:
    """Run zero-LLM golden + mutation fuzz sweep across all 8 forms and A/V runtimes."""
    t0 = time.perf_counter()
    rng = random.Random(seed)
    golden_total = 0
    golden_passed = 0
    golden_failures: list[dict[str, Any]] = []

    mutants_total = 0
    mutants_killed = 0
    surviving_mutants: list[dict[str, Any]] = []
    kills_by_form: dict[str, dict[str, int]] = {}
    kills_by_mutation: dict[str, dict[str, int]] = {}
    role_blocks_by_role: dict[str, int] = {
        "media_production_manager": 0,
        "marketing_manager": 0,
        "communications_strategist": 0,
        "marketing_and_engagement_director": 0,
        "communications_director": 0,
        "ceo": 0,
    }
    golden_board_ready = 0

    specimen_items = list(GOLDEN_SPECIMENS.items())
    for _r in range(max(1, rounds)):
        if _r > 0:
            rng.shuffle(specimen_items)
        for spec_id, spec in specimen_items:
            form_id = spec["form_id"]
            target_dur = spec.get("target_duration_s")
            text = spec["text"]

            g_eval = evaluate_document_flow(text, form_id, target_duration_s=target_dur)
            g_board = evaluate_stakeholder_board(text, form_id, flow_eval=g_eval, target_duration_s=target_dur)
            golden_total += 1
            if g_board.buy_in_ready:
                golden_board_ready += 1
            if g_eval.passed and g_board.buy_in_ready:
                golden_passed += 1
            else:
                golden_failures.append(
                    {
                        "specimen": spec_id,
                        "form_id": form_id,
                        "violations": g_eval.violations,
                        "blocking_roles": g_board.blocking_roles,
                    }
                )

            for mut_name, (forms, mut_fn) in MUTATION_CATALOG.items():
                if form_id not in forms:
                    continue
                if mut_name == "truncate_runtime_half" and (target_dur is None or target_dur < 60):
                    continue
                mutated = mut_fn(text)
                if mutated == text:
                    continue
                m_eval = evaluate_document_flow(mutated, form_id, target_duration_s=target_dur)
                m_board = evaluate_stakeholder_board(mutated, form_id, flow_eval=m_eval, target_duration_s=target_dur)
                mutants_total += 1
                for br in m_board.blocking_roles:
                    role_blocks_by_role[br] = role_blocks_by_role.get(br, 0) + 1
                killed = (
                    (not m_eval.passed or not m_board.buy_in_ready)
                    and (
                        m_eval.flow_score < g_eval.flow_score
                        or len(m_eval.violations) > len(g_eval.violations)
                        or len(m_board.blocking_roles) > len(g_board.blocking_roles)
                    )
                )
                kills_by_form.setdefault(form_id, {"killed": 0, "total": 0})
                kills_by_form[form_id]["total"] += 1
                kills_by_mutation.setdefault(mut_name, {"killed": 0, "total": 0})
                kills_by_mutation[mut_name]["total"] += 1
                if killed:
                    mutants_killed += 1
                    kills_by_form[form_id]["killed"] += 1
                    kills_by_mutation[mut_name]["killed"] += 1
                else:
                    surviving_mutants.append(
                        {
                            "specimen": spec_id,
                            "form_id": form_id,
                            "mutation": mut_name,
                            "flow_score": m_eval.flow_score,
                            "violations": m_eval.violations,
                            "blocking_roles": m_board.blocking_roles,
                        }
                    )

    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
    total_evals = golden_total + mutants_total
    evals_per_sec = round(total_evals / max(elapsed_ms / 1000.0, 1e-6), 1)
    kill_rate = round(mutants_killed / mutants_total, 4) if mutants_total else 1.0
    ok = (golden_passed == golden_total) and (mutants_killed == mutants_total)

    return {
        "ok": ok,
        "rounds": max(1, rounds),
        "elapsed_ms": elapsed_ms,
        "total_evaluations": total_evals,
        "evals_per_sec": evals_per_sec,
        "golden_passed": golden_passed,
        "golden_board_ready": golden_board_ready,
        "golden_total": golden_total,
        "golden_failures": golden_failures[:10],
        "mutants_killed": mutants_killed,
        "mutants_total": mutants_total,
        "kill_rate": kill_rate,
        "surviving_mutants": surviving_mutants[:10],
        "kills_by_form": kills_by_form,
        "kills_by_mutation": kills_by_mutation,
        "role_blocks_by_role": role_blocks_by_role,
    }
