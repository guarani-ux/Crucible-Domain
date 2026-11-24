"""Tests for deterministic Crucible story_engine (grammars, DP arc selection, CHG-01, JSON-RPC)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from crucible.story_engine import (
    TOOL_DEFINITIONS,
    TranscriptSegment,
    check_chg01_invalidation,
    compute_chg01_fingerprint,
    export_clip_manifest,
    handle_rpc_message,
    load_transcript_segments,
    recognize_form,
    select_story_arc_clips,
    validate_clip_intervals,
    validate_editorial_grammar,
)


def test_recognize_form_and_k_story_holds() -> None:
    av = recognize_form("Draft an AV script with voiceover timecode beats")
    assert av["form"] == "av_script"
    assert av["abstained"] is False
    assert av["pinned_craft"] == {"procedure_id": "MW-04", "role": "method", "use": "craft"}

    tx_hold = recognize_form("Please transcribe this raw audio with whisper asr")
    assert tx_hold["form"] == "hold_out_of_scope"
    assert tx_hold["abstained"] is True
    assert tx_hold["pinned_craft"] is None

    cut_hold = recognize_form("Approve final cut and publish cut to channel")
    assert cut_hold["form"] == "hold_out_of_scope"
    assert cut_hold["abstained"] is True
    assert cut_hold["pinned_craft"] is None

    noise = recognize_form("zxqv plugh banana waffle")
    assert noise["form"] is None
    assert noise["abstained"] is True
    assert noise["pinned_craft"] is None


def test_editorial_grammar_valid_and_failure_modes() -> None:
    valid_sections = [
        {
            "id": "beat-1",
            "body": (
                "| Section | Audio | Video |\n"
                "| --- | --- | --- |\n"
                "| Hook 00:00 - 00:10 | Music swells softly | Wide shot of library atrium |"
            ),
        },
        {
            "id": "beat-2",
            "body": (
                "| Section | Audio | Video |\n"
                "| --- | --- | --- |\n"
                "| Payoff 00:10 - 00:25 | VO: 14,200 learners joined | Close-up of workshop table |"
            ),
        },
    ]
    sources = {
        "cpl-stats": "Annual report confirms 14,200 learners joined workshops.",
        "perm-log": "Director memo: prior approval covers this new cut for spring launch.",
    }
    claims = [
        {
            "section": "beat-2",
            "span": "14,200 learners joined",
            "source_id": "cpl-stats",
            "quote": "14,200 learners joined",
        }
    ]
    ok_res = validate_editorial_grammar(
        "av_script",
        valid_sections,
        audio_mode="standard",
        min_seconds=20,
        max_seconds=30,
        sources=sources,
        claims=claims,
    )
    assert ok_res["ok"] is True
    assert ok_res["defects"] == []
    assert ok_res["total_duration_sec"] == 25

    broken_tc = [
        valid_sections[0],
        {
            "id": "beat-2",
            "body": (
                "| Section | Audio | Video |\n"
                "| --- | --- | --- |\n"
                "| Payoff 00:15 - 00:25 | Ambient sound | Close-up of table |"
            ),
        },
    ]
    tc_fail = validate_editorial_grammar("av_script", broken_tc)
    assert tc_fail["ok"] is False
    assert any("non-contiguous" in d for d in tc_fail["defects"])

    music_fail = validate_editorial_grammar("av_script", valid_sections, audio_mode="music_only")
    assert music_fail["ok"] is False
    assert any("music_only" in d for d in music_fail["defects"])

    carryover_sections = [
        valid_sections[0],
        {
            "id": "beat-2",
            "body": (
                "| Section | Audio | Video |\n"
                "| --- | --- | --- |\n"
                "| Payoff 00:10 - 00:20 | Ambient | Note: prior approval covers this new cut |"
            ),
        },
    ]
    carryover_fail = validate_editorial_grammar("av_script", carryover_sections)
    assert carryover_fail["ok"] is False
    assert any("carryover" in d for d in carryover_fail["defects"])

    carryover_ok = validate_editorial_grammar(
        "av_script",
        carryover_sections,
        sources=sources,
        claims=[
            {
                "type": "permission",
                "section": "beat-2",
                "span": "prior approval covers this new cut",
                "source_id": "perm-log",
                "quote": "prior approval covers this new cut",
            }
        ],
    )
    assert carryover_ok["ok"] is True

    bad_claim = [
        {
            "section": "beat-2",
            "span": "14,200 learners joined",
            "source_id": "cpl-stats",
            "quote": "99,999 learners joined",
        }
    ]
    ungrounded_fail = validate_editorial_grammar(
        "av_script", valid_sections, sources=sources, claims=bad_claim
    )
    assert ungrounded_fail["ok"] is False
    assert any("ungrounded" in d for d in ungrounded_fail["defects"])


def test_dp_story_arc_beats_greedy_and_rejects_invalid_intervals() -> None:
    segments = [
        TranscriptSegment(
            id="trap",
            start=0.0,
            end=24.0,
            text="budget community library budget community library budget community",
            arc_hint="OPEN",
        ),
        TranscriptSegment(
            id="open-1",
            start=0.0,
            end=10.0,
            text="budget opens doors for neighbors",
            arc_hint="OPEN",
        ),
        TranscriptSegment(
            id="dev-1",
            start=10.0,
            end=20.0,
            text="community workshops grow every week",
            arc_hint="DEVELOP",
        ),
        TranscriptSegment(
            id="payoff-1",
            start=20.0,
            end=30.0,
            text="library impact transforms the block",
            arc_hint="PAYOFF_CLOSE",
        ),
        TranscriptSegment(
            id="bad-neg",
            start=-2.0,
            end=4.0,
            text="invalid negative start budget community library",
            arc_hint="OPEN",
        ),
    ]
    res = select_story_arc_clips(
        segments,
        ["budget", "community", "library"],
        max_duration_sec=30.0,
    )
    selected_ids = [c["id"] for c in res["clips"]]
    assert selected_ids == ["open-1", "dev-1", "payoff-1"]
    assert [c["arc_stage"] for c in res["clips"]] == ["OPEN", "DEVELOP", "PAYOFF_CLOSE"]
    assert res["story_arc_complete"] is True
    assert res["total_duration_sec"] == 30.0
    assert "bad-neg" in res["rejected_segment_ids"]

    ok_inv, _, err_inv = validate_clip_intervals(
        [{"id": "neg", "start": -1.0, "end": 3.0}, {"id": "rev", "start": 5.0, "end": 5.0}]
    )
    assert ok_inv is False
    assert len(err_inv) == 2


def test_chg01_invalidation_and_manifest_export(tmp_path: Path) -> None:
    transcript_file = tmp_path / "transcript.json"
    transcript_data = {
        "segments": [
            {"id": "s1", "start": 0.0, "end": 8.0, "text": "Opening hook on transit access", "arc_hint": "OPEN"},
            {"id": "s2", "start": 8.0, "end": 18.0, "text": "Developing rider stories across winter", "arc_hint": "DEVELOP"},
            {"id": "s3", "start": 18.0, "end": 28.0, "text": "Closing payoff with daily ridership proof", "arc_hint": "PAYOFF_CLOSE"},
        ]
    }
    transcript_file.write_text(json.dumps(transcript_data), encoding="utf-8")

    segs, src_sha = load_transcript_segments(transcript_file)
    query_terms = ["transit", "rider", "ridership"]
    brief = "clip selection for transit arc"
    max_dur = 30.0
    selection = select_story_arc_clips(segs, query_terms, max_duration_sec=max_dur)
    chg01_sha = compute_chg01_fingerprint(src_sha, brief, query_terms, max_dur)

    out_dir = tmp_path / "export"
    exported = export_clip_manifest(selection, transcript_file, src_sha, chg01_sha, out_dir)
    manifest_path = Path(exported["manifest_path"])
    md_path = Path(exported["markdown_path"])
    assert manifest_path.is_file()
    assert md_path.is_file()

    md_text = md_path.read_text(encoding="utf-8").lower()
    manifest_text = manifest_path.read_text(encoding="utf-8").lower()
    for forbidden in ("timeline", "fcpxml", "edl", "premiere", "resolve"):
        assert forbidden not in md_text
        assert forbidden not in manifest_text

    current_check = check_chg01_invalidation(
        exported["manifest"],
        transcript_file,
        brief=brief,
        query_terms=query_terms,
        max_duration_sec=max_dur,
    )
    assert current_check["stale"] is False
    assert current_check["status"] == "CURRENT"

    raw = transcript_file.read_text(encoding="utf-8").replace("proof", "prooF")
    transcript_file.write_text(raw, encoding="utf-8")
    stale_check = check_chg01_invalidation(
        exported["manifest"],
        transcript_file,
        brief=brief,
        query_terms=query_terms,
        max_duration_sec=max_dur,
    )
    assert stale_check["stale"] is True
    assert stale_check["status"] == "STALE_NEEDS_RECHECK"
    assert "source_sha256_mismatch" in stale_check["reasons"]


def test_json_rpc_roundtrip(tmp_path: Path) -> None:
    init_resp = handle_rpc_message({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}})
    assert init_resp is not None
    assert init_resp["result"]["serverInfo"]["name"] == "story-engine"

    list_resp = handle_rpc_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    assert list_resp is not None
    names = [t["name"] for t in list_resp["result"]["tools"]]
    assert names == [t["name"] for t in TOOL_DEFINITIONS]

    rec_resp = handle_rpc_message(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "story_recognize", "arguments": {"brief": "Write a creative treatment"}},
        }
    )
    assert rec_resp is not None
    assert rec_resp["result"]["isError"] is False
    assert rec_resp["result"]["structuredContent"]["form"] == "treatment"

    transcript_txt = tmp_path / "notes.txt"
    transcript_txt.write_text("First open beat on solar energy\nSecond develop beat on grid\n", encoding="utf-8")
    sel_resp = handle_rpc_message(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {
                "name": "story_select_and_verify",
                "arguments": {
                    "transcript_path": str(transcript_txt),
                    "query_terms": ["solar", "grid"],
                    "max_duration_sec": 20.0,
                },
            },
        }
    )
    assert sel_resp is not None
    assert sel_resp["result"]["structuredContent"]["intervals_ok"] is True

    exp_resp = handle_rpc_message(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {
                "name": "story_export_and_chg01",
                "arguments": {
                    "transcript_path": str(transcript_txt),
                    "query_terms": ["solar", "grid"],
                    "max_duration_sec": 20.0,
                    "output_dir": str(tmp_path / "rpc_out"),
                },
            },
        }
    )
    assert exp_resp is not None
    sc = exp_resp["result"]["structuredContent"]
    assert sc["chg01_check"]["status"] == "CURRENT"
    assert Path(sc["manifest_path"]).is_file()

    bad_resp = handle_rpc_message(
        {"jsonrpc": "2.0", "id": 6, "method": "tools/call", "params": {"name": "missing_tool", "arguments": {}}}
    )
    assert bad_resp is not None
    assert "error" in bad_resp
