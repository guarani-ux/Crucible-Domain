"""Form-Specific Writing-Device Analyzers & Professional Benchmark Scorer."""

from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

LLM_CLICHE_PHRASES = (
    "in today's fast-paced",
    "in today's dynamic",
    "delve into",
    "tapestry of",
    "game-changer",
    "unlock the power",
    "seamless experience",
    "testament to",
    "let's dive in",
    "without further ado",
    "at the end of the day",
)

OFFICIAL_CPL_MANDATES_2027 = ("Collections", "Experiences", "Expertise", "Spaces", "Technology")
CPL_INTERNAL_LENSES = ("Grow", "Books & Reading", "Community")


MASTERY_ELEMENTS = ("style", "audience", "purpose", "formatting", "stakeholder_connection")


@dataclass(frozen=True)
class FormProfile:
    """Professional specification for one document domain across 5 mastery elements."""

    form_id: str
    display_name: str
    audience: str
    required_cues: tuple[str, ...]
    expected_devices: tuple[str, ...]
    craft_arms: tuple[str, ...]
    max_words_target: int
    style_spec: str = ""
    audience_spec: str = ""
    purpose_spec: str = ""
    formatting_spec: str = ""
    stakeholder_spec: str = ""


FORM_PROFILES: dict[str, FormProfile] = {
    "production_brief": FormProfile(
        form_id="production_brief",
        display_name="Production / Project Brief",
        audience="Commissioner, producer, and production leads",
        required_cues=("context", "goal", "audience", "deliverable", "hold"),
        expected_devices=("decision_first_opener", "explicit_owner_holds", "scoped_constraints"),
        craft_arms=("decision_first_scaffold", "evidence_hold_custody", "exemplar_parity_anchor"),
        max_words_target=650,
        style_spec="Decision-led, concise operational prose; zero promotional fluff.",
        audience_spec="Commissioner authorizing budget/crew + producer building the workback.",
        purpose_spec="Approve exact deliverable scope and route unresolved questions to named owners.",
        formatting_spec="Decision request in first 2 lines, numbered sections, deliverables specs table, Held Questions owner table.",
        stakeholder_spec="Separate verified facts from [UNKNOWN — OWNER TO CONFIRM] holds; assign an owner to every open gate.",
    ),
    "av_script": FormProfile(
        form_id="av_script",
        display_name="Audio-Video (A/V) Script",
        audience="Director, presenter/host, camera operator, and editor",
        required_cues=("audio", "video", "timing"),
        expected_devices=("timecode_beats", "spoken_ear_wpm", "av_counterpoint", "low_print_slop"),
        craft_arms=("spoken_ear_counterpoint", "exemplar_parity_anchor", "decision_first_scaffold"),
        max_words_target=550,
        style_spec="Spoken-ear active sentences at <=150 WPM; strip print-prose clichés; keep room for breathing & visual holds.",
        audience_spec="Host speaking aloud on camera + director/editor cutting picture to sound.",
        purpose_spec="Deliver a shootable timed beat sheet where picture and spoken words add distinct value.",
        formatting_spec="Contiguous `MM:SS-MM:SS | Audio | Video` pipe table + WPM timing estimate + caption/muted check.",
        stakeholder_spec="Flag voice/location clearances pending; avoid overclaiming sound/picture assets not yet captured.",
    ),
    "research_note": FormProfile(
        form_id="research_note",
        display_name="Research & Opportunity Document",
        audience="Strategist, producer, and service owners",
        required_cues=("signal", "evidence", "audience", "limit", "test"),
        expected_devices=("observation_vs_hypothesis", "explicit_source_citations", "transfer_limits"),
        craft_arms=("evidence_hold_custody", "decision_first_scaffold", "exemplar_parity_anchor"),
        max_words_target=500,
        style_spec="Qualified, investigative, non-hype precision; distinguish observation from inference.",
        audience_spec="Strategist/producer deciding whether an opportunity merits a pilot.",
        purpose_spec="Select one testable bet or decline with falsifiable evidence and transfer limits.",
        formatting_spec="Observed signal + date, audience barrier, evidence vs. hypothesis split, transfer limits, proposed test.",
        stakeholder_spec="Cite exact local files/dates; explicitly reserve programme/service eligibility to service owners.",
    ),
    "treatment": FormProfile(
        form_id="treatment",
        display_name="Concept Pitch / Treatment",
        audience="Sponsor, creative lead, and stakeholders",
        required_cues=("premise", "story", "visual", "asset"),
        expected_devices=("narrative_arc", "intended_vs_available_assets", "concrete_moments"),
        craft_arms=("exemplar_parity_anchor", "evidence_hold_custody", "decision_first_scaffold"),
        max_words_target=500,
        style_spec="Evocative yet concrete visual storytelling without vague buzzwords.",
        audience_spec="Sponsor approving creative direction + crew evaluating visual feasibility.",
        purpose_spec="Commit to a coherent story arc & look before spending production hours.",
        formatting_spec="Summary hook, open -> turn -> payoff arc, visual look/camera grammar, intended vs. available assets list.",
        stakeholder_spec="Never present proposed locations, talent, or unverified approvals as locked assets.",
    ),
    "call_sheet": FormProfile(
        form_id="call_sheet",
        display_name="Production Call Sheet",
        audience="Crew, talent, and site contacts on shoot day",
        required_cues=("window", "who", "sound", "coverage", "reset"),
        expected_devices=("time_window_table", "named_role_fallbacks", "safety_and_access_gates"),
        craft_arms=("crew_table_completeness", "evidence_hold_custody", "exemplar_parity_anchor"),
        max_words_target=700,
        style_spec="Terse, imperative, unambiguous shoot-day instructions.",
        audience_spec="Crew, presenter, and room contact scanning on mobile under time pressure.",
        purpose_spec="Run door-to-reset execution without missing cues, sound checks, or safety stops.",
        formatting_spec="HH:MM time-window table (`Window | Who & First Job | Gate & Fallback`) + sound/coverage setup checks.",
        stakeholder_spec="Name stop authority, read-back owners, and explicit `[UNKNOWN]` site/power/contact holds.",
    ),
    "shot_list": FormProfile(
        form_id="shot_list",
        display_name="Camera & Audio Shot List",
        audience="Camera operator, sound helper, and editor",
        required_cues=("setup", "priority", "minimum", "alternate"),
        expected_devices=("shot_id_table", "priority_tiers", "minimum_usable_take"),
        craft_arms=("crew_table_completeness", "exemplar_parity_anchor", "spoken_ear_counterpoint"),
        max_words_target=550,
        style_spec="Exact visual framing, orientation, and pass/fail capture criteria.",
        audience_spec="Camera operator/sound helper on floor and editor verifying coverage.",
        purpose_spec="Guarantee essential story beats are captured cleanly before spending time on optional detail.",
        formatting_spec="Structured table (`ID / Setup | Priority & Action | Minimum Usable Take | Use & Alternate`) with P01/H01/A01 IDs.",
        stakeholder_spec="Protect presenter window with explicit cutoffs and archive/pickup fallbacks.",
    ),
    "leadership_report": FormProfile(
        form_id="leadership_report",
        display_name="Executive Summary / Alignment Note",
        audience="Acting Director, senior managers, and Board reviewers",
        required_cues=("decision", "mandate", "evidence", "limit"),
        expected_devices=("inverted_pyramid_opener", "exact_mandate_custody", "bounded_remit"),
        craft_arms=("decision_first_scaffold", "evidence_hold_custody", "exemplar_parity_anchor"),
        max_words_target=350,
        style_spec="Executive brevity (<=260 words target), inverted-pyramid clarity, exact institutional terms.",
        audience_spec="Acting Director / senior leader deciding in <90 seconds within organizational remit.",
        purpose_spec="Surface one clear decision option, verified institutional mandate fit, and hard limits.",
        formatting_spec="Decision request at top, mandate & evidence block, explicit remit/limits and open holds at bottom.",
        stakeholder_spec="Use exact 2027-2030 mandate wording; keep internal editorial lenses distinct; never overclaim release/Asana.",
    ),
    "content_calendar": FormProfile(
        form_id="content_calendar",
        display_name="Content Calendar & Channel Plan",
        audience="Content Management, Digital Marketing, and Communications",
        required_cues=("youtube", "instagram", "newsletter", "milestone", "hold"),
        expected_devices=("channel_native_differentiation", "exposure_stage_separation", "cta_route_check"),
        craft_arms=("channel_native_split", "crew_table_completeness", "evidence_hold_custody"),
        max_words_target=750,
        style_spec="Platform-native hooks per channel; zero copy-paste duplication across surfaces.",
        audience_spec="Channel owners, social schedulers, and newsletter editors preparing staged rollout.",
        purpose_spec="Give every channel a distinct job while preventing premature external/public exposure.",
        formatting_spec="Per-channel copy blocks + Milestone Exposure Ledger (`Milestone | Receiver | Version/Dest | Gate | Receipt`).",
        stakeholder_spec="Enforce CH-04 separation (internal handoff vs. unlisted preview vs. public rollout) and verified CTA URLs.",
    ),
}

