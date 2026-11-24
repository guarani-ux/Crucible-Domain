"""YAML-Driven Crucible Workload Bench: CPL, Creative & Antigravity Proving Ground + Productive Runner."""

from __future__ import annotations

import concurrent.futures
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from collections import Counter
from dataclasses import asdict, dataclass, field, replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

import yaml

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from crucible import story_engine as se
from crucible.form_diagnostics import (
    FORM_PROFILES,
    build_escalation_challenge,
    diagnose_form_deliverable,
    resolve_form_id,
)
from crucible.indexer import build_index
from crucible.replay_loop import discover_gaps
from crucible.router import route_query

try:
    import ram_ml_engine as rml
except ImportError:
    rml = None


VALID_DOMAINS = frozenset({"cpl_sim", "cpl_research", "personal_creative", "personal_systems"})
VALID_MODES = frozenset({"plumbing", "hybrid", "agy_live"})
OFFICIAL_CPL_MANDATES_2027 = ("Collections", "Experiences", "Expertise", "Spaces", "Technology")
CPL_INTERNAL_LENSES = ("Grow", "Books & Reading", "Community")


class WorkloadSpecError(ValueError):
    """Raised when a YAML workload manifest fails validation."""

    def __init__(self, errors: list[str]) -> None:
        self.errors = errors
        super().__init__("; ".join(errors))


@dataclass
class WorkloadDefaults:
    staging_dir: str = ".agents/bench_runs"
    telemetry_file: str = ".agents/bench_telemetry.jsonl"
    ml_history_file: str = ".agents/ml_history.jsonl"
    bandit_state_file: str = ".agents/ml_bandit_state.json"
    learned_policies_file: str = ".agents/ml_learned_policies.json"
    stop_file: str = ".agents/bench.stop"
    timeout_seconds: float = 180.0
    max_retries: int = 1


@dataclass
class WorkloadProject:
    id: str
    domain: str
    mode: str
    form: str = ""
    target_audience: str = ""
    intent: str = ""
    emulates: str = ""
    deliverable: str = ""
    spokes: list[str] = field(default_factory=list)
    planted_faults: list[dict[str, Any]] = field(default_factory=list)
    public_checks: dict[str, Any] = field(default_factory=dict)
    blind_holdouts: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    use_cases: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class WorkloadManifest:
    version: str
    defaults: WorkloadDefaults
    projects: list[WorkloadProject]


