#!/usr/bin/env python3
"""End-to-end RAM tests for crucible_index capability routing, bindings, and doctor checks."""

from __future__ import annotations

import json
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

import crucible_index  # noqa: E402

GATE_SCRIPT = SCRIPTS_DIR / "crucible_gate.py"
STAGED_HOOKS = REPO_ROOT / "Project" / "Inner Gravity" / "install_pack" / "crucible_hooks.json.fixed"


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

            # 2. Fixed staged hooks.json ('scripts/crucible_gate.py ...' for SessionStart, PreToolUse, Stop)
            shutil.copy2(STAGED_HOOKS, repo / ".agents" / "hooks.json")
            good_report = crucible_index.run_doctor(repo, global_config_dir=None, execute_hooks=True)
            self.assertEqual(good_report.fail_count, 0, [f.to_dict() for f in good_report.findings])
            hook_passes = [f for f in good_report.findings if f.category == "hooks" and f.severity == "PASS"]
            self.assertEqual(len(hook_passes), 3)

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

    def test_collect_observatory_snapshot_and_weakness_reporting(self) -> None:
        ig_dir = REPO_ROOT / "Project" / "Inner Gravity"
        if str(ig_dir) not in sys.path:
            sys.path.insert(0, str(ig_dir))
        import collect_observatory  # noqa: E402

        snap = collect_observatory.collect_snapshot(REPO_ROOT, session_id="4188f88a-dc0c-4bba-96bb-c69ea9c4c1ee")
        self.assertEqual(snap["crucible_domain"]["doctor_summary"]["fail"], 0)
        self.assertTrue(snap["session_telemetry"]["present"])
        weakness_ids = {w["id"] for w in snap["known_weaknesses"]}
        self.assertIn("GAP-HV4-NO-TESTS", weakness_ids)


if __name__ == "__main__":
    unittest.main()