# Form-normalization aliases so YAML authors can use natural names
FORM_ALIASES: dict[str, str] = {
    "brief": "production_brief",
    "decision_brief": "production_brief",
    "campaign_brief": "content_calendar",
    "content_plan": "content_calendar",
    "distribution": "content_calendar",
    "exec_summary": "leadership_report",
    "executive_summary": "leadership_report",
    "alignment_note": "leadership_report",
    "concept_pitch": "treatment",
    "research_doc": "research_note",
    "research_document": "research_note",
}


def resolve_form_id(raw_form: str) -> str:
    key = raw_form.strip().lower().replace("-", "_").replace(" ", "_")
    return FORM_ALIASES.get(key, key)


@dataclass
class FormDiagnosticReport:
    """Decomposed quality and 5-element mastery score against professional standards."""

    form_id: str
    overall_score: float
    structure_score: float
    device_score: float
    receiver_actionability: float
    professional_parity: float
    weakest_aspect: str
    diagnosis: str
    measured_features: dict[str, Any]
    element_scores: dict[str, float] | None = None
    weakest_element: str = ""
    mastery_tip: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_escalation_challenge(form_id: str, weakest_element: str, difficulty_level: int) -> str:
    """Generate progressive scenario pressure when an element saturates at an easier difficulty tier."""
    if difficulty_level <= 1:
        return ""
    profile = FORM_PROFILES.get(form_id, FORM_PROFILES["production_brief"])
    if difficulty_level == 2:
        focus = {
            "style": f"Tighten style under 25% fewer words while preserving {profile.style_spec}",
            "audience": f"Serve two readers simultaneously without jargon: {profile.audience_spec}",
            "purpose": "Make the single required decision/action unmistakable in the first 3 lines.",
            "formatting": f"Ensure zero ambiguity in layout: {profile.formatting_spec}",
            "stakeholder_connection": f"Isolate at least 2 realistic missing facts/approvals with named owners: {profile.stakeholder_spec}",
        }.get(weakest_element, profile.stakeholder_spec)
        return f"[Training Level 2 — Constraint Tightening] Focus on '{weakest_element}': {focus}"

    # Level 3: multi-constraint & disruption stress test
    return (
        f"[Training Level 3 — Real-World Disruption Stress Test] Handle a mid-project constraint change "
        f"(e.g., 20% shorter runtime/window OR one unconfirmed branch/asset hold) while keeping '{weakest_element}' "
        f"({getattr(profile, {'style': 'style_spec', 'audience': 'audience_spec', 'purpose': 'purpose_spec', 'formatting': 'formatting_spec', 'stakeholder_connection': 'stakeholder_spec'}.get(weakest_element, 'purpose_spec'))}) "
        "immediately actionable for a cold colleague."
    )