@dataclass
class ProjectRunReceipt:
    timestamp: str
    run_id: str
    round_idx: int
    project_id: str
    domain: str
    mode: str
    passed: bool
    skipped: bool
    public_ok: bool
    holdout_ok: bool
    planted_caught: int
    planted_total: int
    retries_used: int
    route_ms: float
    execute_ms: float
    verify_ms: float
    total_ms: float
    deliverable_path: str = ""
    failure_category: str = ""
    error_summary: str = ""
    form_id: str = ""
    craft_arm: str = ""
    diagnostic_score: float = 0.0
    weakest_aspect: str = ""
    diagnosis: str = ""
    frontier_saturated: bool = False
    weakest_element: str = ""
    element_scores: dict[str, float] = field(default_factory=dict)
    difficulty_level: int = 1
    escalated_to: int | None = None
    use_case_id: str = ""
    skills: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _run_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def load_workload_manifest(source: Path | str | dict[str, Any]) -> WorkloadManifest:
    """Parse and validate a YAML workload manifest from file path, YAML string, or dict."""
    if isinstance(source, dict):
        raw: Any = source
    elif isinstance(source, Path):
        try:
            raw = yaml.safe_load(source.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            raise WorkloadSpecError([f"cannot parse workload YAML '{source}': {exc}"]) from exc
    elif isinstance(source, str):
        p = Path(source)
        if "\n" not in source and p.is_file():
            try:
                raw = yaml.safe_load(p.read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError) as exc:
                raise WorkloadSpecError([f"cannot parse workload YAML '{p}': {exc}"]) from exc
        else:
            try:
                raw = yaml.safe_load(source)
            except yaml.YAMLError as exc:
                raise WorkloadSpecError([f"invalid workload YAML string: {exc}"]) from exc
    else:
        raise TypeError(f"source must be Path, str, or dict, got {type(source).__name__}")

    if not isinstance(raw, dict):
        raise WorkloadSpecError(["workload manifest root must be a YAML mapping"])

    errors: list[str] = []
    version = str(raw.get("version", "1.0"))
    raw_def = raw.get("defaults") or {}
    if not isinstance(raw_def, dict):
        errors.append("'defaults' must be a mapping")
        raw_def = {}

    timeout_s = raw_def.get("timeout_seconds", 180.0)
    max_retries = raw_def.get("max_retries", 1)
    if isinstance(timeout_s, bool) or not isinstance(timeout_s, (int, float)) or float(timeout_s) <= 0:
        errors.append("defaults.timeout_seconds must be a positive number")
        timeout_s = 180.0
    if isinstance(max_retries, bool) or not isinstance(max_retries, int) or max_retries < 0:
        errors.append("defaults.max_retries must be an integer >= 0")
        max_retries = 1

    defaults = WorkloadDefaults(
        staging_dir=str(raw_def.get("staging_dir", ".agents/bench_runs")),
        telemetry_file=str(raw_def.get("telemetry_file", ".agents/bench_telemetry.jsonl")),
        ml_history_file=str(raw_def.get("ml_history_file", ".agents/ml_history.jsonl")),
        bandit_state_file=str(raw_def.get("bandit_state_file", ".agents/ml_bandit_state.json")),
        learned_policies_file=str(raw_def.get("learned_policies_file", ".agents/ml_learned_policies.json")),
        stop_file=str(raw_def.get("stop_file", ".agents/bench.stop")),
        timeout_seconds=float(timeout_s),
        max_retries=int(max_retries),
    )

    raw_projects = raw.get("projects")
    projects: list[WorkloadProject] = []
    seen_ids: set[str] = set()
    if not isinstance(raw_projects, list) or not raw_projects:
        errors.append("'projects' must be a non-empty list")
    else:
        for idx, item in enumerate(raw_projects):
            if not isinstance(item, dict):
                errors.append(f"projects[{idx}] must be a mapping")
                continue
            pid = str(item.get("id", "")).strip()
            if not pid:
                errors.append(f"projects[{idx}].id must be non-empty")
                continue
            if pid in seen_ids:
                errors.append(f"duplicate project id: '{pid}'")
            seen_ids.add(pid)

            domain = str(item.get("domain", "")).strip()
            if domain not in VALID_DOMAINS:
                errors.append(f"project '{pid}' domain '{domain}' must be one of {sorted(VALID_DOMAINS)}")

            mode = str(item.get("mode", "")).strip()
            if mode not in VALID_MODES:
                errors.append(f"project '{pid}' mode '{mode}' must be one of {sorted(VALID_MODES)}")

            deliverable = str(item.get("deliverable", "")).strip()
            if deliverable and (".." in deliverable or Path(deliverable).is_absolute()):
                errors.append(f"project '{pid}' deliverable '{deliverable}' must be a safe relative filename")

            planted = item.get("planted_faults") or []
            if not isinstance(planted, list) or not all(isinstance(x, dict) for x in planted):
                errors.append(f"project '{pid}' planted_faults must be a list of mappings")
                planted = []

            if mode == "plumbing" and not planted:
                errors.append(f"plumbing project '{pid}' must declare at least one planted_faults check")
            if mode in ("hybrid", "agy_live") and not str(item.get("intent", "")).strip():
                errors.append(f"{mode} project '{pid}' must declare a non-empty 'intent'")

            use_cases: list[dict[str, Any]] = []
            raw_ucs = item.get("use_cases") or []
            if not isinstance(raw_ucs, list):
                errors.append(f"project '{pid}' use_cases must be a list")
                raw_ucs = []
            seen_uc: set[str] = set()
            for uidx, uc_item in enumerate(raw_ucs):
                if not isinstance(uc_item, dict) or not str(uc_item.get("id", "")).strip() or not str(uc_item.get("intent", "")).strip():
                    errors.append(f"project '{pid}' use_cases[{uidx}] needs non-empty 'id' and 'intent'")
                    continue
                uc_key = str(uc_item["id"]).strip()
                if uc_key in seen_uc:
                    errors.append(f"project '{pid}' duplicate use_case id '{uc_key}'")
                seen_uc.add(uc_key)
                use_cases.append(
                    {
                        "id": uc_key,
                        "intent": str(uc_item["intent"]).strip(),
                        "target_audience": str(uc_item.get("target_audience", "")).strip(),
                        "skills": [str(s) for s in (uc_item.get("skills") or [])],
                        "tools": [str(s) for s in (uc_item.get("tools") or [])],
                    }
                )

            projects.append(
                WorkloadProject(
                    id=pid,
                    domain=domain,
                    mode=mode,
                    form=str(item.get("form", "")).strip(),
                    target_audience=str(item.get("target_audience", "")).strip(),
                    intent=str(item.get("intent", "")).strip(),
                    emulates=str(item.get("emulates", "")).strip(),
                    deliverable=deliverable or f"{pid}.md",
                    spokes=[str(s) for s in (item.get("spokes") or [])],
                    planted_faults=list(planted),
                    public_checks=dict(item.get("public_checks") or {}),
                    blind_holdouts=dict(item.get("blind_holdouts") or {}),
                    enabled=bool(item.get("enabled", True)),
                    use_cases=use_cases,
                )
            )

    if errors:
        raise WorkloadSpecError(errors)

    return WorkloadManifest(version=version, defaults=defaults, projects=projects)


def _word_count(text: str) -> int:
    return len(re.findall(r"\S+", text))


def _has_mandate_lens_confusion(text: str, terms: list[str]) -> str | None:
    """Detect if an internal editorial lens is falsely presented as an official 2027-2030 mandate."""
    for term in terms:
        esc = re.escape(term)
        pat1 = re.compile(rf"\bmandate[s]?\b[^\n.]{{0,65}}\b{esc}\b", re.IGNORECASE)
        pat2 = re.compile(rf"\b{esc}\b[^\n.]{{0,45}}\bmandate[s]?\b", re.IGNORECASE)
        for m in (*pat1.finditer(text), *pat2.finditer(text)):
            window = m.group(0).lower()
            if any(neg in window for neg in ("not a", "not an", "distinct from", "never", "lens, not", "lenses")):
                continue
            return term
    return None


def evaluate_deliverable(
    text: str,
    public_checks: dict[str, Any],
    blind_holdouts: dict[str, Any],
) -> tuple[bool, bool, str, str]:
    """Return (public_ok, holdout_ok, failure_category, error_detail) without leaking holdout internals."""
    pub_errors: list[str] = []
    words = _word_count(text)

    max_words = public_checks.get("max_words")
    if isinstance(max_words, int) and words > max_words:
        pub_errors.append(f"word count {words} exceeds max_words={max_words} (G05 cold-receiver ceiling)")

    min_words = public_checks.get("min_words")
    if isinstance(min_words, int) and words < min_words:
        pub_errors.append(f"word count {words} below min_words={min_words}")

    for sec in public_checks.get("required_sections") or []:
        if str(sec).lower() not in text.lower():
            pub_errors.append(f"missing required section: '{sec}'")

    if public_checks.get("must_cite_local_files"):
        has_path = bool(
            re.search(r"([A-Za-z0-9_./ -]+\.(?:md|py|json|yaml|ps1))", text)
        )
        if not has_path:
            pub_errors.append("deliverable must cite at least one concrete repository file path")

    if pub_errors:
        return False, True, "public_check_failed", "; ".join(pub_errors)

    # Worker-blind holdouts: never leak specific forbidden lists in failure detail
    category = str(blind_holdouts.get("failure_category", "private_holdout_violation")).strip() or "private_holdout_violation"

    if blind_holdouts.get("require_official_cpl_mandate"):
        if not any(m in text for m in OFFICIAL_CPL_MANDATES_2027):
            return True, False, category, f"WITHHELD_HOLDOUT_FAILED: {category}"

    forbid_mandate_terms = [str(t) for t in (blind_holdouts.get("forbid_terms_as_mandates") or [])]
    if forbid_mandate_terms and _has_mandate_lens_confusion(text, forbid_mandate_terms) is not None:
        return True, False, category, f"WITHHELD_HOLDOUT_FAILED: {category}"

    for phrase in blind_holdouts.get("forbid_unverified_claims") or []:
        if str(phrase).lower() in text.lower():
            return True, False, category, f"WITHHELD_HOLDOUT_FAILED: {category}"

    return True, True, "", ""


def _run_planted_fault(fault: dict[str, Any], work_dir: Path) -> tuple[bool, str]:
    """Execute one deterministic canary fault injection and return (caught, detail)."""
    kind = str(fault.get("kind", "")).strip()

    if kind == "mandate_lens_confusion":
        bad_doc = (
            "## Episode Pitch\n"
            "This episode advances Calgary Public Library's official 2027-2030 mandate: Grow.\n"
        )
        _, holdout_ok, _, _ = evaluate_deliverable(
            bad_doc,
            public_checks={},
            blind_holdouts={
                "forbid_terms_as_mandates": list(CPL_INTERNAL_LENSES),
                "failure_category": "cpl_mandate_lens_confusion",
            },
        )
        caught = holdout_ok is False
        return caught, "caught Grow-as-mandate trap" if caught else "MISSED mandate_lens_confusion"

    if kind == "unverified_release_claim":
        bad_doc = "Status: Episode cut v2 is approved for release and Asana updated.\n"
        _, holdout_ok, _, _ = evaluate_deliverable(
            bad_doc,
            public_checks={},
            blind_holdouts={
                "forbid_unverified_claims": ["approved for release", "Asana updated"],
                "failure_category": "cpl_authority_violation",
            },
        )
        caught = holdout_ok is False
        return caught, "caught unverified release/Asana claim" if caught else "MISSED unverified_release_claim"

    if kind == "cut_trim_without_captions":
        t_dir = work_dir / "chg01_canary"
        t_dir.mkdir(parents=True, exist_ok=True)
        transcript_v1 = t_dir / "pilot_a_transcript.json"
        segments_v1 = [
            {"id": "s1", "start": 0.0, "end": 12.0, "speaker": "Host", "text": "What do you read after finishing a great mystery?"},
            {"id": "s2", "start": 12.0, "end": 28.0, "speaker": "Librarian", "text": "Start with the mood and pacing you want next, not just the genre shelf."},
            {"id": "s3", "start": 28.0, "end": 42.0, "speaker": "Host", "text": "Ask a Calgary Public Library specialist for your next three picks today."},
        ]
        transcript_v1.write_text(json.dumps(segments_v1, indent=2), encoding="utf-8")
        segs, src_sha = se.load_transcript_segments(transcript_v1)
        terms = ["mystery", "librarian", "picks"]
        sel = se.select_story_arc_clips(segs, terms, max_duration_sec=45.0)
        fp = se.compute_chg01_fingerprint(src_sha, "Pilot A v1", terms, 45.0)
        exp = se.export_clip_manifest(sel, transcript_v1, src_sha, fp, t_dir)
        manifest = json.loads(Path(exp["manifest_path"]).read_text(encoding="utf-8"))

        # Simulate an 8-second trim in v2 without refreshing captions/manifest
        segments_v2 = [
            segments_v1[0],
            {"id": "s2", "start": 12.0, "end": 20.0, "speaker": "Librarian", "text": "Start with the mood you want next."},
            {"id": "s3", "start": 20.0, "end": 34.0, "speaker": "Host", "text": "Ask a Calgary Public Library specialist for your next three picks today."},
        ]
        transcript_v1.write_text(json.dumps(segments_v2, indent=2), encoding="utf-8")
        inv = se.check_chg01_invalidation(manifest, transcript_v1, "Pilot A v1", terms, 45.0)
        caught = bool(inv.get("stale") is True)
        return caught, f"CHG-01 stale={inv.get('stale')}" if caught else "MISSED CHG-01 cut trim invalidation"

    if kind == "av_timing_drift":
        recognized = se.recognize_form("Write a 60-second A/V script with visual and audio columns")
        bad_sections = [
            {"id": "hook", "body": "| 00:00 - 00:05 | Host on camera | Welcome |\n"},
            {"id": "beat-1", "body": "| 00:10 - 00:05 | Host on camera | Inverted beat timecode |\n"},
            {"id": "cta", "body": "| 00:10 - 00:15 | Card | Visit calgarylibrary.ca |\n"},
        ]
        res = se.validate_editorial_grammar(recognized["form"], bad_sections)
        caught = bool(res.get("ok") is False and res.get("defects"))
        return caught, "caught inverted A/V beat timecode" if caught else "MISSED av_timing_drift"

    return False, f"unknown planted_fault kind: '{kind}'"


def _synthesize_hybrid_deliverable(
    root: Path,
    project: WorkloadProject,
    telemetry_path: Path,
) -> str:
    """Produce a real, evidence-grounded deliverable from live repository state in 0 LLM tokens."""
    if project.domain == "cpl_research":
        gt_path = root / "Calgary Public Library" / "GROUND_TRUTH.md"
        has_gt = gt_path.is_file()
        return "\n".join(
            [
                "# BENCH_CANDIDATE (UNAPPROVED) — PITCH-YCD Episode 1 Pre-Flight & Hook Brief",
                "",
                f"> **Source Grounding:** `Calgary Public Library/GROUND_TRUTH.md` (`verified_present={has_gt}`) · **2027–2030 Mandates:** `Experiences`, `Expertise`, `Technology` (internal editorial lenses kept distinct from official mandates).",
                "",
                "## Patron Problem",
                "A Calgary resident needs to digitize aging family VHS tapes or prepare a job-ready portfolio piece without paying commercial studio rates, and assumes the Library only lends print books.",
                "",
                "## Library Resource Used",
                "On-location walkthrough with Calgary Public Library `Expertise` (staff guidance) and free public `Experiences` / `Technology` access—filmed as one continuous problem-to-solution story rather than a generic facility tour (per the 213-video audit rule separating discoverability from retention).",
                "",
                "## Immediate Patron Action",
                "Book a free library session or bring one real project item to a participating branch this week via `calgarylibrary.ca` (targeting immediate patron action rather than treating Vision 2040 as a single-video KPI).",
                "",
                "## Open Holds",
                "- `[UNKNOWN — OWNER TO CONFIRM]` Confirm exact branch location access, staff availability (`CD-01`), and `G02` production sign-off before scheduling capture.",
                "- `[UNKNOWN — OWNER TO CONFIRM]` `G06` release destination and channel scheduling remain unrecorded (`DO NOT RELEASE` until confirmed).",
                "",
            ]
        )

    # Default / personal_systems / personal_creative hybrid synthesis: live Crucible self-audit
    gap_report = discover_gaps(root, import_root=".agents/scripts")
    idx = build_index(root)
    summary = summarize_bench_telemetry(telemetry_path)
    top_rec = summary["top_recommendation"]
    gap_lines = (
        [f"- `{g.kind}` on `{g.target_path}`: {g.detail}" for g in gap_report.gaps[:3]]
        if gap_report.gaps
        else ["- `0` structural syntax, MCP, stale-SHA, or orphan-module gaps detected across `.agents/scripts`."]
    )

    return "\n".join(
        [
            f"# {project.id} — Live Crucible Telemetry & Upgrade Card",
            "",
            f"- **Indexed Capabilities:** `{len(idx.entries)}` across `.agents/scripts/crucible_gate.py` and `Personal Work/GROUND_TRUTH.md`.",
            f"- **AST Graph Scan:** `{gap_report.unit_count}` units, `{gap_report.edge_count}` static edges in `{gap_report.elapsed_ms:.1f}ms`.",
            f"- **Bench History:** `{summary['total_runs']}` recorded project runs (`pass_rate={summary['pass_rate']:.1%}`).",
            "",
            "## Observed Gaps",
            *gap_lines,
            "",
            "## Highest-Leverage Next Upgrade",
            f"- **Target:** {top_rec}",
            "- **Verification Gate:** `python .agents/scripts/crucible_gate.py bench run .agents/bench/workloads.yaml --mode offline` + `crucible_gate.py doctor`.",
            "",
        ]
    )


def _infer_project_form(project: WorkloadProject) -> str:
    if project.form:
        return resolve_form_id(project.form)
    if project.domain == "personal_creative":
        return "av_script"
    if project.domain in ("cpl_research", "personal_systems"):
        return "research_note"
    return "production_brief"


def _build_agy_worker_prompt(
    project: WorkloadProject,
    *,
    form_id: str = "",
    craft_instruction: str = "",
    prior_diagnosis: str = "",
    learned_rules: list[str] | None = None,
    escalation_challenge: str = "",
    skills: list[str] | None = None,
    tools: list[str] | None = None,
) -> str:
    """Build worker prompt with 5-element form mastery spec, learned rules, escalation, and prior diagnosis."""
    eff_form = form_id or _infer_project_form(project)
    profile = FORM_PROFILES.get(eff_form, FORM_PROFILES["production_brief"])
    audience = project.target_audience or profile.audience
    lines = [
        "Produce ONLY the requested Markdown deliverable content (no conversational preamble).",
        "Treat repository files as read-only context; do not modify workspace files or external services.",
        f"Domain: {project.domain}",
        f"Document Domain: {profile.display_name} ({eff_form})",
        f"Target Audience & Receiver: {audience}",
        "Mastery Elements for this Document Domain:",
        f"  - Style: {profile.style_spec}",
        f"  - Audience: {profile.audience_spec}",
        f"  - Purpose: {profile.purpose_spec}",
        f"  - Formatting: {profile.formatting_spec}",
        f"  - Stakeholder Connection: {profile.stakeholder_spec}",
        f"Assignment: {project.intent}",
    ]
    if skills:
        lines.append("Professional skills this use case requires: " + "; ".join(skills))
    if tools:
        lines.append("Tools/sources to ground the work in (read-only): " + "; ".join(tools))
    if craft_instruction:
        lines.append(f"Selected Craft Priority: {craft_instruction}")
    if learned_rules:
        lines.append("Accumulated Proven Craft Rules from Prior Rounds:")
        for rule in learned_rules[:3]:
            lines.append(f"  * {rule}")
    if escalation_challenge:
        lines.append(escalation_challenge)
    if prior_diagnosis:
        lines.append(f"Prior Round Weakness to Improve: {prior_diagnosis}")
    if project.public_checks:
        lines.append(f"Public acceptance checks: {json.dumps(project.public_checks, ensure_ascii=False)}")
    return "\n".join(lines) + "\n"


def _default_agy_worker(
    prompt: str,
    root: Path,
    timeout_s: float,
    *,
    effort: str = "medium",
) -> tuple[bool, str]:
    """Invoke headless `agy --print` in sandbox mode with adaptive --effort, hard timeout, and Ctrl+C kill."""
    agy_bin = shutil.which("agy") or shutil.which("agy.exe")
    if not agy_bin:
        return False, "AGY_UNAVAILABLE: 'agy' CLI not found on PATH"
    cmd = [
        agy_bin,
        "--print",
        prompt,
        "--sandbox",
        "--print-timeout",
        f"{int(max(5, round(timeout_s)))}s",
    ]
    if effort in ("low", "medium", "high"):
        cmd.extend(["--effort", effort])
    proc = subprocess.Popen(
        cmd,
        cwd=root,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout_s + 10.0)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.communicate()
        return False, f"AGY_TIMEOUT: exceeded {timeout_s}s"
    except KeyboardInterrupt:
        proc.terminate()
        try:
            proc.communicate(timeout=3.0)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.communicate()
        raise

    out = (stdout or "").strip()
    if proc.returncode != 0 or not out:
        err = (stderr or "").strip() or f"exit_code={proc.returncode}"
        return False, f"AGY_FAILED: {err[:240]}"
    return True, out


def _run_with_heartbeat(
    fn: Callable[[], tuple[bool, str]],
    progress_fn: Callable[[str], None] | None,
    label: str,
    timeout_s: float,
    interval_s: float = 10.0,
) -> tuple[bool, str]:
    """Run worker fn while emitting periodic elapsed heartbeat messages if progress_fn is set."""
    if progress_fn is None or interval_s <= 0:
        return fn()
    done = threading.Event()
    t0 = time.monotonic()

    def _beat() -> None:
        while not done.wait(interval_s):
            elapsed = int(round(time.monotonic() - t0))
            progress_fn(f"    ... {label} still waiting on agy ({elapsed}s / {int(timeout_s)}s)")

    th = threading.Thread(target=_beat, daemon=True)
    th.start()
    try:
        return fn()
    finally:
        done.set()
        th.join(timeout=0.5)


def _call_worker(
    worker: Callable[..., tuple[bool, str]],
    prompt: str,
    root: Path,
    timeout_s: float,
    effort: str,
) -> tuple[bool, str]:
    if worker is _default_agy_worker:
        return _default_agy_worker(prompt, root, timeout_s, effort=effort)
    return worker(prompt, root, timeout_s)


def _select_frontier_batch(
    root: Path,
    eligible_ids: list[str],
    count: int,
    bandit_state_path: Path,
) -> tuple[list[str], dict[str, Any]]:
    """Select up to `count` distinct unsaturated targets for parallel frontier training."""
    if not eligible_ids or rml is None:
        return eligible_ids[:count], {"all_saturated": False, "reason": "no ml engine"}
    first = rml.select_next_frontier_target(root, eligible_ids, state_path=bandit_state_path)
    frontier = list(first.get("frontier") or [])
    unsat = [e["id"] for e in frontier if not e.get("saturated")]
    primary = first.get("selected_id")
    if unsat:
        ordered = ([primary] if primary in unsat else []) + [eid for eid in unsat if eid != primary]
        chosen = ordered[: max(1, count)]
    else:
        chosen = [e["id"] for e in sorted(frontier, key=lambda x: (x["latest_score"], x["runs"]))[: max(1, count)]]
    return chosen, first


def _append_bench_telemetry(path: Path, receipt: ProjectRunReceipt) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(receipt.to_dict(), ensure_ascii=False, sort_keys=True) + "\n")


