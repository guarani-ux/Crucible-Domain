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

    def test_collect_observatory_snapshot_and_weakness_reporting(self) -> None:
        ig_dir = REPO_ROOT / "Project" / "Inner Gravity"
        if str(ig_dir) not in sys.path:
            sys.path.insert(0, str(ig_dir))
        import collect_observatory  # noqa: E402

        with tempfile.TemporaryDirectory() as tmp:
            gemini_dir = Path(tmp) / ".gemini"
            cfg_dir = gemini_dir / "config"
            (cfg_dir / "scripts").mkdir(parents=True)
            (cfg_dir / "scripts" / "hook_v4.py").write_text("# stub\n", encoding="utf-8")
            (cfg_dir / "hooks.json").write_text('{"h": {"enabled": false}}', encoding="utf-8")
            (cfg_dir / "hooks.json.portable").write_text('{"h": {"enabled": true}}', encoding="utf-8")

            brain = gemini_dir / "antigravity" / "brain" / "synthetic-session-001"
            (brain / "inner-gravity-observations").mkdir(parents=True)
            (brain / ".system_generated" / "logs").mkdir(parents=True)
            (brain / "reliability-events.jsonl").write_text(
                '{"stepIdx": 1, "tool": "read_file", "failed": false}\n', encoding="utf-8"
            )
            (brain / "inner-gravity-observations" / "r1.json").write_text(
                '{"event": "stop", "model": "test-model"}\n', encoding="utf-8"
            )
            (brain / ".system_generated" / "logs" / "transcript.jsonl").write_text(
                '{"type": "USER_INPUT"}\n', encoding="utf-8"
            )

            snap = collect_observatory.collect_snapshot(
                REPO_ROOT,
                gemini_dir=gemini_dir,
                session_id="synthetic-session-001",
            )
            self.assertEqual(snap["crucible_domain"]["doctor_summary"]["fail"], 0)
            self.assertTrue(snap["session_telemetry"]["present"])
            self.assertEqual(snap["session_telemetry"]["reliability_events_total"], 1)
            weakness_ids = {w["id"] for w in snap["known_weaknesses"]}
            self.assertEqual(snap["antigravity_host"]["hook_v4_test_count"], 0)
            self.assertIn("GAP-HV4-NO-TESTS", weakness_ids)
            self.assertIn("GAP-HOOKS-PORTABILITY", weakness_ids)

            tests_dir = cfg_dir / "scripts" / "tests"
            tests_dir.mkdir(parents=True)
            hv4_test_file = tests_dir / "test_hook_v4.py"
            hv4_test_file.write_text(
                "\n".join(f"def test_case_{i}():\n    assert 1 + {i} != 99\n" for i in range(2)),
                encoding="utf-8",
            )
            snap_thin = collect_observatory.collect_snapshot(
                REPO_ROOT,
                gemini_dir=gemini_dir,
                session_id="synthetic-session-001",
            )
            thin_ids = {w["id"] for w in snap_thin["known_weaknesses"]}
            self.assertEqual(snap_thin["antigravity_host"]["hook_v4_test_count"], 2)
            self.assertNotIn("GAP-HV4-NO-TESTS", thin_ids)
            self.assertIn("GAP-HV4-THIN-TESTS", thin_ids)

            hv4_test_file.write_text(
                "\n".join(f"def test_case_{i}():\n    assert 1 + {i} != 99\n" for i in range(10)),
                encoding="utf-8",
            )
            snap_deep = collect_observatory.collect_snapshot(
                REPO_ROOT,
                gemini_dir=gemini_dir,
                session_id="synthetic-session-001",
            )
            deep_ids = {w["id"] for w in snap_deep["known_weaknesses"]}
            self.assertEqual(snap_deep["antigravity_host"]["hook_v4_test_count"], 10)
            self.assertNotIn("GAP-HV4-NO-TESTS", deep_ids)
            self.assertNotIn("GAP-HV4-THIN-TESTS", deep_ids)

    def test_exhibits_parse_mechanisms_breakpoints_and_transfers(self) -> None:
        idx = crucible_index.build_index(REPO_ROOT, global_config_dir=None)
        exhibits = [e for e in idx.entries.values() if e.kind == "exhibit"]
        self.assertEqual(len(exhibits), 10)
        for ex in exhibits:
            self.assertTrue(ex.mechanisms.strip(), f"{ex.id} missing mechanisms")
            self.assertTrue(ex.breakpoints.strip(), f"{ex.id} missing breakpoints")
            self.assertTrue(ex.transfers.strip(), f"{ex.id} missing transfers")

    def test_forge_brief_surfaces_checkpoint_prior_art_and_k_arch_01(self) -> None:
        idx = crucible_index.build_index(REPO_ROOT, global_config_dir=None)
        brief = crucible_index.forge_brief(idx, "build a resilient sqlite checkpoint resume engine for failed steps")
        self.assertFalse(brief.abstained)
        exhibit_ids = {p["id"] for p in brief.prior_systems}
        lesson_ids = {k["id"] for k in brief.governing_lessons}
        self.assertIn("A09", exhibit_ids)
        self.assertIn("K-ARCH-01", lesson_ids)
        self.assertTrue(any("[K-ARCH-01 / A09]" in r for r in brief.verification_requirements))

    def test_forge_brief_surfaces_retrieval_sidecar_and_k_arch_02(self) -> None:
        idx = crucible_index.build_index(REPO_ROOT, global_config_dir=None)
        brief = crucible_index.forge_brief(idx, "build a knowledge retrieval sidecar for prior lessons and schema replay")
        self.assertFalse(brief.abstained)
        exhibit_ids = {p["id"] for p in brief.prior_systems}
        lesson_ids = {k["id"] for k in brief.governing_lessons}
        self.assertIn("A06", exhibit_ids)
        self.assertIn("K-ARCH-02", lesson_ids)
        self.assertIn("K-SIDECAR-01", lesson_ids)
        self.assertTrue(any("[K-ARCH-02 / A04 / A06]" in r for r in brief.verification_requirements))

    def test_forge_brief_abstains_on_noise_while_keeping_tq_floor(self) -> None:
        idx = crucible_index.build_index(REPO_ROOT, global_config_dir=None)
        brief = crucible_index.forge_brief(idx, "quantum espresso banana smoothie recipe")
        self.assertTrue(brief.abstained)
        self.assertEqual(brief.existing_projects, [])
        self.assertEqual(brief.prior_systems, [])
        self.assertEqual(brief.governing_lessons, [])
        self.assertEqual(brief.procedures_and_roles, [])
        self.assertTrue(any("[TQ-01..TQ-05]" in r for r in brief.verification_requirements))

    def test_cli_forge_subcommand_json_and_missing_arg_rejection(self) -> None:
        proc_ok = subprocess.run(
            [
                sys.executable,
                str(GATE_SCRIPT),
                "--root",
                str(REPO_ROOT),
                "forge",
                "--json",
                "--no-global",
                "checkpoint resume workflow",
            ],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(proc_ok.returncode, 0, proc_ok.stderr)
        data = json.loads(proc_ok.stdout)
        self.assertIn("prior_systems", data)
        self.assertIn("governing_lessons", data)
        self.assertIn("verification_requirements", data)

        proc_missing = subprocess.run(
            [sys.executable, str(GATE_SCRIPT), "--root", str(REPO_ROOT), "forge"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(proc_missing.returncode, 2)

    def test_compute_melt_diff_classifies_melted_stale_hub_unmelted_and_stubs(self) -> None:
        synthetic_repos = [
            {
                "name": "Kageyoni",
                "pushedAt": "2026-10-28T12:00:00Z",
                "diskUsage": 17326,
                "isPrivate": True,
                "isArchived": False,
                "primaryLanguage": {"name": "Python"},
                "description": "Prior system",
            },
            {
                "name": "sidecar",
                "pushedAt": "2026-11-23T08:00:00Z",
                "diskUsage": 122,
                "isPrivate": True,
                "isArchived": False,
                "primaryLanguage": {"name": "Python"},
                "description": "Updated after exhibit date",
            },
            {
                "name": "Crucible-Domain",
                "pushedAt": "2026-11-23T09:00:00Z",
                "diskUsage": 339,
                "isPrivate": True,
                "isArchived": False,
                "primaryLanguage": {"name": "Python"},
                "description": "Hub repo",
            },
            {
                "name": "mercury",
                "pushedAt": "2026-11-23T07:00:00Z",
                "diskUsage": 112,
                "isPrivate": True,
                "isArchived": False,
                "primaryLanguage": {"name": "Python"},
                "description": "Modular Preview/Program Engine",
            },
            {
                "name": "Story-House",
                "pushedAt": "2026-11-09T07:00:00Z",
                "diskUsage": 1612,
                "isPrivate": True,
                "isArchived": False,
                "primaryLanguage": {"name": "Python"},
                "description": "",
            },
            {
                "name": "Dangai",
                "pushedAt": "2026-04-14T07:00:00Z",
                "diskUsage": 0,
                "isPrivate": True,
                "isArchived": False,
                "primaryLanguage": None,
                "description": "",
            },
        ]
        diff = crucible_index.compute_melt_diff(REPO_ROOT, synthetic_repos)
        self.assertEqual(diff["exhibit_baseline_date"], "2026-11-15")
        self.assertEqual(diff["counts"]["melted"], 1)
        self.assertEqual(diff["counts"]["stale_melted"], 1)
        self.assertEqual(diff["counts"]["active_hub"], 1)
        self.assertEqual(diff["counts"]["unmelted"], 2)
        self.assertEqual(diff["counts"]["skip_stub"], 1)
        self.assertEqual(diff["stale_melted"][0]["exhibit_id"], "A06")
        unmelted_by_name = {r["name"]: r for r in diff["unmelted"]}
        self.assertFalse(unmelted_by_name["mercury"]["in_project_register"])
        self.assertTrue(unmelted_by_name["Story-House"]["in_project_register"])

    def test_run_melt_scan_enforces_batch_cap_and_filters_binaries_and_empty_repos(self) -> None:
        with self.assertRaises(ValueError):
            crucible_index.run_melt_scan([])
        with self.assertRaises(ValueError):
            crucible_index.run_melt_scan(["r1", "r2", "r3", "r4", "r5", "r6"])

        fixtures = {
            "mercury": {
                "tree_payload": {
                    "truncated": False,
                    "tree": [
                        {"type": "blob", "path": "pyproject.toml"},
                        {"type": "blob", "path": "src/main.py"},
                        {"type": "blob", "path": "src/engine.py"},
                        {"type": "blob", "path": "tests/test_engine.py"},
                        {"type": "blob", "path": "node_modules/pkg/index.js"},
                        {"type": "blob", "path": "assets/demo.mp4"},
                    ],
                },
                "readme_text": "# Mercury\n\n" + ("Modular writing desk and preview engine. " * 30),
            },
            "Dangai": {
                "tree_payload": {"error_status": 409, "empty_repo": True},
                "readme_text": "",
            },
            "media-dump": {
                "tree_payload": {
                    "truncated": False,
                    "tree": [
                        {"type": "blob", "path": "clips/intro.mp4"},
                        {"type": "blob", "path": "README.md"},
                    ],
                },
                "readme_text": "# Media Dump",
            },
        }
        report = crucible_index.run_melt_scan(["mercury", "Dangai", "media-dump"], fixtures=fixtures)
        self.assertEqual(report["scanned_count"], 3)
        by_name = {r["repo"]: r for r in report["results"]}
        self.assertEqual(by_name["mercury"]["triage_verdict"], "MELT_READY")
        self.assertEqual(by_name["mercury"]["code_files"], 2)
        self.assertEqual(by_name["mercury"]["test_files"], 1)
        self.assertEqual(by_name["mercury"]["ignored_or_asset_files"], 2)
        self.assertLessEqual(len(by_name["mercury"]["readme_excerpt"]), crucible_index.MAX_README_EXCERPT_CHARS)
        self.assertEqual(by_name["Dangai"]["triage_verdict"], "EMPTY_REPO")
        self.assertEqual(by_name["media-dump"]["triage_verdict"], "SKIP_ASSET_OR_STUB")

        formatted = crucible_index._format_melt_scan_text(report)
        self.assertIn("[MELT_READY] mercury", formatted)
        self.assertIn("[EMPTY_REPO] Dangai", formatted)

    def test_cli_melt_diff_and_melt_scan_offline_json_and_cap_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            diff_fix = tmp_path / "repos.json"
            diff_fix.write_text(
                json.dumps(
                    [
                        {
                            "name": "mercury",
                            "pushedAt": "2026-11-23T07:00:00Z",
                            "diskUsage": 112,
                            "isPrivate": True,
                            "isArchived": False,
                            "primaryLanguage": {"name": "Python"},
                            "description": "Desk",
                        }
                    ]
                ),
                encoding="utf-8",
            )
            p_diff = subprocess.run(
                [
                    sys.executable,
                    str(GATE_SCRIPT),
                    "--root",
                    str(REPO_ROOT),
                    "melt-diff",
                    "--from-json",
                    str(diff_fix),
                    "--json",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(p_diff.returncode, 0, p_diff.stderr)
            diff_out = json.loads(p_diff.stdout)
            self.assertEqual(diff_out["counts"]["unmelted"], 1)

            p_over_cap = subprocess.run(
                [
                    sys.executable,
                    str(GATE_SCRIPT),
                    "--root",
                    str(REPO_ROOT),
                    "melt-scan",
                    "r1",
                    "r2",
                    "r3",
                    "r4",
                    "r5",
                    "r6",
                ],
                cwd=REPO_ROOT,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(p_over_cap.returncode, 2)
            self.assertIn("batch cap exceeded", p_over_cap.stderr)

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


if __name__ == "__main__":
    unittest.main()
