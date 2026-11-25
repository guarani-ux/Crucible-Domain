#!/usr/bin/env python3
"""Cyclical Upstream Capability Evolver (Downstream Failures -> L0-L4 Attribution -> Multi-Case Ablation -> Upstream Promotion).

Closes the upward spiral in Crucible Domain:
  1. Reads observed downstream failures (ratchet, pipeline, bench telemetry).
  2. Traces each failure up the canonical L4 -> L3 -> L2 -> L1 -> L0 Sensemaking Ontology.
  3. Synthesizes a concrete upstream capability upgrade for `.agents/bench/craft_protocols.yaml`.
  4. Runs a multi-case ablation across distinct platforms & lengths (15s IG, 30s YT, 45s LI, 60s FB, 180s YT, 300s YT).
  5. Promotes the upstream upgrade (bumping craft_protocols.yaml version + solidifying golden exemplars)
     ONLY when multi-case ablation achieves zero regressions.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from .outcome_ratchet import load_ratchet_state
from .root_axis_engine import DEFAULT_ONTOLOGY_REL
from .sensemaking_compiler import (
    DEFAULT_PROTOCOLS_REL,
    compile_and_evaluate,
    load_craft_protocols,
    synthesize_canonical_av_graph,
    validate_sensemaking_graph,
)

DEFAULT_EVOLUTION_LOG_REL = Path(".agents") / "capability_evolution_log.jsonl"
DEFAULT_EXEMPLAR_BANK_REL = Path(".agents") / "bench" / "golden_exemplars.json"

MULTI_CASE_AV_MATRIX: list[tuple[str, int, str]] = [
    ("instagram", 15, "15s Vertical Muted-First Reels Cutdown"),
    ("youtube", 30, "30s YouTube Shorts Hook"),
    ("linkedin", 45, "45s LinkedIn Civic Innovation Clip"),
    ("facebook", 60, "1-Minute Neighborhood Branch Walkthrough"),
    ("youtube", 180, "3-Minute Patron Story Mini-Doc"),
    ("youtube", 300, "5-Minute Deep-Dive Episode"),
]

L3_UPGRADE_PLAYBOOK: dict[str, str] = {
    "L3:MULTI_TRACK_STORY_ARCHITECTURE": "Enforce explicit A-story (external action), B-story (human shift), and C-story (public library truth) convergence before rendering any 60s+ script.",
    "L3:HOOK_AND_TENSION_MECHANICS": "Require an unresolved visual/curiosity hook gap in Beat 1 and explicit BUT/THEREFORE causal beat links with retention resets <=60s on long-form scripts.",
    "L3:PLATFORM_AND_AV_MEDIUM_PHYSICS": "Enforce Visual-First Subtraction (overlap <=0.35), <=150 WPM breath cadence, and mandatory muted-first kinetic captions on Instagram, LinkedIn, and Facebook.",
    "L3:POLITICAL_STEWARDSHIP_AND_AUTHORITY": "Enforce strict 2-zone separation: zero raw file paths (#L12) or internal gate codes inside stakeholder-facing prose; isolate all custody tags in Internal Custody & Sources.",
    "L3:FIELD_FEASIBILITY_AND_CUSTODY": "Require contiguous MM:SS-MM:SS runtime math within +/-15% of target duration and named accountable owners on 100% of open holds.",
    "L3:RHETORICAL_PERSUASION_AND_PSYCHOLOGY": "Model explicit Stakeholder Belief-Delta shifts (current skepticism -> target state -> concrete shift trigger) for Patron, Production, and Director/CEO lenses before drafting.",
    "L3:SOURCE_PROVENANCE_AND_EVIDENCE": "Anchor every factual claim to verified primary local sources in Internal Custody & Sources and separate observation strictly before hypothesis.",
    "L3:STRATEGIC_CHARTER_AND_TRADEOFFS": "Bind official 2027-2030 mandates organically to concrete patron service promises and opportunity-cost trade-offs without Vision 2040 KPI misuse.",
}


def attribute_failures_to_ontology(
    repo_root: Path,
    *,
    failed_probes: list[str] | None = None,
    weakest_engines: list[str] | None = None,
) -> dict[str, Any]:
    """Trace downstream failed probes & weakest engines up the canonical L4 -> L3 -> L2 -> L1 -> L0 tree."""
    ont_path = Path(repo_root) / DEFAULT_ONTOLOGY_REL
    if not ont_path.is_file():
        return {"ok": False, "error": f"Missing ontology: {ont_path}", "attributed_l3": []}
    import yaml  # type: ignore

    raw = yaml.safe_load(ont_path.read_text(encoding="utf-8", errors="replace")) or {}
    l3_by_id = {x["id"]: x for x in (raw.get("L3_sub_disciplines") or []) if isinstance(x, dict)}
    l2_by_id = {x["id"]: x for x in (raw.get("L2_engines") or []) if isinstance(x, dict)}
    l1_by_id = {x["id"]: x for x in (raw.get("L1_axes") or []) if isinstance(x, dict)}

    l3_counts: dict[str, int] = {}
    probe_set = set(failed_probes or [])
    for prim in raw.get("L4_atomic_primitives") or []:
        if not isinstance(prim, dict):
            continue
        if prim.get("probe") in probe_set:
            p3 = str(prim.get("parent_l3", ""))
            if p3:
                l3_counts[p3] = l3_counts.get(p3, 0) + 1

    # Also map weakest L2 engine names to their child L3 nodes
    eng_tokens = {e.lower() for e in (weakest_engines or []) if e}
    for l2_id, l2_obj in l2_by_id.items():
        title_low = str(l2_obj.get("title", "")).lower()
        if any(tok.replace("_", " ")[:12] in title_low or l2_id.lower() in tok for tok in eng_tokens):
            for c3 in l2_obj.get("governs_l3") or []:
                l3_counts[c3] = l3_counts.get(c3, 0) + 1

    ranked = sorted(l3_counts.items(), key=lambda kv: -kv[1])
    chains: list[dict[str, Any]] = []
    for l3_id, hits in ranked:
        l3_obj = l3_by_id.get(l3_id, {})
        l2_id = str(l3_obj.get("parent_l2", ""))
        l2_obj = l2_by_id.get(l2_id, {})
        l1_id = str(l2_obj.get("parent_l1", ""))
        l1_obj = l1_by_id.get(l1_id, {})
        chains.append(
            {
                "l3_id": l3_id,
                "l2_id": l2_id,
                "l1_id": l1_id,
                "l0_id": str(l1_obj.get("parent_l0", "L0:INSTITUTIONAL_SENSEMAKING_AND_ACTION_DESIGN")),
                "hits": hits,
                "proposed_upstream_upgrade": L3_UPGRADE_PLAYBOOK.get(l3_id, ""),
            }
        )
    return {"ok": True, "attributed_l3": chains}


def run_multi_case_ablation(
    repo_root: Path,
    *,
    form_id: str = "av_script",
    cases: list[tuple[str, int, str]] | None = None,
) -> dict[str, Any]:
    """Run deterministic multi-case evaluation across all platforms (IG/YT/LI/FB) and lengths (15s..300s)."""
    eval_cases = cases or MULTI_CASE_AV_MATRIX
    results: list[dict[str, Any]] = []
    passed_cnt = 0
    for plat, dur, topic in eval_cases:
        res = compile_and_evaluate(
            repo_root,
            form_id=form_id,
            platform=plat,
            target_duration_s=dur,
            topic=topic,
            mode="offline",
        )
        ok = bool(res.get("ok"))
        if ok:
            passed_cnt += 1
        results.append(
            {
                "platform": plat,
                "duration_s": dur,
                "topic": topic,
                "ok": ok,
                "graph_score": res.get("graph_validation", {}).get("graph_score", 0.0),
                "flow_score": res.get("flow_score", 0.0),
                "board_score": res.get("board_score", 0.0),
                "axes": res.get("axes", {}),
                "violations": res.get("graph_validation", {}).get("violations", []),
            }
        )

    # Counterfactual check: prove a broken graph (missing BUT/THEREFORE + leaked #L12) is caught upstream
    broken_graph = synthesize_canonical_av_graph(platform="instagram", target_duration_s=180, repo_root=repo_root)
    for b in broken_graph["causal_spine"]["beats"]:
        b["causal_link"] = "AND_THEN"
        b["muted_caption"] = ""
    broken_graph["causal_spine"]["beats"][0]["spoken_beat"] += " See GROUND_TRUTH.md#L12."
    broken_val = validate_sensemaking_graph(
        broken_graph, form_id="av_script", platform="instagram", target_duration_s=180, repo_root=repo_root
    )
    counterfactual_caught = (
        not broken_val.ok
        and any("missing_but_therefore" in v for v in broken_val.violations)
        and any("muted_first_captions" in v for v in broken_val.violations)
        and any("internal_jargon_leaked" in v for v in broken_val.violations)
    )

    return {
        "ok": (passed_cnt == len(eval_cases)) and counterfactual_caught,
        "cases_passed": passed_cnt,
        "cases_total": len(eval_cases),
        "counterfactual_caught": counterfactual_caught,
        "counterfactual_violations": broken_val.violations,
        "cases": results,
    }


def _bump_patch_version(ver: str) -> str:
    parts = [int(p) for p in ver.split(".") if p.isdigit()]
    while len(parts) < 3:
        parts.append(0)
    parts[2] += 1
    return ".".join(str(x) for x in parts[:3])


def evolve_form_capability(
    repo_root: Path,
    *,
    form_id: str = "av_script",
    apply_upgrade: bool = False,
) -> dict[str, Any]:
    """Trace real observed failures up L0-L4, run 6-case platform/length ablation, and optionally promote upstream."""
    t0 = time.perf_counter()
    root = Path(repo_root).resolve()

    # Gather observed failures from ratchet + telemetry
    ratchet = load_ratchet_state(root)
    weakest_engines: list[str] = []
    for fid, frec in (ratchet.get("forms") or {}).items():
        if form_id != "all" and fid != form_id:
            continue
        for eng, cnt in (frec.get("weakest_engine_counts") or {}).items():
            weakest_engines.extend([eng] * int(cnt))

    failed_probes: list[str] = []
    # Default seed probes if no live failures recorded yet for this form
    if not weakest_engines:
        failed_probes = ["narrative_tension_and_counterpoint", "physical_timing_and_wpm", "stewardship_boundary"]

    attr = attribute_failures_to_ontology(root, failed_probes=failed_probes, weakest_engines=weakest_engines)
    chains = attr.get("attributed_l3") or []
    top_chain = chains[0] if chains else None

    ablation = run_multi_case_ablation(root, form_id=form_id if form_id != "all" else "av_script")
    promoted = False
    new_version = load_craft_protocols(root).get("version", "1.0.0")
    promoted_rule = ""

    if apply_upgrade and ablation["ok"] and top_chain and top_chain.get("proposed_upstream_upgrade"):
        import yaml  # type: ignore

        prot_path = root / DEFAULT_PROTOCOLS_REL
        protocols = load_craft_protocols(root)
        f_proto = (protocols.setdefault("form_protocols", {})).setdefault(
            form_id, {"required_graph_nodes": [], "craft_principles": [], "evolved_upgrades": []}
        )
        upgrades = f_proto.setdefault("evolved_upgrades", [])
        rule = str(top_chain["proposed_upstream_upgrade"])
        if rule not in upgrades:
            upgrades.append(rule)
            new_version = _bump_patch_version(str(protocols.get("version", "1.0.0")))
            protocols["version"] = new_version
            prot_path.write_text(yaml.safe_dump(protocols, sort_keys=False, allow_unicode=True), encoding="utf-8")
            promoted = True
            promoted_rule = rule

        # Solidify golden exemplars across all 6 platform/length cases
        bank_path = root / DEFAULT_EXEMPLAR_BANK_REL
        bank: dict[str, Any] = {"version": new_version, "exemplars": []}
        for plat, dur, topic in MULTI_CASE_AV_MATRIX:
            c_res = compile_and_evaluate(root, form_id="av_script", platform=plat, target_duration_s=dur, topic=topic, mode="offline")
            if c_res["ok"]:
                bank["exemplars"].append(
                    {
                        "form_id": "av_script",
                        "platform": plat,
                        "duration_s": dur,
                        "topic": topic,
                        "flow_score": c_res["flow_score"],
                        "board_score": c_res["board_score"],
                        "axes": c_res["axes"],
                    }
                )
        bank_path.parent.mkdir(parents=True, exist_ok=True)
        bank_path.write_text(json.dumps(bank, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

        log_path = root / DEFAULT_EVOLUTION_LOG_REL
        with log_path.open("a", encoding="utf-8", newline="\n") as lf:
            lf.write(
                json.dumps(
                    {
                        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                        "form_id": form_id,
                        "new_version": new_version,
                        "promoted": promoted,
                        "l3_target": top_chain["l3_id"],
                        "rule": rule,
                        "ablation_passed": f"{ablation['cases_passed']}/{ablation['cases_total']}",
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )

    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
    return {
        "ok": ablation["ok"],
        "elapsed_ms": elapsed_ms,
        "form_id": form_id,
        "protocol_version": new_version,
        "top_attributed_chain": top_chain,
        "all_attributed_chains": chains[:5],
        "ablation": ablation,
        "promoted": promoted,
        "promoted_rule": promoted_rule,
    }