def request_bench_stop(repo_root: Path, stop_file_rel: str = ".agents/bench.stop") -> Path:
    """Create the graceful stop sentinel file for an active --until-exit bench loop."""
    p = (Path(repo_root).resolve() / stop_file_rel).resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(f"stop requested at {_utc_now_iso()}\n", encoding="utf-8", newline="\n")
    return p


def run_workload_bench(
    repo_root: Path,
    manifest: WorkloadManifest,
    *,
    mode_filter: str = "all",
    project_ids: list[str] | None = None,
    rounds: int = 1,
    interval_sec: float = 0.0,
    adaptive: bool = False,
    until_exit: bool = False,
    max_minutes: float = 0.0,
    workers: int = 1,
    progress_fn: Callable[[str], None] | None = None,
    agy_worker_fn: Callable[[str, Path, float], tuple[bool, str]] | None = None,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    """Execute YAML workloads for N rounds or --until-exit with parallel workers, --effort tiering, and ML mastery."""
    if not until_exit and rounds < 1:
        raise ValueError("rounds must be >= 1 unless until_exit=True")
    if mode_filter not in ("all", "offline", "plumbing", "hybrid", "agy_live"):
        raise ValueError(f"invalid mode_filter '{mode_filter}'")

    root = Path(repo_root).resolve()
    staging_base = (root / manifest.defaults.staging_dir).resolve()
    telemetry_path = (root / manifest.defaults.telemetry_file).resolve()
    ml_history_path = (root / manifest.defaults.ml_history_file).resolve()
    bandit_state_path = (root / manifest.defaults.bandit_state_file).resolve()
    learned_policies_path = (root / manifest.defaults.learned_policies_file).resolve()
    stop_file_path = (root / manifest.defaults.stop_file).resolve()
    worker = agy_worker_fn or _default_agy_worker
    selected_ids = set(project_ids) if project_ids else None
    max_workers = max(1, int(workers))
    state_lock = threading.Lock()

    all_receipts: list[ProjectRunReceipt] = []
    prior_diagnosis_by_proj: dict[str, str] = {}
    frontier_rotations: list[dict[str, Any]] = []
    run_id = _run_stamp() + "-" + hashlib.sha256(f"{time.time_ns()}".encode()).hexdigest()[:6]
    start_mono = time.monotonic()
    stopped_reason = "rounds_completed"
    rounds_completed = 0
    round_idx = 0

    def _safe_progress(msg: str) -> None:
        if progress_fn is not None:
            with state_lock:
                progress_fn(msg)

    try:
        while until_exit or round_idx < rounds:
            if stop_file_path.is_file():
                stopped_reason = "stop_file"
                try:
                    stop_file_path.unlink()
                except OSError:
                    pass
                break
            if max_minutes > 0.0 and round_idx > 0 and (time.monotonic() - start_mono) >= (max_minutes * 60.0):
                stopped_reason = "max_minutes"
                break

            round_idx += 1
            round_dir = staging_base / f"{run_id}_r{round_idx:02d}"
            round_dir.mkdir(parents=True, exist_ok=True)
            round_cap_index = build_index(root, global_config_dir=None)

            adaptive_target_ids: set[str] | None = None
            if adaptive and rml is not None:
                eligible_non_plumbing = [
                    p.id
                    for p in manifest.projects
                    if p.enabled
                    and (selected_ids is None or p.id in selected_ids)
                    and p.mode != "plumbing"
                    and not (mode_filter == "offline" and p.mode == "agy_live")
                    and (mode_filter not in ("hybrid", "agy_live") or p.mode == mode_filter)
                ]
                if eligible_non_plumbing:
                    chosen_list, f_choice = _select_frontier_batch(
                        root,
                        eligible_non_plumbing,
                        max_workers,
                        bandit_state_path,
                    )
                    adaptive_target_ids = set(chosen_list)
                    frontier_rotations.append(
                        {
                            "round_idx": round_idx,
                            "selected_id": chosen_list[0] if chosen_list else None,
                            "selected_ids": chosen_list,
                            "all_saturated": bool(f_choice.get("all_saturated")),
                            "reason": str(f_choice.get("reason", "")),
                        }
                    )

            def _run_one_project(proj: WorkloadProject) -> ProjectRunReceipt:
                t_total = time.perf_counter()
                t_route = time.perf_counter()
                query_str = " ".join([proj.domain, proj.form, *proj.spokes, proj.intent[:60], proj.emulates[:60]]).strip()
                _ = route_query(round_cap_index, query_str or proj.id, top_k=3)
                route_ms = round((time.perf_counter() - t_route) * 1000.0, 2)

                proj_dir = round_dir / proj.id
                proj_dir.mkdir(parents=True, exist_ok=True)

                if proj.mode == "plumbing":
                    t_exec = time.perf_counter()
                    caught = 0
                    fault_notes: list[str] = []
                    with tempfile.TemporaryDirectory(prefix="crucible_plumb_") as tmp_name:
                        tmp_dir = Path(tmp_name)
                        for fault in proj.planted_faults:
                            ok_f, note_f = _run_planted_fault(fault, tmp_dir)
                            if ok_f:
                                caught += 1
                            else:
                                fault_notes.append(note_f)
                    execute_ms = round((time.perf_counter() - t_exec) * 1000.0, 2)
                    total_faults = len(proj.planted_faults)
                    passed = caught == total_faults
                    total_ms = round((time.perf_counter() - t_total) * 1000.0, 2)
                    receipt = ProjectRunReceipt(
                        timestamp=_utc_now_iso(),
                        run_id=run_id,
                        round_idx=round_idx,
                        project_id=proj.id,
                        domain=proj.domain,
                        mode=proj.mode,
                        passed=passed,
                        skipped=False,
                        public_ok=passed,
                        holdout_ok=passed,
                        planted_caught=caught,
                        planted_total=total_faults,
                        retries_used=0,
                        route_ms=route_ms,
                        execute_ms=execute_ms,
                        verify_ms=0.0,
                        total_ms=total_ms,
                        failure_category="" if passed else "missed_planted_fault",
                        error_summary="; ".join(fault_notes),
                    )
                else:
                    form_id = _infer_project_form(proj)
                    profile = FORM_PROFILES.get(form_id, FORM_PROFILES["production_brief"])
                    context_key = f"{form_id}:{proj.domain}"
                    with state_lock:
                        arm_choice = (
                            rml.select_craft_arm(
                                root,
                                context_key,
                                profile.craft_arms,
                                state_path=bandit_state_path,
                            )
                            if rml is not None
                            else {"arm_id": profile.craft_arms[0], "instruction": ""}
                        )
                        mastery_ctx = (
                            rml.get_domain_mastery_context(root, proj.id, form_id, policy_path=learned_policies_path)
                            if rml is not None
                            else {"difficulty_level": 1, "weakest_element": "", "last_diagnosis": "", "learned_rules": []}
                        )
                        persisted_diag = prior_diagnosis_by_proj.get(proj.id) or str(mastery_ctx.get("last_diagnosis", ""))

                    arm_id = str(arm_choice.get("arm_id", profile.craft_arms[0]))
                    arm_instruction = str(arm_choice.get("instruction", ""))

                    uc: dict[str, Any] = {}
                    eff_proj = proj
                    if proj.use_cases:
                        with state_lock:
                            tgt = (
                                rml.load_learned_policies(root, learned_policies_path)["targets"].get(proj.id, {})
                                if rml is not None
                                else {}
                            )
                        runs_done = int(tgt.get("runs", round_idx - 1))
                        uc = proj.use_cases[runs_done % len(proj.use_cases)]
                        eff_proj = replace(
                            proj,
                            intent=str(uc.get("intent") or proj.intent),
                            target_audience=str(uc.get("target_audience") or proj.target_audience),
                        )
                    uc_skills = [str(s) for s in (uc.get("skills") or [])]
                    uc_tools = [str(s) for s in (uc.get("tools") or [])]
                    uc_id = str(uc.get("id", ""))
                    cur_level = int(mastery_ctx.get("difficulty_level", 1))
                    escalation_txt = build_escalation_challenge(
                        form_id,
                        str(mastery_ctx.get("weakest_element", "")),
                        cur_level,
                    )

                    _safe_progress(
                        f"  [r{round_idx}] START {proj.id} ({form_id} L{cur_level} | use_case={uc_id or '-'} | arm={arm_id} | mode={proj.mode}) ..."
                    )

                    retries_used = 0
                    max_attempts = 1 + (manifest.defaults.max_retries if proj.mode == "agy_live" else 0)
                    execute_ms = 0.0
                    verify_ms = 0.0
                    pub_ok = False
                    hold_ok = False
                    fail_cat = ""
                    err_detail = ""
                    candidate_text = ""
                    feedback_suffix = ""
                    diag_score = 0.0
                    weakest_aspect = ""
                    weakest_element = ""
                    element_scores: dict[str, float] = {}
                    diagnosis = ""
                    mastery_tip = ""
                    min_form_score = proj.public_checks.get("min_form_score")

                    for attempt in range(max_attempts):
                        if attempt > 0:
                            retries_used += 1
                            _safe_progress(f"    -> repair retry ({attempt}/{max_attempts - 1}) after '{fail_cat}'...")
                        t_exec = time.perf_counter()
                        if proj.mode == "hybrid":
                            ok_gen = True
                            candidate_text = _synthesize_hybrid_deliverable(root, proj, telemetry_path)
                        else:
                            effort = "high" if (attempt > 0 or cur_level >= 3) else ("medium" if cur_level == 2 else "low")
                            prompt = (
                                _build_agy_worker_prompt(
                                    eff_proj,
                                    form_id=form_id,
                                    craft_instruction=arm_instruction,
                                    prior_diagnosis=persisted_diag,
                                    learned_rules=list(mastery_ctx.get("learned_rules", [])),
                                    escalation_challenge=escalation_txt,
                                    skills=uc_skills,
                                    tools=uc_tools,
                                )
                                + feedback_suffix
                            )
                            ok_gen, candidate_text = _run_with_heartbeat(
                                lambda p=prompt, ef=effort: _call_worker(
                                    worker, p, root, manifest.defaults.timeout_seconds, ef
                                ),
                                _safe_progress if progress_fn is not None else None,
                                f"[r{round_idx}] {proj.id}",
                                manifest.defaults.timeout_seconds,
                            )
                        execute_ms += (time.perf_counter() - t_exec) * 1000.0

                        if not ok_gen:
                            pub_ok = False
                            hold_ok = False
                            fail_cat = "worker_execution_error"
                            err_detail = candidate_text
                            feedback_suffix = "\nPrevious attempt failed to produce output; emit valid Markdown only.\n"
                            continue

                        t_ver = time.perf_counter()
                        pub_ok, hold_ok, fail_cat, err_detail = evaluate_deliverable(
                            candidate_text,
                            proj.public_checks,
                            proj.blind_holdouts,
                        )
                        diag = diagnose_form_deliverable(
                            candidate_text,
                            form_id,
                            repo_root=root,
                            strict_cpl_mandates=proj.domain.startswith("cpl"),
                        )
                        diag_score = diag.overall_score
                        weakest_aspect = diag.weakest_aspect
                        weakest_element = diag.weakest_element
                        element_scores = dict(diag.element_scores or {})
                        diagnosis = diag.diagnosis
                        mastery_tip = diag.mastery_tip
                        if (
                            pub_ok
                            and hold_ok
                            and isinstance(min_form_score, (int, float))
                            and diag_score < float(min_form_score)
                        ):
                            pub_ok = False
                            fail_cat = "form_device_below_threshold"
                            err_detail = (
                                f"form score {diag_score:.3f} < min_form_score={float(min_form_score):.2f} ({diagnosis})"
                            )
                        verify_ms += (time.perf_counter() - t_ver) * 1000.0
                        if pub_ok and hold_ok:
                            break
                        feedback_suffix = f"\nRepair category required: {fail_cat} ({err_detail}; {diagnosis})\n"

                    passed = bool(pub_ok and hold_ok)
                    frontier_saturated = False
                    escalated_to: int | None = None
                    with state_lock:
                        if diagnosis:
                            prior_diagnosis_by_proj[proj.id] = f"weakest_element={weakest_element} ({diagnosis})"
                        if rml is not None:
                            upd = rml.update_craft_arm(
                                root,
                                context_key,
                                arm_id,
                                diag_score,
                                passed=passed,
                                target_key=proj.id,
                                state_path=bandit_state_path,
                            )
                            dr = rml.assess_diminishing_returns(upd["trajectory"])
                            frontier_saturated = bool(dr["saturated"])
                            m_upd = rml.record_domain_mastery(
                                root,
                                proj.id,
                                form_id,
                                score=diag_score,
                                passed=passed,
                                arm_id=arm_id,
                                element_scores=element_scores,
                                weakest_element=weakest_element,
                                diagnosis=diagnosis,
                                mastery_tip=mastery_tip,
                                saturated=frontier_saturated,
                                policy_path=learned_policies_path,
                                bandit_state_path=bandit_state_path,
                            )
                            escalated_to = m_upd.get("escalated_to")

                    deliv_rel = ""
                    if candidate_text and passed:
                        out_file = proj_dir / proj.deliverable
                        out_file.write_text(candidate_text, encoding="utf-8", newline="\n")
                        rel_or_abs = out_file.relative_to(root) if out_file.is_relative_to(root) else out_file
                        deliv_rel = str(rel_or_abs).replace("\\", "/")

                    total_ms = round((time.perf_counter() - t_total) * 1000.0, 2)
                    receipt = ProjectRunReceipt(
                        timestamp=_utc_now_iso(),
                        run_id=run_id,
                        round_idx=round_idx,
                        project_id=proj.id,
                        domain=proj.domain,
                        mode=proj.mode,
                        passed=passed,
                        skipped=False,
                        public_ok=pub_ok,
                        holdout_ok=hold_ok,
                        planted_caught=0,
                        planted_total=0,
                        retries_used=retries_used,
                        route_ms=route_ms,
                        execute_ms=round(execute_ms, 2),
                        verify_ms=round(verify_ms, 2),
                        total_ms=total_ms,
                        deliverable_path=deliv_rel,
                        failure_category=fail_cat,
                        error_summary=err_detail,
                        form_id=form_id,
                        craft_arm=arm_id,
                        diagnostic_score=diag_score,
                        weakest_aspect=weakest_aspect,
                        diagnosis=diagnosis,
                        frontier_saturated=frontier_saturated,
                        weakest_element=weakest_element,
                        element_scores=element_scores,
                        difficulty_level=cur_level,
                        escalated_to=escalated_to,
                        use_case_id=uc_id,
                        skills=uc_skills,
                        tools=uc_tools,
                    )

                with state_lock:
                    _append_bench_telemetry(telemetry_path, receipt)
                    if rml is not None:
                        err_sha = (
                            hashlib.sha256(receipt.failure_category.encode("utf-8")).hexdigest()[:16]
                            if not receipt.passed
                            else ""
                        )
                        rml.record_loop_outcome(
                            root,
                            slice_id=f"bench:{proj.id}",
                            target_paths=[f".agents/bench/{proj.id}"],
                            passed=receipt.passed,
                            error_sha256=err_sha,
                            seconds=receipt.total_ms / 1000.0,
                            out_path=ml_history_path,
                        )
                    all_receipts.append(receipt)

                if receipt.planted_total:
                    _safe_progress(
                        f"  [r{round_idx}] {receipt.project_id}: "
                        f"{'PASS' if receipt.passed else 'FAIL'} in {receipt.total_ms:.0f}ms [canaries {receipt.planted_caught}/{receipt.planted_total}]"
                    )
                else:
                    esc_note = f" ESC->L{receipt.escalated_to}" if receipt.escalated_to else ""
                    el = receipt.element_scores or {}
                    el_str = (
                        f"style={el.get('style', 0):.2f} aud={el.get('audience', 0):.2f} "
                        f"purp={el.get('purpose', 0):.2f} fmt={el.get('formatting', 0):.2f} "
                        f"stake={el.get('stakeholder_connection', 0):.2f}"
                    )
                    deliv_note = f" -> {receipt.deliverable_path}" if receipt.deliverable_path else ""
                    err_note = f" ({receipt.error_summary[:100]})" if (not receipt.passed and receipt.error_summary) else ""
                    _safe_progress(
                        f"  [r{round_idx}] {receipt.project_id} ({receipt.form_id} L{receipt.difficulty_level}): "
                        f"{'PASS' if receipt.passed else 'FAIL'} in {receipt.total_ms / 1000.0:.1f}s | "
                        f"score={receipt.diagnostic_score:.2f} [{el_str}] weak={receipt.weakest_element}{esc_note}{deliv_note}{err_note}"
                    )
                return receipt

            plumbing_batch: list[WorkloadProject] = []
            parallel_batch: list[WorkloadProject] = []
            for proj in manifest.projects:
                if not proj.enabled:
                    continue
                if selected_ids is not None and proj.id not in selected_ids:
                    continue
                if mode_filter == "offline" and proj.mode == "agy_live":
                    all_receipts.append(
                        ProjectRunReceipt(
                            timestamp=_utc_now_iso(),
                            run_id=run_id,
                            round_idx=round_idx,
                            project_id=proj.id,
                            domain=proj.domain,
                            mode=proj.mode,
                            passed=True,
                            skipped=True,
                            public_ok=True,
                            holdout_ok=True,
                            planted_caught=0,
                            planted_total=0,
                            retries_used=0,
                            route_ms=0.0,
                            execute_ms=0.0,
                            verify_ms=0.0,
                            total_ms=0.0,
                            error_summary="skipped in offline mode",
                        )
                    )
                    continue
                if mode_filter in ("plumbing", "hybrid", "agy_live") and proj.mode != mode_filter:
                    continue
                if adaptive and proj.mode != "plumbing" and adaptive_target_ids and proj.id not in adaptive_target_ids:
                    continue
                if proj.mode == "plumbing":
                    plumbing_batch.append(proj)
                else:
                    parallel_batch.append(proj)

            for p_item in plumbing_batch:
                _run_one_project(p_item)

            if max_workers > 1 and len(parallel_batch) > 1:
                with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as pool:
                    futures = [pool.submit(_run_one_project, item) for item in parallel_batch]
                    for fut in concurrent.futures.as_completed(futures):
                        fut.result()
            else:
                for p_item in parallel_batch:
                    _run_one_project(p_item)

            rounds_completed = round_idx
            if stopped_reason == "stop_file":
                break
            if (until_exit or round_idx < rounds) and interval_sec > 0:
                sleep_fn(interval_sec)
    except KeyboardInterrupt:
        stopped_reason = "keyboard_interrupt"

    active = [r for r in all_receipts if not r.skipped]
    all_passed = all(r.passed for r in active)
    summary = summarize_bench_telemetry(telemetry_path)
    return {
        "ok": all_passed,
        "run_id": run_id,
        "rounds_completed": rounds_completed,
        "stopped_reason": stopped_reason,
        "adaptive": adaptive,
        "until_exit": until_exit,
        "frontier_rotations": frontier_rotations,
        "executed_count": len(active),
        "passed_count": sum(1 for r in active if r.passed),
        "skipped_count": sum(1 for r in all_receipts if r.skipped),
        "deliverables": [r.deliverable_path for r in active if r.deliverable_path],
        "receipts": [r.to_dict() for r in all_receipts],
        "telemetry_summary": summary,
    }


def summarize_bench_telemetry(telemetry_path: Path | str) -> dict[str, Any]:
    """Aggregate bench_telemetry.jsonl into a plain-English scorecard and #1 bottleneck recommendation."""
    p = Path(telemetry_path)
    if not p.is_file():
        return {
            "total_runs": 0,
            "pass_rate": 1.0,
            "holdout_catch_count": 0,
            "planted_caught": 0,
            "planted_total": 0,
            "slowest_project": None,
            "slowest_ms": 0.0,
            "recent_deliverables": [],
            "failure_categories": {},
            "top_recommendation": "Run 'crucible_gate.py bench run .agents/bench/workloads.yaml --mode offline' to establish your baseline.",
        }

    rows: list[dict[str, Any]] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue

    active = [r for r in rows if not r.get("skipped")]
    if not active:
        return {
            "total_runs": 0,
            "pass_rate": 1.0,
            "holdout_catch_count": 0,
            "planted_caught": 0,
            "planted_total": 0,
            "slowest_project": None,
            "slowest_ms": 0.0,
            "recent_deliverables": [],
            "failure_categories": {},
            "top_recommendation": "No active runs recorded yet; execute bench in offline or all mode.",
        }

    passed = sum(1 for r in active if r.get("passed"))
    holdout_catches = sum(1 for r in active if r.get("public_ok") and not r.get("holdout_ok"))
    planted_caught = sum(int(r.get("planted_caught", 0)) for r in active)
    planted_total = sum(int(r.get("planted_total", 0)) for r in active)
    slowest = max(active, key=lambda r: float(r.get("total_ms", 0.0)))
    fail_counts: Counter[str] = Counter(
        str(r.get("failure_category"))
        for r in active
        if not r.get("passed") and r.get("failure_category")
    )
    deliverables = [str(r["deliverable_path"]) for r in active if r.get("deliverable_path")][-5:]
    scored_rows = [r for r in active if float(r.get("diagnostic_score", 0.0)) > 0.0]
    avg_diag = round(sum(float(r["diagnostic_score"]) for r in scored_rows) / len(scored_rows), 3) if scored_rows else 0.0
    form_scores: dict[str, list[float]] = {}
    aspect_fails: Counter[str] = Counter()
    element_fails: Counter[str] = Counter()
    uc_scores: dict[str, list[float]] = {}
    for r in scored_rows:
        fid = str(r.get("form_id") or "unknown")
        form_scores.setdefault(fid, []).append(float(r["diagnostic_score"]))
        if r.get("use_case_id"):
            uc_scores.setdefault(f"{fid}/{r['use_case_id']}", []).append(float(r["diagnostic_score"]))
        if r.get("weakest_aspect"):
            aspect_fails[str(r["weakest_aspect"])] += 1
        if r.get("weakest_element"):
            element_fails[str(r["weakest_element"])] += 1
    avg_by_form = {k: round(sum(v) / len(v), 3) for k, v in sorted(form_scores.items())}
    weakest_form = min(avg_by_form, key=lambda k: avg_by_form[k]) if avg_by_form else None

    if planted_caught < planted_total:
        top_rec = (
            f"URGENT GUARDRAIL DRIFT: {planted_total - planted_caught} planted canary fault(s) escaped detection; "
            "inspect story_engine CHG-01 and CPL mandate rules immediately."
        )
    elif fail_counts:
        worst_cat, cnt = fail_counts.most_common(1)[0]
        top_rec = (
            f"Tighten '{worst_cat}' guidance in spoke/skill prompts (triggered {cnt}x across bench runs)."
        )
    elif weakest_form and avg_by_form[weakest_form] < 0.85:
        worst_el = element_fails.most_common(1)[0][0] if element_fails else (
            aspect_fails.most_common(1)[0][0] if aspect_fails else "formatting"
        )
        top_rec = (
            f"Optimize '{weakest_form}' (avg={avg_by_form[weakest_form]:.3f}, weakest_element={worst_el}) via adaptive bandit loop."
        )
    else:
        top_rec = (
            f"All {passed}/{len(active)} runs passed (avg_form_score={avg_diag:.3f}, canaries {planted_caught}/{planted_total}); "
            f"slowest workload is '{slowest.get('project_id')}' ({float(slowest.get('total_ms', 0.0)):.1f}ms)."
        )

    return {
        "total_runs": len(active),
        "pass_rate": round(passed / len(active), 4),
        "avg_form_score": avg_diag,
        "avg_score_by_form": avg_by_form,
        "avg_score_by_use_case": {k: round(sum(v) / len(v), 3) for k, v in sorted(uc_scores.items())},
        "weakest_form": weakest_form,
        "weakest_elements": dict(element_fails),
        "holdout_catch_count": holdout_catches,
        "planted_caught": planted_caught,
        "planted_total": planted_total,
        "slowest_project": slowest.get("project_id"),
        "slowest_ms": round(float(slowest.get("total_ms", 0.0)), 2),
        "recent_deliverables": deliverables,
        "failure_categories": dict(fail_counts),
        "top_recommendation": top_rec,
    }