def _count_words(text: str) -> int:
    return len(re.findall(r"\S+", text))


def _slop_penalty(text: str) -> tuple[float, list[str]]:
    lower = text.lower()
    hits = [p for p in LLM_CLICHE_PHRASES if p in lower]
    return min(0.6, 0.2 * len(hits)), hits


def _has_markdown_table(text: str) -> bool:
    lines = text.splitlines()
    return any("|" in ln and "---" in ln for ln in lines)


def _extract_timecode_beats(text: str) -> list[tuple[int, int, str, str]]:
    """Extract (start_sec, end_sec, audio_cell, video_cell) from timed A/V pipe rows."""
    beats: list[tuple[int, int, str, str]] = []
    tc_re = re.compile(r"(\d{1,2}):(\d{2})\s*[–-]\s*(\d{1,2}):(\d{2})")
    for line in text.splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        m = tc_re.search(cells[0])
        if not m:
            continue
        s1 = int(m.group(1)) * 60 + int(m.group(2))
        s2 = int(m.group(3)) * 60 + int(m.group(4))
        beats.append((s1, s2, cells[1], cells[2]))
    return beats


def _score_av_devices(text: str) -> tuple[float, dict[str, Any], list[str]]:
    beats = _extract_timecode_beats(text)
    notes: list[str] = []
    if not beats:
        return 0.15, {"beat_count": 0, "estimated_wpm": 0.0, "av_overlap": 1.0}, [
            "missing timed A/V table rows (expected `MM:SS-MM:SS | Audio | Video`)"
        ]

    valid_beats = sum(1 for s, e, _, _ in beats if 0 <= s < e)
    beat_validity = valid_beats / len(beats)
    if valid_beats < len(beats):
        notes.append(f"{len(beats) - valid_beats} beat(s) have inverted or zero-length timecodes")

    spoken_words = 0
    overlaps: list[float] = []
    total_sec = 0
    for s, e, audio, video in beats:
        total_sec += max(0, e - s)
        a_clean = re.sub(r"\*\*[^*]+\*\*", "", audio)
        a_toks = re.findall(r"[a-z0-9']+", a_clean.lower())
        v_toks = set(re.findall(r"[a-z0-9']+", video.lower()))
        spoken_words += len(a_toks)
        if a_toks and v_toks:
            stop = {"the", "a", "an", "to", "of", "and", "in", "on", "is", "it", "for", "with", "that", "this"}
            a_content = {t for t in a_toks if t not in stop and len(t) > 2}
            v_content = {t for t in v_toks if t not in stop and len(t) > 2}
            if a_content:
                overlaps.append(len(a_content & v_content) / len(a_content))

    wpm = (spoken_words / total_sec) * 60.0 if total_sec > 0 else 999.0
    if wpm <= 160.0:
        wpm_score = 1.0
    elif wpm <= 195.0:
        wpm_score = 0.65
        notes.append(f"spoken cadence {wpm:.0f} WPM is slightly dense (target <=155 WPM for pauses)")
    else:
        wpm_score = 0.25
        notes.append(f"spoken cadence {wpm:.0f} WPM exceeds readable broadcast pace (<=160 WPM)")

    avg_overlap = sum(overlaps) / len(overlaps) if overlaps else 0.0
    if avg_overlap <= 0.45:
        counterpoint_score = 1.0
    elif avg_overlap <= 0.65:
        counterpoint_score = 0.65
        notes.append(f"audio-visual lexical overlap {avg_overlap:.0%}: narration partially duplicates picture")
    else:
        counterpoint_score = 0.3
        notes.append(f"high audio-visual redundancy ({avg_overlap:.0%} overlap): show visually instead of narrating it")

    slop_pen, slop_hits = _slop_penalty(text)
    if slop_hits:
        notes.append(f"print-prose LLM slop detected in script: {slop_hits[:2]}")

    score = max(0.0, min(1.0, 0.35 * beat_validity + 0.35 * wpm_score + 0.30 * counterpoint_score - slop_pen))
    feats = {
        "beat_count": len(beats),
        "valid_beats": valid_beats,
        "total_sec": total_sec,
        "estimated_wpm": round(wpm, 1),
        "av_overlap": round(avg_overlap, 3),
    }
    return score, feats, notes


