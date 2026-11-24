#!/usr/bin/env python3
"""End-to-end RAM tests for crucible_index capability routing, bindings, and doctor checks."""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import crucible_gate  # noqa: E402
import crucible_index  # noqa: E402

GATE_SCRIPT = SCRIPTS_DIR / "crucible_gate.py"
LIVE_HOOKS = REPO_ROOT / ".agents" / "hooks.json"


class TestCrucibleIndexAndDoctor(unittest.TestCase):
    """Verify fast in-RAM indexing, ChatGPT skill bindings, abstention, and hook health checks."""

    def test_index_discovers_full_live_estate_fast(self) -> None:
        idx = crucible_index.build_index(REPO_ROOT, global_config_dir=None)
        self.assertLess(idx.build_ms, 1000.0)
        self.assertGreaterEqual(idx.counts_by_kind.get("procedure", 0), 55)
        self.assertEqual(idx.counts_by_kind.get("role", 0), 12)
        self.assertGreaterEqual(idx.counts_by_kind.get("knowledge", 0), 9)
        self.assertGreaterEqual(idx.counts_by_kind.get("project", 0), 6)
        self.assertEqual(idx.counts_by_kind.get("exhibit", 0), 10)
        self.assertIn("ig-reconcile", idx.entries)

    def test_all_ten_chatgpt_skill_bindings_resolve_locally(self) -> None:
        idx = crucible_index.build_index(REPO_ROOT, global_config_dir=crucible_index.DEFAULT_GLOBAL_CONFIG_DIR)
        self.assertEqual(len(idx.chatgpt_bindings), 10)
        for sid, status in idx.chatgpt_bindings.items():
            self.assertTrue(
                status.ok,
                f"ChatGPT binding {sid} ({status.label}) has missing targets: {status.missing_targets}",
            )
            res = crucible_index.route_query(idx, sid)
            self.assertEqual(res.match_mode, "chatgpt_binding")
            self.assertFalse(res.abstained)
            self.assertGreaterEqual(len(res.matches), 1)

        url_res = crucible_index.route_query(
            idx, "https://chatgpt.com/skills?skill_id=6a8875c54d3c81919a7f6de589f82d02"
        )
        self.assertEqual(url_res.match_mode, "chatgpt_binding")
        self.assertIn("MW-04", [m.entry.id for m in url_res.matches])

    def test_route_exact_lexical_and_selective_abstention(self) -> None:
        idx = crucible_index.build_index(REPO_ROOT, global_config_dir=None)

        exact_mw = crucible_index.route_query(idx, "MW-04")
        self.assertEqual(exact_mw.match_mode, "exact")
        self.assertEqual(exact_mw.matches[0].entry.id, "MW-04")
        self.assertTrue(exact_mw.matches[0].entry.path.endswith("media-writing.md"))

        exact_role = crucible_index.route_query(idx, "prod-s")
        self.assertEqual(exact_role.match_mode, "exact")
        self.assertEqual(exact_role.matches[0].entry.id, "PROD-S")

        lex = crucible_index.route_query(idx, "write an audiovisual script for school video")
        self.assertEqual(lex.match_mode, "lexical")
        self.assertFalse(lex.abstained)
        self.assertIn("MW-04", [m.entry.id for m in lex.matches])

        abstain = crucible_index.route_query(idx, "quantum espresso banana smoothie recipe")
        self.assertTrue(abstain.abstained)
        self.assertEqual(abstain.match_mode, "abstained")
        self.assertEqual(abstain.matches, [])

    def test_doctor_catches_broken_cwd_hook_and_passes_staged_fix(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            agents_dir = repo / ".agents" / "scripts"
            agents_dir.mkdir(parents=True)
            shutil.copy2(SCRIPTS_DIR / "crucible_gate.py", agents_dir / "crucible_gate.py")
            shutil.copy2(SCRIPTS_DIR / "crucible_index.py", agents_dir / "crucible_index.py")
            shutil.copytree(
                SCRIPTS_DIR / "crucible",
                agents_dir / "crucible",
                ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
            )
            (repo / "IDEAS.md").write_text("# Ledger\n\n## Stage 4: Active (WIP <= 1)\n(empty)\n", encoding="utf-8")

            # 1. Broken cwd path ('.agents/scripts/...' evaluated inside '.agents/')
            broken_hooks = {
                "crucible-domain-map": {
                    "enabled": True,
                    "SessionStart": [{"type": "command", "command": "python .agents/scripts/crucible_gate.py session-start"}],
                }
            }
            (repo / ".agents" / "hooks.json").write_text(json.dumps(broken_hooks), encoding="utf-8")
            bad_report = crucible_index.run_doctor(repo, global_config_dir=None, execute_hooks=True)
            self.assertFalse(bad_report.ok)
            self.assertGreaterEqual(bad_report.fail_count, 1)
            hook_fails = [f for f in bad_report.findings if f.category == "hooks" and f.severity == "FAIL"]
            self.assertTrue(hook_fails)

            # 2. Live hooks.json ('scripts/crucible_gate.py ...' for SessionStart and PreToolUse)
            shutil.copy2(LIVE_HOOKS, repo / ".agents" / "hooks.json")
            good_report = crucible_index.run_doctor(repo, global_config_dir=None, execute_hooks=True)
            self.assertEqual(good_report.fail_count, 0, [f.to_dict() for f in good_report.findings])
            hook_passes = [f for f in good_report.findings if f.category == "hooks" and f.severity == "PASS"]
            self.assertEqual(len(hook_passes), 2)

    def test_doctor_detects_diverged_media_agency_copy(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            (repo / "Knowledge" / "Media Agency").mkdir(parents=True)
            (repo / "Project" / "Media Agency").mkdir(parents=True)
            (repo / "Knowledge" / "Media Agency" / "PROD-S.md").write_text("# PROD-S canonical\n", encoding="utf-8")
            (repo / "Project" / "Media Agency" / "PROD-S.md").write_text("# PROD-S stale\n", encoding="utf-8")
            report = crucible_index.run_doctor(repo, global_config_dir=None, execute_hooks=False)
            self.assertEqual(report.metrics.get("media_agency_diverged"), 1)
            dup_warns = [f for f in report.findings if f.category == "duplicates" and f.severity == "WARN"]
            self.assertEqual(len(dup_warns), 1)

    def test_live_workspace_bindings_and_local_entry_links(self) -> None:
        report = crucible_index.run_doctor(
            REPO_ROOT,
            global_config_dir=crucible_index.DEFAULT_GLOBAL_CONFIG_DIR,
            execute_hooks=False,
        )
        self.assertEqual(report.metrics.get("chatgpt_unbound"), 0)
        self.assertGreaterEqual(report.metrics.get("chatgpt_bound", 0), 10)
        self.assertEqual(report.metrics.get("media_agency_diverged", 0), 0)

        link_fails = [f for f in report.findings if f.category == "links" and f.severity == "FAIL"]
        self.assertEqual(link_fails, [], f"Broken local entry links found: {link_fails}")

        # Live workspace hooks are now patched and verified green.
        hook_fails = [f for f in report.findings if f.category == "hooks" and f.severity == "FAIL"]
        self.assertEqual(hook_fails, [], f"Live hook failures detected: {hook_fails}")
        self.assertEqual(report.fail_count, 0)

    def test_cli_route_and_doctor_subcommands(self) -> None:
        proc_route = subprocess.run(
            [sys.executable, str(GATE_SCRIPT), "--root", str(REPO_ROOT), "route", "--json", "--no-global", "MW-04"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(proc_route.returncode, 0, proc_route.stderr)
        payload = json.loads(proc_route.stdout)
        self.assertEqual(payload["match_mode"], "exact")
        self.assertEqual(payload["matches"][0]["id"], "MW-04")

        proc_doc = subprocess.run(
            [sys.executable, str(GATE_SCRIPT), "--root", str(REPO_ROOT), "doctor", "--json", "--no-global", "--skip-exec"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(proc_doc.returncode, 0, proc_doc.stdout + proc_doc.stderr)
        doc_json = json.loads(proc_doc.stdout)
        self.assertIn("summary", doc_json)
        self.assertEqual(doc_json["metrics"]["chatgpt_unbound"], 0)

    def test_shifting_sand_pre_tool_denies_deliverable_in_empty_domain_and_allows_ground_truth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            (repo / "Personal Work").mkdir(parents=True)
            (repo / "IDEAS.md").write_text("# Ledger\n", encoding="utf-8")

            deny_payload = {
                "toolCall": {
                    "name": "write_file",
                    "args": {"Path": str(repo / "Personal Work" / "deliverable.md"), "Content": "# Draft\n"},
                }
            }
            deny_proc = subprocess.run(
                [sys.executable, str(GATE_SCRIPT), "--root", str(repo), "pre-tool"],
                cwd=repo,
                input=json.dumps(deny_payload),
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(deny_proc.returncode, 0)
            self.assertEqual(json.loads(deny_proc.stdout)["decision"], "deny")

            allow_payload = {
                "toolCall": {
                    "name": "write_file",
                    "args": {"Path": str(repo / "Personal Work" / "GROUND_TRUTH.md"), "Content": "# Ground Truth\n"},
                }
            }
            allow_proc = subprocess.run(
                [sys.executable, str(GATE_SCRIPT), "--root", str(repo), "pre-tool"],
                cwd=repo,
                input=json.dumps(allow_payload),
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(allow_proc.returncode, 0)
            self.assertEqual(json.loads(allow_proc.stdout)["decision"], "allow")


    def test_exhibits_parse_mechanisms_breakpoints_and_transfers(self) -> None:
        idx = crucible_index.build_index(REPO_ROOT, global_config_dir=None)
        exhibits = [e for e in idx.entries.values() if e.kind == "exhibit"]
        self.assertEqual(len(exhibits), 10)
        for ex in exhibits:
            self.assertTrue(ex.mechanisms.strip(), f"{ex.id} missing mechanisms")
            self.assertTrue(ex.breakpoints.strip(), f"{ex.id} missing breakpoints")
            self.assertTrue(ex.transfers.strip(), f"{ex.id} missing transfers")








    def test_primitives_registry_indexes_routes_and_validates_negative_schema(self) -> None:
        idx = crucible_index.build_index(REPO_ROOT, global_config_dir=None)
        primitives = [e for e in idx.entries.values() if e.kind == "primitive"]
        self.assertGreaterEqual(len(primitives), 12)

        routed = crucible_index.route_query(idx, "PRIM-02")
        self.assertFalse(routed.abstained)
        self.assertEqual(routed.match_mode, "exact")
        self.assertEqual(routed.matches[0].entry.id, "PRIM-02")

        findings: list[crucible_index.DiagnosticFinding] = []
        count = crucible_index.validate_primitives_registry(REPO_ROOT, findings)
        self.assertGreaterEqual(count, 12)
        self.assertTrue(any(f.category == "primitives" and f.severity == "PASS" for f in findings))

        with tempfile.TemporaryDirectory() as tmp:
            bad_root = Path(tmp)
            (bad_root / "Knowledge").mkdir()
            (bad_root / "Knowledge" / "Crucible_Primitives.json").write_text(
                json.dumps(
                    {
                        "families": ["intake-grounding"],
                        "primitives": [
                            {
                                "id": "PRIM-99",
                                "name": "Broken",
                                "family": "unknown-family",
                                "status": "INVALID_STATUS",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )
            bad_findings: list[crucible_index.DiagnosticFinding] = []
            crucible_index.validate_primitives_registry(bad_root, bad_findings)
            self.assertTrue(any(f.category == "primitives" and f.severity == "FAIL" for f in bad_findings))






    def test_graphs_and_pilot_docs_route_by_id_and_lexical(self) -> None:
        idx = crucible_index.build_index(REPO_ROOT, global_config_dir=None)

        atlas_exact = crucible_index.route_query(idx, "CRUCIBLE-ATLAS")
        self.assertFalse(atlas_exact.abstained)
        self.assertEqual(atlas_exact.match_mode, "exact")
        self.assertEqual(atlas_exact.matches[0].entry.id, "CRUCIBLE-ATLAS")
        self.assertEqual(atlas_exact.matches[0].entry.path, "Graphs/00_System_Atlas_and_Neon_Handoff.md")

        atlas_lex = crucible_index.route_query(idx, "system atlas")
        self.assertFalse(atlas_lex.abstained)
        self.assertEqual(atlas_lex.match_mode, "lexical")
        self.assertEqual(atlas_lex.matches[0].entry.path, "Graphs/00_System_Atlas_and_Neon_Handoff.md")

        audit_exact = crucible_index.route_query(idx, "CRUCIBLE-AUDIT")
        self.assertFalse(audit_exact.abstained)
        self.assertEqual(audit_exact.matches[0].entry.path, "Graphs/02_Coupling_and_Reachability_Audit.md")

        obs_exact = crucible_index.route_query(idx, "IG-OBS")
        self.assertFalse(obs_exact.abstained)
        self.assertEqual(
            obs_exact.matches[0].entry.path,
            "Project/Inner Gravity/05_Session_4188f88a_Causal_Trace_and_Gaps.md",
        )

        pilot_exact = crucible_index.route_query(idx, "CPL-PILOT-MAPS")
        self.assertFalse(pilot_exact.abstained)
        self.assertEqual(pilot_exact.match_mode, "exact")
        self.assertTrue(pilot_exact.matches[0].entry.path.endswith("cpl_pilot_maps.md"))

    def test_doctor_portability_info_and_graphs_broken_link_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "repo"
            (repo / "Graphs").mkdir(parents=True)
            (repo / "Graphs" / "00_System_Atlas_and_Neon_Handoff.md").write_text("# Atlas\n", encoding="utf-8")
            (repo / "Graphs" / "GROUND_TRUTH.md").write_text(
                "# Ground Truth\nSee [Atlas](./00_System_Atlas_and_Neon_Handoff.md).\n",
                encoding="utf-8",
            )
            missing_global = tmp_path / "absent_global_config"

            report = crucible_index.run_doctor(repo, global_config_dir=missing_global, execute_hooks=False)
            self.assertTrue(report.ok, [f.to_dict() for f in report.findings])
            self.assertEqual(report.fail_count, 0)
            info_findings = [
                f for f in report.findings if f.category == "portability" and f.severity == "INFO"
            ]
            self.assertEqual(len(info_findings), 1)
            self.assertEqual(info_findings[0].subject, str(missing_global))
            self.assertIn("global config dir absent", info_findings[0].detail)
            self.assertEqual(
                report.warn_count,
                sum(1 for f in report.findings if f.severity == "WARN"),
            )
            self.assertEqual(
                report.pass_count,
                sum(1 for f in report.findings if f.severity == "PASS"),
            )
            rendered = crucible_index._format_doctor_text(report)
            self.assertIn("[INFO] portability", rendered)

            # Negative path: broken relative Markdown link inside Graphs/GROUND_TRUTH.md must FAIL.
            (repo / "Graphs" / "GROUND_TRUTH.md").write_text(
                "# Ground Truth\nBroken [Missing Target](./missing_target.md).\n",
                encoding="utf-8",
            )
            bad_report = crucible_index.run_doctor(repo, global_config_dir=missing_global, execute_hooks=False)
            self.assertFalse(bad_report.ok)
            self.assertGreaterEqual(bad_report.fail_count, 1)
            link_fails = [
                f
                for f in bad_report.findings
                if f.category == "links" and f.severity == "FAIL" and f.subject == "Graphs/GROUND_TRUTH.md"
            ]
            self.assertEqual(len(link_fails), 1)
            self.assertIn("missing_target.md", link_fails[0].detail)

    def test_bm25_graph_walk_and_structural_filtering(self) -> None:
        from crucible.models import CapabilityEntry, CapabilityIndex

        e_a = CapabilityEntry(
            id="CAP-A",
            kind="procedure",
            title="Alpha Calibration",
            path="a.md",
            line=1,
            domain="personal",
            reachability="local",
            use_when="calibrate alpha",
            summary="Primary entry",
            related_ids=("CAP-B",),
        )
        e_b = CapabilityEntry(
            id="CAP-B",
            kind="knowledge",
            title="Beta Reference",
            path="b.md",
            line=1,
            domain="cpl",
            reachability="local",
            use_when="reference",
            summary="Linked 1-hop",
            related_ids=("CAP-C", "CAP-A"),
        )
        e_c = CapabilityEntry(
            id="CAP-C",
            kind="skill",
            title="Gamma Tool",
            path="c.md",
            line=1,
            domain="cpl",
            reachability="local",
            use_when="tool",
            summary="Linked 2-hop",
            related_ids=("CAP-A",),
        )
        idx = CapabilityIndex(
            root=REPO_ROOT,
            entries={"CAP-A": e_a, "CAP-B": e_b, "CAP-C": e_c},
            alias_map={"cap-a": "CAP-A", "cap-b": "CAP-B", "cap-c": "CAP-C"},
            chatgpt_bindings={},
            skill_frontmatter_bytes={},
            build_ms=0.1,
        )

        # 2-hop graph walk reaches CAP-B and CAP-C despite cyclic CAP-A <-> CAP-B <-> CAP-C
        res_2hop = crucible_index.route_query(idx, "alpha calibration", max_hops=2, graph_decay=0.5)
        self.assertFalse(res_2hop.abstained)
        ids_2hop = [m.entry.id for m in res_2hop.matches]
        self.assertEqual(ids_2hop[0], "CAP-A")
        self.assertIn("CAP-B", ids_2hop)
        self.assertIn("CAP-C", ids_2hop)
        via_c = next(m.matched_via for m in res_2hop.matches if m.entry.id == "CAP-C")
        self.assertEqual(via_c, "graph_walk:2hop_from:CAP-A")

        # Structural filter by domain="cpl" and kind="skill" isolates CAP-C
        res_filtered = crucible_index.route_query(
            idx, "alpha calibration", max_hops=2, domain="cpl", kind="skill"
        )
        self.assertFalse(res_filtered.abstained)
        self.assertEqual([m.entry.id for m in res_filtered.matches], ["CAP-C"])

        # Negative control: non-matching domain abstains
        res_empty = crucible_index.route_query(idx, "alpha calibration", domain="nonexistent")
        self.assertTrue(res_empty.abstained)
        self.assertEqual(res_empty.match_mode, "abstained")

    def test_format_route_text_truncates_summary_and_rejects_tiny_limit(self) -> None:
        from crucible.models import CapabilityEntry, RouteMatch, RouteResult

        long_summary = "Alpha summary detail " * 6
        entry = CapabilityEntry(
            id="CAP-TRIM",
            kind="procedure",
            title="Trim Test",
            path="trim.md",
            line=1,
            domain="personal",
            reachability="local",
            use_when="trim summary",
            summary=long_summary,
        )
        result = RouteResult(
            query="trim",
            match_mode="exact_id",
            abstained=False,
            reason="Exact match.",
            matches=[RouteMatch(entry=entry, score=10.0, matched_via="exact_id")],
        )

        formatted = crucible_index._format_route_text(result, max_summary_chars=40)
        note_lines = [line for line in formatted.splitlines() if line.startswith("   Note: ")]
        self.assertEqual(len(note_lines), 1)
        note_payload = note_lines[0][len("   Note: "):]
        self.assertLessEqual(len(note_payload), 40)
        self.assertTrue(note_payload.endswith("..."))
        self.assertEqual(note_payload, f"{long_summary[:37].rstrip()}...")

        with self.assertRaises(ValueError):
            crucible_index._format_route_text(result, max_summary_chars=5)


if __name__ == "__main__":
    unittest.main()
