"""Deterministic Story Engine: form grammars, DP story-arc clip selection, CHG-01, and K-MCP-01 stdio RPC."""

from __future__ import annotations

import hashlib
import json
import math
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

_TRANSCRIBE_HOLD_RE = re.compile(
    r"\b(?:transcrib\w*|whisper|asr|speech[- ]to[- ]text|fresh\s+speech)\b",
    re.IGNORECASE,
)
_CUT_APPROVAL_HOLD_RE = re.compile(
    r"\b(?:approve(?:\s+\w+){0,2}\s+cut|editorial\s+approval|final\s+cut|sign\s+off|publish\s+cut|release\s+cut)\b",
    re.IGNORECASE,
)
_CARRYOVER_APPROVAL_RE = re.compile(
    r"\b(?:prior\s+approval\s+covers\s+(?:this\s+)?(?:new\s+)?cut|"
    r"extend\s+prior\s+approval\s+to\s+this\s+cut|"
    r"covered\s+by\s+prior\s+(?:cut\s+)?approval|"
    r"carryover\s+(?:cut\s+)?approval)\b",
    re.IGNORECASE,
)
_SPOKEN_CUE_RE = re.compile(
    r"\b(?:narrator|narration|voiceover|dialogue|vo)\s*:",
    re.IGNORECASE,
)
_TIMECODE_RE = re.compile(r"\b(\d{2}):(\d{2})\s*-\s*(\d{2}):(\d{2})\b")
_SEP_CELL_RE = re.compile(r"^:?-{3,}:?$")
_WORD_RE = re.compile(r"[a-z0-9]+")


@dataclass(frozen=True)
class FormSpec:
    """Declarative specification of an editorial document or selection form."""

    form_id: str
    required_sections: tuple[str, ...]
    layout: str
    pinned_procedure: str | None
    keywords: tuple[str, ...]


FORMS: dict[str, FormSpec] = {
    "av_script": FormSpec(
        form_id="av_script",
        required_sections=("beat-*",),
        layout="timed_av",
        pinned_procedure="MW-04",
        keywords=(
            "av script",
            "a/v script",
            "audio-video",
            "timed script",
            "timecode",
            "voiceover",
            "beat sheet",
            "av_script",
        ),
    ),
    "treatment": FormSpec(
        form_id="treatment",
        required_sections=("premise", "arc", "visual_approach"),
        layout="prose",
        pinned_procedure="MW-02",
        keywords=(
            "treatment",
            "creative treatment",
            "visual approach",
            "look and feel",
            "narrative treatment",
        ),
    ),
    "production_brief": FormSpec(
        form_id="production_brief",
        required_sections=("objective", "audience", "deliverables"),
        layout="brief",
        pinned_procedure="MW-01",
        keywords=(
            "production brief",
            "creative brief",
            "shoot brief",
            "deliverables",
            "production_brief",
        ),
    ),
    "story_arc": FormSpec(
        form_id="story_arc",
        required_sections=("open", "develop", "payoff_close"),
        layout="arc",
        pinned_procedure=None,
        keywords=(
            "story arc",
            "narrative arc",
            "three act",
            "storyline",
            "story_arc",
        ),
    ),
    "clip_select": FormSpec(
        form_id="clip_select",
        required_sections=("selected_clips", "limits"),
        layout="clip_manifest",
        pinned_procedure=None,
        keywords=(
            "clip select",
            "clip selection",
            "saved transcript",
            "transcript clips",
            "extract clips",
            "clip_select",
        ),
    ),
}


@dataclass(frozen=True)
class TranscriptSegment:
    """Single timestamped segment from a retained transcript."""

    id: str
    start: float
    end: float
    text: str
    speaker: str = ""
    arc_hint: str = ""