def _score_decision_first_devices(text: str, *, strict_mandates: bool = False) -> tuple[float, dict[str, Any], list[str]]:
    notes: list[str] = []
    non_empty = [ln.strip() for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#") and not ln.strip().startswith(">")]
    lead = " ".join(non_empty[:2]).lower()
    decision_verbs = ("approve", "decision", "confirm", "choose", "authorize", "recommend", "select", "hold", "target")
    decision_first = any(v in lead for v in decision_verbs)
    if not decision_first:
        notes.append("opener lacks explicit decision/recommendation verb (lead with the ask, not background)")

    has_owner_hold = bool(
        re.search(r"(\[UNKNOWN|TBD\s*[—-]|owner:|Owner|Held question|Open Holds)", text, re.IGNORECASE)
    )
    if not has_owner_hold:
        notes.append("missing explicit owner/hold separation (`[UNKNOWN — OWNER TO CONFIRM]` or `Owner:` gate)")

    mandate_ok = True
    if strict_mandates:
        has_official = any(m in text for m in OFFICIAL_CPL_MANDATES_2027)
        if not has_official:
            mandate_ok = False
            notes.append("missing explicit 2027-2030 official mandate reference")
        for lens in CPL_INTERNAL_LENSES:
            if re.search(rf"\bmandate[s]?\b[^\n.]{{0,50}}\b{re.escape(lens)}\b", text, re.IGNORECASE):
                if "distinct" not in text.lower() and "not a" not in text.lower():
                    mandate_ok = False
                    notes.append(f"internal editorial lens '{lens}' conflated with official 2027-2030 mandate")

    slop_pen, slop_hits = _slop_penalty(text)
    if slop_hits:
        notes.append(f"filler clichés reduce executive brevity: {slop_hits[:2]}")

    score = max(
        0.0,
        min(
            1.0,
            (0.35 if decision_first else 0.10)
            + (0.35 if has_owner_hold else 0.05)
            + (0.30 if mandate_ok else 0.0)
            - slop_pen,
        ),
    )
    return score, {"decision_first": decision_first, "has_owner_hold": has_owner_hold, "mandate_ok": mandate_ok}, notes


def _score_research_devices(text: str) -> tuple[float, dict[str, Any], list[str]]:
    notes: list[str] = []
    lower = text.lower()
    has_obs_vs_hyp = ("hypothesis" in lower or "propose" in lower or "alternative" in lower) and (
        "observed" in lower or "evidence" in lower or "verified" in lower or "audit" in lower
    )
    if not has_obs_vs_hyp:
        notes.append("separate observed facts/dates from proposed hypotheses and alternatives")

    has_citations = bool(re.search(r"([A-Za-z0-9_./-]+\.(?:md|py|json|yaml|csv)|20\d{2}-\d{2}|213\s+video)", text))
    if not has_citations:
        notes.append("missing grounded local file path, date stamp, or quantitative source citation")

    has_limits_and_test = ("limit" in lower or "transfer" in lower or "unknown" in lower or "hold" in lower) and (
        "test" in lower or "check" in lower or "next" in lower
    )
    if not has_limits_and_test:
        notes.append("missing explicit transfer limits or concrete next testable check")

    score = (0.35 if has_obs_vs_hyp else 0.1) + (0.35 if has_citations else 0.05) + (0.30 if has_limits_and_test else 0.1)
    return score, {"obs_vs_hyp": has_obs_vs_hyp, "has_citations": has_citations, "has_limits_and_test": has_limits_and_test}, notes


def _score_operational_table_devices(text: str, form_id: str) -> tuple[float, dict[str, Any], list[str]]:
    notes: list[str] = []
    has_table = _has_markdown_table(text)
    if not has_table:
        notes.append(f"{form_id} requires a structured Markdown table for fast crew scanning")

    lower = text.lower()
    if form_id == "call_sheet":
        has_windows = bool(re.search(r"\b\d{2}:\d{2}\b", text))
        has_fallback = any(k in lower for k in ("fallback", "if unavailable", "hold", "stop", "reset"))
        has_sound_cov = ("sound" in lower or "lav" in lower or "audio" in lower) and ("camera" in lower or "frame" in lower or "coverage" in lower)
        if not has_windows:
            notes.append("call sheet missing explicit HH:MM door/cue/reset windows")
        if not has_fallback:
            notes.append("call sheet missing fallback/stop/reset procedures")
        if not has_sound_cov:
            notes.append("call sheet missing sound-check and framing/coverage test gates")
        score = (0.30 if has_table else 0.05) + (0.25 if has_windows else 0.05) + (0.25 if has_fallback else 0.05) + (0.20 if has_sound_cov else 0.05)
        return score, {"has_table": has_table, "has_windows": has_windows, "has_fallback": has_fallback}, notes

    # shot_list
    has_shot_ids = len(re.findall(r"\b[PHAB]\d{2}\b|\bS\d{2}\b", text)) >= 2
    has_priority = any(k in lower for k in ("essential", "supporting", "priority"))
    has_min_take = any(k in lower for k in ("minimum", "usable", "focus", "hold", "slate"))
    if not has_shot_ids:
        notes.append("shot list missing stable shot IDs (e.g., P01, H01, A01)")
    if not has_priority:
        notes.append("shot list missing Essential vs. Supporting priority tiers")
    if not has_min_take:
        notes.append("shot list missing minimum usable take criteria")
    score = (0.30 if has_table else 0.05) + (0.25 if has_shot_ids else 0.05) + (0.25 if has_priority else 0.05) + (0.20 if has_min_take else 0.05)
    return score, {"has_table": has_table, "has_shot_ids": has_shot_ids, "has_priority": has_priority}, notes


def _score_content_calendar_devices(text: str) -> tuple[float, dict[str, Any], list[str]]:
    notes: list[str] = []
    lower = text.lower()
    channels = [c for c in ("youtube", "instagram", "newsletter", "reel", "short", "email") if c in lower]
    distinct_channels = len(set(channels)) >= 2
    if not distinct_channels:
        notes.append("content calendar must differentiate at least 2 native channels (e.g., YouTube vs. Instagram/Newsletter)")

    has_exposure_gates = any(k in lower for k in ("unlisted", "handoff", "public", "hold", "release"))
    if not has_exposure_gates:
        notes.append("missing CH-04 exposure stage separation (internal handoff vs. unlisted vs. public rollout)")

    has_cta_or_date = any(k in lower for k in ("cta", "url", "link", "monday", "tuesday", "friday", "day "))
    if not has_cta_or_date:
        notes.append("missing verifiable CTA link route or scheduled milestone cadence")

    # Check copy isn't identical across channel headings
    sections = re.split(r"^#{2,5}\s+", text, flags=re.MULTILINE)[1:]
    unique_ratio = len({s.strip()[:80].lower() for s in sections if s.strip()}) / max(1, len(sections))
    if sections and unique_ratio < 0.8:
        notes.append("channel sections duplicate the same opening copy instead of adapting per platform")

    score = (
        (0.35 if distinct_channels else 0.10)
        + (0.30 if has_exposure_gates else 0.05)
        + (0.20 if has_cta_or_date else 0.05)
        + (0.15 * unique_ratio)
    )
    return min(1.0, score), {"channels": channels, "has_exposure_gates": has_exposure_gates, "unique_ratio": round(unique_ratio, 2)}, notes


def _score_treatment_devices(text: str) -> tuple[float, dict[str, Any], list[str]]:
    notes: list[str] = []
    lower = text.lower()
    has_arc = any(k in lower for k in ("open", "turn", "payoff", "close", "story", "premise"))
    has_visual = any(k in lower for k in ("frame", "camera", "visual", "look", "overhead", "light", "shot"))
    has_asset_sep = any(k in lower for k in ("available", "pending", "proposed", "cleared", "tbd", "unknown"))
    if not has_arc:
        notes.append("treatment missing narrative arc (open -> develop/turn -> payoff)")
    if not has_visual:
        notes.append("treatment missing concrete visual/cinematic treatment details")
    if not has_asset_sep:
        notes.append("treatment fails to separate intended story moments from confirmed available assets")
    score = (0.35 if has_arc else 0.1) + (0.35 if has_visual else 0.1) + (0.30 if has_asset_sep else 0.05)
    return score, {"has_arc": has_arc, "has_visual": has_visual, "has_asset_sep": has_asset_sep}, notes


def _lexical_parity_with_exemplar(text: str, exemplar_text: str) -> float:
    """Normalized TF cosine parity against professional exemplar vocabulary & structural density."""
    if not exemplar_text.strip():
        return 0.70
    toks_a = re.findall(r"[a-z0-9]{3,}", text.lower())
    toks_b = re.findall(r"[a-z0-9]{3,}", exemplar_text.lower())
    if not toks_a or not toks_b:
        return 0.0
    freq_a: dict[str, int] = {}
    freq_b: dict[str, int] = {}
    for t in toks_a:
        freq_a[t] = freq_a.get(t, 0) + 1
    for t in toks_b:
        freq_b[t] = freq_b.get(t, 0) + 1
    common = set(freq_a) & set(freq_b)
    dot = sum(freq_a[k] * freq_b[k] for k in common)
    norm = math.sqrt(sum(v * v for v in freq_a.values())) * math.sqrt(sum(v * v for v in freq_b.values()))
    return round(min(1.0, (dot / norm) * 1.45), 3) if norm > 0 else 0.0


def load_professional_exemplar(repo_root: Path, form_id: str) -> str:
    """Extract matching professional reference section from Media Agency practice-exercises.md if present."""
    ex_path = Path(repo_root) / "Knowledge" / "Media Agency" / "Skills and Workflows" / "practice-exercises.md"
    if not ex_path.is_file():
        return ""
    raw = ex_path.read_text(encoding="utf-8", errors="replace")
    markers = {
        "production_brief": "#### Decision brief",
        "av_script": "#### A/V script",
        "call_sheet": "#### Call sheet",
        "shot_list": "#### Shot list",
        "content_calendar": "### Fold and Share release pack",
    }
    marker = markers.get(form_id)
    if not marker or marker not in raw:
        return raw[:1500]
    start = raw.index(marker)
    return raw[start : start + 2400]


def diagnose_form_deliverable(
    text: str,
    raw_form: str,
    *,
    repo_root: Path | None = None,
    strict_cpl_mandates: bool = False,
) -> FormDiagnosticReport:
    """Score a deliverable across structure, writing devices, receiver actionability, and professional parity."""
    form_id = resolve_form_id(raw_form)
    profile = FORM_PROFILES.get(form_id, FORM_PROFILES["production_brief"])
    lower = text.lower()

    cue_hits = sum(1 for c in profile.required_cues if c in lower)
    structure_score = round(cue_hits / len(profile.required_cues), 3) if profile.required_cues else 1.0
    missing_cues = [c for c in profile.required_cues if c not in lower]

    if form_id == "av_script":
        device_score, dev_feats, dev_notes = _score_av_devices(text)
    elif form_id in ("production_brief", "leadership_report"):
        device_score, dev_feats, dev_notes = _score_decision_first_devices(
            text, strict_mandates=(strict_cpl_mandates or form_id == "leadership_report")
        )
    elif form_id == "research_note":
        device_score, dev_feats, dev_notes = _score_research_devices(text)
    elif form_id in ("call_sheet", "shot_list"):
        device_score, dev_feats, dev_notes = _score_operational_table_devices(text, form_id)
    elif form_id == "content_calendar":
        device_score, dev_feats, dev_notes = _score_content_calendar_devices(text)
    else:
        device_score, dev_feats, dev_notes = _score_treatment_devices(text)

    words = _count_words(text)
    brevity_ok = 25 <= words <= profile.max_words_target
    has_next_owner = bool(re.search(r"(owner|confirm|review|verify|check|assign|pending|next)", lower))
    slop_pen, _ = _slop_penalty(text)
    receiver_actionability = round(
        max(0.0, min(1.0, (0.45 if brevity_ok else 0.15) + (0.40 if has_next_owner else 0.10) + 0.15 - slop_pen)),
        3,
    )

    exemplar = load_professional_exemplar(repo_root, form_id) if repo_root is not None else ""
    lex_parity = _lexical_parity_with_exemplar(text, exemplar)
    professional_parity = round(0.55 * device_score + 0.25 * structure_score + 0.20 * lex_parity, 3)

    overall = round(
        0.25 * structure_score
        + 0.35 * device_score
        + 0.20 * receiver_actionability
        + 0.20 * professional_parity,
        3,
    )

    aspects = {
        "structure": structure_score,
        "writing_devices": round(device_score, 3),
        "receiver_actionability": receiver_actionability,
        "professional_parity": professional_parity,
    }
    weakest_aspect = min(aspects, key=lambda k: aspects[k])

    # Compute the 5 writing-domain mastery elements (style, audience, purpose, formatting, stakeholder_connection)
    has_holds = bool(re.search(r"(\[UNKNOWN|TBD|hold|owner:|pending|confirm)", lower))
    has_table = _has_markdown_table(text)
    style_el = round(max(0.0, min(1.0, (0.60 * device_score + 0.40 * (1.0 if brevity_ok else 0.35)) - slop_pen)), 3)
    audience_el = round(max(0.0, min(1.0, 0.50 * receiver_actionability + 0.30 * lex_parity + (0.20 if brevity_ok else 0.05))), 3)
    purpose_el = round(max(0.0, min(1.0, 0.50 * structure_score + 0.50 * device_score)), 3)
    fmt_table_bonus = 0.25 if (form_id in ("av_script", "call_sheet", "shot_list", "content_calendar") and has_table) else (0.25 if "##" in text or "**" in text else 0.10)
    formatting_el = round(max(0.0, min(1.0, 0.55 * structure_score + 0.20 * (1.0 if brevity_ok else 0.4) + fmt_table_bonus)), 3)
    stakeholder_el = round(max(0.0, min(1.0, 0.55 * receiver_actionability + (0.30 if has_holds else 0.05) + 0.15 * professional_parity)), 3)
    element_scores = {
        "style": style_el,
        "audience": audience_el,
        "purpose": purpose_el,
        "formatting": formatting_el,
        "stakeholder_connection": stakeholder_el,
    }
    weakest_element = min(element_scores, key=lambda k: element_scores[k])
    spec_attr = {
        "style": "style_spec",
        "audience": "audience_spec",
        "purpose": "purpose_spec",
        "formatting": "formatting_spec",
        "stakeholder_connection": "stakeholder_spec",
    }[weakest_element]
    mastery_tip = getattr(profile, spec_attr, "")

    diag_parts: list[str] = []
    if missing_cues:
        diag_parts.append(f"missing cues {missing_cues}")
    diag_parts.extend(dev_notes[:2])
    if not brevity_ok:
        diag_parts.append(f"word count {words} outside [25, {profile.max_words_target}]")
    diagnosis = f"{form_id}: " + ("; ".join(diag_parts) if diag_parts else "matches professional baseline")

    return FormDiagnosticReport(
        form_id=form_id,
        overall_score=overall,
        structure_score=structure_score,
        device_score=round(device_score, 3),
        receiver_actionability=receiver_actionability,
        professional_parity=professional_parity,
        weakest_aspect=weakest_aspect,
        diagnosis=diagnosis,
        measured_features={"words": words, **dev_feats, "missing_cues": missing_cues},
        element_scores=element_scores,
        weakest_element=weakest_element,
        mastery_tip=mastery_tip,
    )