def recognize_form(brief: str) -> dict[str, Any]:
    """Deterministically recognize form or abstain/hold per K-STORY-01 and K-MCP-01."""
    text = (brief or "").strip()
    if _TRANSCRIBE_HOLD_RE.search(text):
        return {
            "form": "hold_out_of_scope",
            "abstained": True,
            "pinned_craft": None,
            "score": 0,
            "hold_reason": "fresh_speech_transcription_out_of_scope",
        }
    if _CUT_APPROVAL_HOLD_RE.search(text):
        return {
            "form": "hold_out_of_scope",
            "abstained": True,
            "pinned_craft": None,
            "score": 0,
            "hold_reason": "editorial_cut_approval_requires_human_authority",
        }

    lowered = text.lower()
    best_spec: FormSpec | None = None
    best_score = 0
    for spec in FORMS.values():
        score = 0
        for kw in spec.keywords:
            pattern = re.compile(r"\b" + re.escape(kw.lower()) + r"\b")
            matches = pattern.findall(lowered)
            if matches:
                weight = max(1, len(kw.split()))
                score += weight * len(matches)
        if score > best_score:
            best_score = score
            best_spec = spec

    if best_spec is None or best_score == 0:
        return {
            "form": None,
            "abstained": True,
            "pinned_craft": None,
            "score": 0,
        }

    pinned_craft = (
        {"procedure_id": best_spec.pinned_procedure, "role": "method", "use": "craft"}
        if best_spec.pinned_procedure is not None
        else None
    )
    return {
        "form": best_spec.form_id,
        "abstained": False,
        "pinned_craft": pinned_craft,
        "score": best_score,
    }


def _section_id(section: dict[str, Any]) -> str:
    return str(section.get("id") or section.get("name") or section.get("section") or "").strip()


def _section_body(section: dict[str, Any]) -> str:
    return str(section.get("body") or section.get("content") or section.get("text") or "")


def _check_required_ordered_sections(
    required_sections: tuple[str, ...],
    section_ids: list[str],
    defects: list[str],
) -> None:
    cursor = 0
    for req in required_sections:
        if req.endswith("*"):
            prefix = req[:-1]
            found_idx = None
            for idx in range(cursor, len(section_ids)):
                if section_ids[idx].startswith(prefix):
                    found_idx = idx
                    break
            if found_idx is None:
                defects.append(f"missing required ordered section matching '{req}'")
                return
            cursor = found_idx + 1
            while cursor < len(section_ids) and section_ids[cursor].startswith(prefix):
                cursor += 1
        else:
            found_idx = None
            for idx in range(cursor, len(section_ids)):
                if section_ids[idx] == req:
                    found_idx = idx
                    break
            if found_idx is None:
                defects.append(f"missing or out-of-order required section '{req}'")
                return
            cursor = found_idx + 1


def _parse_mmss(mm: str, ss: str) -> int | None:
    minutes = int(mm)
    seconds = int(ss)
    if seconds >= 60:
        return None
    return minutes * 60 + seconds


def _split_md_row(line: str) -> list[str] | None:
    stripped = line.strip()
    if not (stripped.startswith("|") and stripped.endswith("|")):
        return None
    inner = stripped[1:-1]
    return [cell.strip() for cell in inner.split("|")]


def _validate_timed_av_beat(
    sec_id: str,
    body: str,
    cursor: int,
    audio_mode: str,
    defects: list[str],
) -> int:
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    table_rows: list[list[str]] = []
    for ln in lines:
        if ln.startswith("|"):
            cells = _split_md_row(ln)
            if cells is None:
                defects.append(f"{sec_id}: malformed Markdown table row '{ln}'")
                return cursor
            table_rows.append(cells)

    if len(table_rows) < 3:
        defects.append(f"{sec_id}: expected Markdown table with header, separator, and >=1 data row")
        return cursor

    header = [c.lower() for c in table_rows[0]]
    if header != ["section", "audio", "video"]:
        defects.append(f"{sec_id}: table header must be '| Section | Audio | Video |'")
        return cursor

    sep = table_rows[1]
    if len(sep) != 3 or not all(_SEP_CELL_RE.match(c) for c in sep):
        defects.append(f"{sec_id}: invalid Markdown table separator row")
        return cursor

    for row_idx, row in enumerate(table_rows[2:], start=1):
        if len(row) != 3:
            defects.append(f"{sec_id} row {row_idx}: expected 3 columns")
            continue
        sec_cell, audio_cell, video_cell = row
        if not sec_cell or not audio_cell or not video_cell:
            defects.append(f"{sec_id} row {row_idx}: empty cell in '| Section | Audio | Video |'")
            continue
        tc_match = _TIMECODE_RE.search(sec_cell)
        if tc_match is None:
            defects.append(f"{sec_id} row {row_idx}: missing MM:SS - MM:SS timecode in '{sec_cell}'")
            continue
        start_sec = _parse_mmss(tc_match.group(1), tc_match.group(2))
        end_sec = _parse_mmss(tc_match.group(3), tc_match.group(4))
        if start_sec is None or end_sec is None:
            defects.append(f"{sec_id} row {row_idx}: invalid seconds in timecode '{tc_match.group(0)}'")
            continue
        if start_sec != cursor:
            defects.append(
                f"{sec_id} row {row_idx}: non-contiguous timecode start {start_sec}s != cursor {cursor}s"
            )
        if end_sec <= start_sec:
            defects.append(
                f"{sec_id} row {row_idx}: non-positive duration ({start_sec}s -> {end_sec}s)"
            )
        else:
            cursor = end_sec

        if audio_mode == "music_only" and _SPOKEN_CUE_RE.search(audio_cell):
            defects.append(
                f"{sec_id} row {row_idx}: spoken cue disallowed in audio_mode='music_only'"
            )

    return cursor


def _claim_kind(claim: dict[str, Any]) -> str:
    return str(claim.get("type") or claim.get("kind") or claim.get("claim_type") or "").strip().lower()


def validate_editorial_grammar(
    form_id: str,
    sections: list[dict[str, str]],
    *,
    audio_mode: str = "standard",
    min_seconds: int = 0,
    max_seconds: int | None = None,
    sources: dict[str, str] | None = None,
    claims: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """Validate ordered sections, timed AV tables, carryover approvals, and grounded claims."""
    defects: list[str] = []
    spec = FORMS.get(form_id)
    if spec is None:
        return {"ok": False, "defects": [f"unknown form_id '{form_id}'"], "total_duration_sec": 0}

    norm_sections = [(_section_id(s), _section_body(s)) for s in sections]
    section_ids = [sid for sid, _ in norm_sections]
    section_map = {sid: body for sid, body in norm_sections}

    _check_required_ordered_sections(spec.required_sections, section_ids, defects)

    cursor = 0
    if spec.layout == "timed_av":
        for sid, body in norm_sections:
            if sid.startswith("beat-"):
                cursor = _validate_timed_av_beat(sid, body, cursor, audio_mode, defects)
        if cursor < min_seconds:
            defects.append(f"total duration {cursor}s is below min_seconds {min_seconds}s")
        if max_seconds is not None and cursor > max_seconds:
            defects.append(f"total duration {cursor}s exceeds max_seconds {max_seconds}s")

    sources_map = sources or {}
    claims_list = claims or []
    verified_permission_sections: set[str] = set()
    has_global_verified_permission = False

    for idx, claim in enumerate(claims_list):
        span = str(claim.get("span") or "")
        source_id = str(claim.get("source_id") or "")
        target_sec = claim.get("section") or claim.get("section_id")
        if not span:
            defects.append(f"claim[{idx}]: empty span")
            continue

        if target_sec is not None:
            target_sec_str = str(target_sec).strip()
            body = section_map.get(target_sec_str)
            if body is None:
                defects.append(f"claim[{idx}]: section '{target_sec_str}' not found")
                occ = 0
            else:
                occ = body.count(span)
        else:
            occ = sum(body.count(span) for _, body in norm_sections)

        if occ == 0:
            defects.append(f"claim[{idx}]: span {span!r} not found in section body")
        elif occ > 1:
            defects.append(f"claim[{idx}]: span {span!r} is not unique (occurrences={occ})")

        source_text = sources_map.get(source_id)
        if source_text is None:
            defects.append(f"claim[{idx}]: unknown source_id '{source_id}'")
            continue

        quote = str(claim.get("quote") or claim.get("figure") or span)
        if quote not in source_text:
            defects.append(
                f"claim[{idx}]: ungrounded quote/figure {quote!r} not in source '{source_id}'"
            )
        elif _claim_kind(claim) == "permission" and occ == 1:
            if target_sec is not None:
                verified_permission_sections.add(str(target_sec).strip())
            else:
                has_global_verified_permission = True

    for sid, body in norm_sections:
        if _CARRYOVER_APPROVAL_RE.search(body):
            if not (has_global_verified_permission or sid in verified_permission_sections):
                defects.append(
                    f"{sid}: carryover cut-approval phrase disallowed without verified permission claim"
                )

    return {
        "ok": len(defects) == 0,
        "defects": defects,
        "total_duration_sec": cursor,
    }


def load_transcript_segments(path: Path) -> tuple[list[TranscriptSegment], str]:
    """Load saved transcript segments from .json or .txt and return (segments, sha256_hex)."""
    p = Path(path)
    raw_bytes = p.read_bytes()
    sha256_hex = hashlib.sha256(raw_bytes).hexdigest()
    raw_text = raw_bytes.decode("utf-8")

    segments: list[TranscriptSegment] = []
    if p.suffix.lower() == ".json":
        payload = json.loads(raw_text)
        items = payload.get("segments", []) if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            raise ValueError("JSON transcript must be a list or contain a 'segments' list")
        for idx, item in enumerate(items, start=1):
            segments.append(
                TranscriptSegment(
                    id=str(item.get("id", f"seg-{idx}")),
                    start=float(item["start"]),
                    end=float(item["end"]),
                    text=str(item.get("text", "")),
                    speaker=str(item.get("speaker", "")),
                    arc_hint=str(item.get("arc_hint", "")),
                )
            )
    else:
        lines = [ln.strip() for ln in raw_text.splitlines() if ln.strip()]
        for idx, line in enumerate(lines):
            segments.append(
                TranscriptSegment(
                    id=f"seg-{idx + 1}",
                    start=float(idx * 5),
                    end=float((idx + 1) * 5),
                    text=line,
                )
            )
    return segments, sha256_hex


def _is_finite_number(val: Any) -> bool:
    return not isinstance(val, bool) and isinstance(val, (int, float)) and math.isfinite(float(val))


def validate_clip_intervals(
    clips: list[dict[str, Any]],
    *,
    allow_overlap: bool = False,
) -> tuple[bool, list[dict[str, Any]], list[str]]:
    """Validate 0 <= start < end, finite numerics, optional non-overlap, and compute duration."""
    errors: list[str] = []
    normalized: list[dict[str, Any]] = []

    for idx, clip in enumerate(clips):
        start_raw = clip.get("start")
        end_raw = clip.get("end")
        if not _is_finite_number(start_raw) or not _is_finite_number(end_raw):
            errors.append(f"clip[{idx}]: non-finite or non-numeric start/end")
            continue
        start = float(start_raw)
        end = float(end_raw)
        if start < 0.0:
            errors.append(f"clip[{idx}]: negative start {start}")
            continue
        if end <= start:
            errors.append(f"clip[{idx}]: end {end} must be > start {start}")
            continue
        item = dict(clip)
        item["start"] = start
        item["end"] = end
        item["duration"] = round(end - start, 3)
        normalized.append(item)

    if not allow_overlap and normalized:
        normalized.sort(key=lambda c: (c["start"], c["end"], str(c.get("id", ""))))
        prev_end = -1.0
        for idx, item in enumerate(normalized):
            if item["start"] < prev_end:
                errors.append(
                    f"clip[{idx}] ({item.get('id', idx)}): overlap start {item['start']} < prev_end {prev_end}"
                )
            if item["end"] > prev_end:
                prev_end = item["end"]

    return len(errors) == 0, normalized, errors


def _tokenize(text: str) -> list[str]:
    return _WORD_RE.findall(text.lower())


def select_story_arc_clips(
    segments: list[TranscriptSegment],
    query_terms: list[str],
    *,
    max_duration_sec: float = 60.0,
    arc_stages: tuple[str, ...] = ("OPEN", "DEVELOP", "PAYOFF_CLOSE"),
) -> dict[str, Any]:
    """Solve exact DP over non-overlapping valid segments and decisecond budget for story arc."""
    if not arc_stages:
        raise ValueError("arc_stages must be non-empty")
    if not _is_finite_number(max_duration_sec) or float(max_duration_sec) <= 0.0:
        raise ValueError("max_duration_sec must be finite and > 0")

    budget_ds = int(round(float(max_duration_sec) * 10))
    valid_segs: list[TranscriptSegment] = []
    rejected_ids: list[str] = []
    for seg in segments:
        if (
            _is_finite_number(seg.start)
            and _is_finite_number(seg.end)
            and 0.0 <= float(seg.start) < float(seg.end)
        ):
            dur_ds = max(1, int(round((float(seg.end) - float(seg.start)) * 10)))
            if dur_ds <= budget_ds:
                valid_segs.append(seg)
        else:
            rejected_ids.append(seg.id)

    valid_segs.sort(key=lambda s: (float(s.start), float(s.end), s.id))
    n = len(valid_segs)
    k = len(arc_stages)

    if n == 0:
        empty_sha = hashlib.sha256(b"[]").hexdigest()
        return {
            "clips": [],
            "total_duration_sec": 0.0,
            "total_score": 0.0,
            "story_arc_complete": False,
            "selection_sha256": empty_sha,
            "rejected_segment_ids": rejected_ids,
        }

    query_tokens: list[str] = []
    seen_q: set[str] = set()
    for term in query_terms:
        for tok in _tokenize(term):
            if tok not in seen_q:
                seen_q.add(tok)
                query_tokens.append(tok)

    seg_token_counts: list[dict[str, int]] = []
    for seg in valid_segs:
        counts: dict[str, int] = {}
        for tok in _tokenize(seg.text):
            counts[tok] = counts.get(tok, 0) + 1
        seg_token_counts.append(counts)

    idf: dict[str, float] = {}
    for qt in query_tokens:
        df = sum(1 for counts in seg_token_counts if qt in counts)
        idf[qt] = math.log((n + 1.0) / (df + 1.0)) + 1.0

    rel_scores: list[float] = []
    for counts in seg_token_counts:
        if not query_tokens:
            rel_scores.append(0.5)
        else:
            score = 0.0
            for qt in query_tokens:
                cnt = counts.get(qt, 0)
                if cnt > 0:
                    score += idf[qt] * (1.0 + 0.5 * min(cnt - 1, 3))
            rel_scores.append(score)

    dur_ds_list = [max(1, int(round((float(s.end) - float(s.start)) * 10))) for s in valid_segs]
    stages_upper = [st.strip().upper() for st in arc_stages]

    def _align_bonus(seg_idx: int, stage_idx: int) -> float:
        hint = valid_segs[seg_idx].arc_hint.strip().upper()
        if not hint:
            return 0.25
        if hint == stages_upper[stage_idx]:
            return 3.0
        return -0.5

    neg_inf = float("-inf")
    dp_score: list[list[list[float]]] = [
        [[neg_inf] * (budget_ds + 1) for _ in range(k)] for _ in range(n)
    ]
    dp_prev: list[list[list[tuple[int, int, int] | None]]] = [
        [[None] * (budget_ds + 1) for _ in range(k)] for _ in range(n)
    ]
    dp_step: list[list[list[float]]] = [
        [[0.0] * (budget_ds + 1) for _ in range(k)] for _ in range(n)
    ]

    avail_score: list[list[float]] = [[neg_inf] * (budget_ds + 1) for _ in range(k)]
    avail_src: list[list[tuple[int, int, int] | None]] = [
        [None] * (budget_ds + 1) for _ in range(k)
    ]

    end_sorted = sorted(range(n), key=lambda idx: (float(valid_segs[idx].end), float(valid_segs[idx].start), idx))
    end_ptr = 0

    best_total = 0.0
    best_state: tuple[int, int, int] | None = None

    for i in range(n):
        seg_start = float(valid_segs[i].start)
        while end_ptr < n and float(valid_segs[end_sorted[end_ptr]].end) <= seg_start + 1e-9:
            j = end_sorted[end_ptr]
            for st_j in range(k):
                row_j = dp_score[j][st_j]
                avail_row = avail_score[st_j]
                avail_src_row = avail_src[st_j]
                for w in range(budget_ds + 1):
                    val = row_j[w]
                    if val > avail_row[w]:
                        avail_row[w] = val
                        avail_src_row[w] = (j, st_j, w)
            end_ptr += 1

        dur_i = dur_ds_list[i]
        rel_i = rel_scores[i]
        for st in range(k):
            align_i = _align_bonus(i, st)
            start_bonus = 2.0 if st == 0 else 0.0
            start_score = rel_i + align_i + start_bonus
            if start_score > dp_score[i][st][dur_i]:
                dp_score[i][st][dur_i] = start_score
                dp_prev[i][st][dur_i] = None
                dp_step[i][st][dur_i] = start_score

            for prev_st in range(st + 1):
                if st == prev_st + 1:
                    trans = 4.0
                elif st > prev_st + 1:
                    trans = 1.0
                else:
                    trans = 0.25
                avail_row = avail_score[prev_st]
                avail_src_row = avail_src[prev_st]
                step_gain = rel_i + align_i + trans
                target_row = dp_score[i][st]
                target_prev = dp_prev[i][st]
                target_step = dp_step[i][st]
                limit_w = budget_ds - dur_i
                for w_prev in range(limit_w + 1):
                    prev_val = avail_row[w_prev]
                    if prev_val == neg_inf:
                        continue
                    cand = prev_val + step_gain
                    w_new = w_prev + dur_i
                    if cand > target_row[w_new]:
                        target_row[w_new] = cand
                        target_prev[w_new] = avail_src_row[w_prev]
                        target_step[w_new] = step_gain

            for w in range(dur_i, budget_ds + 1):
                val = dp_score[i][st][w]
                if val > best_total:
                    best_total = val
                    best_state = (i, st, w)

    chain: list[tuple[int, int, float]] = []
    cur = best_state
    while cur is not None:
        ci, cst, cw = cur
        chain.append((ci, cst, dp_step[ci][cst][cw]))
        cur = dp_prev[ci][cst][cw]
    chain.reverse()

    selected_list: list[dict[str, Any]] = []
    stages_seen: set[str] = set()
    total_duration = 0.0
    for idx_seg, st_idx, clip_score in chain:
        seg = valid_segs[idx_seg]
        dur = round(float(seg.end) - float(seg.start), 3)
        total_duration += dur
        stage_label = arc_stages[st_idx]
        stages_seen.add(stage_label)
        selected_list.append(
            {
                "id": seg.id,
                "start": float(seg.start),
                "end": float(seg.end),
                "duration": dur,
                "text": seg.text,
                "speaker": seg.speaker,
                "arc_hint": seg.arc_hint,
                "arc_stage": stage_label,
                "score": round(clip_score, 4),
            }
        )

    canon = json.dumps(
        {
            "clips": selected_list,
            "arc_stages": list(arc_stages),
            "max_duration_sec": round(float(max_duration_sec), 3),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    selection_sha256 = hashlib.sha256(canon).hexdigest()

    return {
        "clips": selected_list,
        "total_duration_sec": round(total_duration, 3),
        "total_score": round(best_total, 4),
        "story_arc_complete": all(stage in stages_seen for stage in arc_stages),
        "selection_sha256": selection_sha256,
        "rejected_segment_ids": rejected_ids,
    }


def compute_chg01_fingerprint(
    transcript_sha256: str,
    brief: str,
    query_terms: list[str],
    max_duration_sec: float,
) -> str:
    """Compute canonical CHG-01 SHA-256 fingerprint over transcript bytes and selection inputs."""
    payload = {
        "transcript_sha256": transcript_sha256,
        "brief": brief.strip(),
        "query_terms": [t.strip().lower() for t in query_terms if t.strip()],
        "max_duration_sec": round(float(max_duration_sec), 3),
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def export_clip_manifest(
    selection: dict[str, Any],
    source_path: Path,
    source_sha256: str,
    chg01_sha256: str,
    output_dir: Path | None = None,
) -> dict[str, Any]:
    """Build and optionally write clip manifest JSON and Markdown summary without NLE creep."""
    clips = [
        {
            "id": str(c["id"]),
            "start": float(c["start"]),
            "end": float(c["end"]),
            "duration": float(c.get("duration", round(float(c["end"]) - float(c["start"]), 3))),
            "arc_stage": str(c.get("arc_stage", "")),
            "speaker": str(c.get("speaker", "")),
            "text": str(c.get("text", "")),
            "score": float(c.get("score", 0.0)),
        }
        for c in selection.get("clips", [])
    ]
    limits = [
        "Saved-transcript clip selection only; no fresh speech transcription (K-STORY-01).",
        "No editorial cut approval or non-linear editor project export (K-MCP-01).",
        "CHG-01 fingerprint invalidates on any source transcript byte or selection input change.",
    ]
    manifest: dict[str, Any] = {
        "schema_version": "storylane.clip_manifest.v1",
        "source_path": str(source_path),
        "source_sha256": source_sha256,
        "chg01_sha256": chg01_sha256,
        "selection_sha256": str(selection.get("selection_sha256", "")),
        "total_duration_sec": float(selection.get("total_duration_sec", 0.0)),
        "story_arc_complete": bool(selection.get("story_arc_complete", False)),
        "clips": clips,
        "limits": limits,
    }

    manifest_path: Path | None = None
    markdown_path: Path | None = None
    if output_dir is not None:
        out_dir = Path(output_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        manifest_path = out_dir / "storylane_clip_manifest.json"
        markdown_path = out_dir / "storylane_clip_select.md"

        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )

        md_lines = [
            "# Story-Lane Clip Selection",
            "",
            f"- **Source Path:** `{source_path}`",
            f"- **Source SHA-256:** `{source_sha256}`",
            f"- **CHG-01 SHA-256:** `{chg01_sha256}`",
            f"- **Total Duration:** {manifest['total_duration_sec']}s",
            f"- **Story Arc Complete:** {manifest['story_arc_complete']}",
            "",
            "## Selected Clips",
            "",
            "| Clip ID | Arc Stage | Start (s) | End (s) | Duration (s) | Text |",
            "| --- | --- | --- | --- | --- | --- |",
        ]
        for c in clips:
            safe_text = c["text"].replace("|", "\\|").replace("\n", " ")
            md_lines.append(
                f"| {c['id']} | {c['arc_stage']} | {c['start']:.2f} | {c['end']:.2f} | {c['duration']:.2f} | {safe_text} |"
            )
        md_lines.extend(["", "## Limits", ""])
        for lim in limits:
            md_lines.append(f"- {lim}")
        md_lines.append("")
        markdown_path.write_text("\n".join(md_lines), encoding="utf-8")

    return {
        "manifest": manifest,
        "manifest_path": str(manifest_path) if manifest_path is not None else None,
        "markdown_path": str(markdown_path) if markdown_path is not None else None,
    }


def check_chg01_invalidation(
    manifest: dict[str, Any],
    current_transcript_path: Path,
    brief: str = "",
    query_terms: list[str] | None = None,
    max_duration_sec: float | None = None,
) -> dict[str, Any]:
    """Re-hash live transcript bytes and recompute CHG-01 fingerprint to detect staleness."""
    p = Path(current_transcript_path)
    live_source_sha256 = hashlib.sha256(p.read_bytes()).hexdigest()
    reasons: list[str] = []

    if live_source_sha256 != manifest.get("source_sha256"):
        reasons.append("source_sha256_mismatch")

    if brief or query_terms is not None or max_duration_sec is not None:
        qt = query_terms if query_terms is not None else []
        md = float(max_duration_sec) if max_duration_sec is not None else 60.0
        live_chg01 = compute_chg01_fingerprint(live_source_sha256, brief, qt, md)
        if live_chg01 != manifest.get("chg01_sha256"):
            reasons.append("chg01_fingerprint_mismatch")

    stale = len(reasons) > 0
    return {
        "stale": stale,
        "status": "STALE_NEEDS_RECHECK" if stale else "CURRENT",
        "reasons": reasons,
        "live_source_sha256": live_source_sha256,
        "manifest_source_sha256": manifest.get("source_sha256", ""),
        "manifest_chg01_sha256": manifest.get("chg01_sha256", ""),
    }


TOOL_DEFINITIONS: list[dict[str, Any]] = [
    {
        "name": "story_recognize",
        "description": "Recognize editorial form and enforce K-STORY-01 / K-MCP-01 scope holds.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "brief": {"type": "string", "description": "Commission or editorial brief."},
            },
            "required": ["brief"],
        },
    },
    {
        "name": "story_select_and_verify",
        "description": "Run DP story-arc clip selection, interval validation, and optional editorial grammar check.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "transcript_path": {"type": "string"},
                "segments": {"type": "array", "items": {"type": "object"}},
                "query_terms": {"type": "array", "items": {"type": "string"}},
                "max_duration_sec": {"type": "number", "default": 60.0},
                "arc_stages": {"type": "array", "items": {"type": "string"}},
                "form_id": {"type": "string"},
                "sections": {"type": "array", "items": {"type": "object"}},
                "audio_mode": {"type": "string", "default": "standard"},
                "min_seconds": {"type": "integer", "default": 0},
                "max_seconds": {"type": "integer"},
                "sources": {"type": "object"},
                "claims": {"type": "array", "items": {"type": "object"}},
            },
        },
    },
    {
        "name": "story_export_and_chg01",
        "description": "Export storylane clip manifest/markdown or check CHG-01 staleness against live transcript.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "transcript_path": {"type": "string"},
                "selection": {"type": "object"},
                "manifest": {"type": "object"},
                "brief": {"type": "string", "default": ""},
                "query_terms": {"type": "array", "items": {"type": "string"}},
                "max_duration_sec": {"type": "number", "default": 60.0},
                "output_dir": {"type": "string"},
            },
            "required": ["transcript_path"],
        },
    },
]


def _rpc_error(req_id: Any, code: int, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "error": {"code": code, "message": message}}


def _dispatch_tool(name: str, args: dict[str, Any]) -> dict[str, Any]:
    if name == "story_recognize":
        return recognize_form(str(args["brief"]))

    if name == "story_select_and_verify":
        source_sha256 = ""
        if "transcript_path" in args and args["transcript_path"] is not None:
            segs, source_sha256 = load_transcript_segments(Path(args["transcript_path"]))
        elif "segments" in args and args["segments"] is not None:
            raw_segs = args["segments"]
            segs = [
                TranscriptSegment(
                    id=str(s.get("id", f"seg-{idx}")),
                    start=float(s["start"]),
                    end=float(s["end"]),
                    text=str(s.get("text", "")),
                    speaker=str(s.get("speaker", "")),
                    arc_hint=str(s.get("arc_hint", "")),
                )
                for idx, s in enumerate(raw_segs, start=1)
            ]
            source_sha256 = hashlib.sha256(
                json.dumps([asdict(s) for s in segs], sort_keys=True).encode("utf-8")
            ).hexdigest()
        else:
            segs = []

        query_terms = [str(t) for t in args.get("query_terms", [])]
        max_dur = float(args.get("max_duration_sec", 60.0))
        arc_stages = tuple(str(x) for x in args.get("arc_stages", ("OPEN", "DEVELOP", "PAYOFF_CLOSE")))
        selection = select_story_arc_clips(
            segs,
            query_terms,
            max_duration_sec=max_dur,
            arc_stages=arc_stages,
        )
        ok_intervals, norm_clips, interval_errors = validate_clip_intervals(selection["clips"])
        result: dict[str, Any] = {
            "source_sha256": source_sha256,
            "selection": selection,
            "intervals_ok": ok_intervals,
            "interval_errors": interval_errors,
            "validated_clips": norm_clips,
        }
        if "form_id" in args and "sections" in args:
            result["grammar_validation"] = validate_editorial_grammar(
                str(args["form_id"]),
                list(args["sections"]),
                audio_mode=str(args.get("audio_mode", "standard")),
                min_seconds=int(args.get("min_seconds", 0)),
                max_seconds=args.get("max_seconds"),
                sources=args.get("sources"),
                claims=args.get("claims"),
            )
        return result

    if name == "story_export_and_chg01":
        t_path = Path(args["transcript_path"])
        if "manifest" in args and args["manifest"] is not None:
            return check_chg01_invalidation(
                dict(args["manifest"]),
                t_path,
                brief=str(args.get("brief", "")),
                query_terms=args.get("query_terms"),
                max_duration_sec=args.get("max_duration_sec"),
            )
        segs, src_sha = load_transcript_segments(t_path)
        query_terms = [str(t) for t in args.get("query_terms", [])]
        max_dur = float(args.get("max_duration_sec", 60.0))
        brief = str(args.get("brief", ""))
        selection = args.get("selection")
        if selection is None:
            selection = select_story_arc_clips(segs, query_terms, max_duration_sec=max_dur)
        chg01_sha = compute_chg01_fingerprint(src_sha, brief, query_terms, max_dur)
        out_dir = Path(args["output_dir"]) if args.get("output_dir") else None
        exported = export_clip_manifest(selection, t_path, src_sha, chg01_sha, out_dir)
        chg01_check = check_chg01_invalidation(
            exported["manifest"],
            t_path,
            brief=brief,
            query_terms=query_terms,
            max_duration_sec=max_dur,
        )
        return {**exported, "chg01_check": chg01_check}

    raise KeyError(f"Unknown tool: {name}")


def handle_rpc_message(message: dict[str, Any]) -> dict[str, Any] | None:
    """Process one JSON-RPC 2.0 request/notification dict and return response or None."""
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return _rpc_error(message.get("id") if isinstance(message, dict) else None, -32600, "Invalid Request")

    method = message.get("method")
    req_id = message.get("id")
    params = message.get("params") or {}

    if "id" not in message or (req_id is None and str(method or "").startswith("notifications/")):
        return None

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "story-engine", "version": "1.0.0"},
            },
        }
    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": TOOL_DEFINITIONS}}
    if method == "tools/call":
        tool_name = params.get("name")
        tool_args = params.get("arguments") or {}
        if not isinstance(tool_name, str) or not isinstance(tool_args, dict):
            return _rpc_error(req_id, -32602, "Invalid params for tools/call")
        try:
            payload = _dispatch_tool(tool_name, tool_args)
        except KeyError as exc:
            return _rpc_error(req_id, -32602, str(exc))
        except (ValueError, FileNotFoundError, TypeError) as exc:
            return {
                "jsonrpc": "2.0",
                "id": req_id,
                "result": {
                    "content": [{"type": "text", "text": str(exc)}],
                    "isError": True,
                },
            }
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [{"type": "text", "text": json.dumps(payload, indent=2)}],
                "structuredContent": payload,
                "isError": False,
            },
        }

    return _rpc_error(req_id, -32601, f"Method not found: {method}")


def serve_stdio() -> None:
    """Serve K-MCP-01 JSON-RPC 2.0 messages over stdin/stdout line-by-line."""
    for raw_line in sys.stdin:
        line = raw_line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as exc:
            resp: dict[str, Any] | None = _rpc_error(None, -32700, f"Parse error: {exc}")
        else:
            resp = handle_rpc_message(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    serve_stdio()
