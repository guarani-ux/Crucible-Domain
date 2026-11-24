#!/usr/bin/env python3
"""Red-capable end-to-end tests for Crucible Domain deterministic local gates."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

GATE_SCRIPT = Path(__file__).resolve().parents[1] / "crucible_gate.py"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    proc = subprocess.run(
        ["git", *args],
        cwd=repo,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed ({proc.returncode}): {proc.stderr or proc.stdout}")
    return proc


def _run_gate(repo: Path, *args: str, stdin_payload: dict[str, object] | None = None) -> subprocess.CompletedProcess[str]:
    raw_input = json.dumps(stdin_payload) if stdin_payload is not None else "{}"
    return subprocess.run(
        [sys.executable, str(GATE_SCRIPT), "--root", str(repo), *args],
        cwd=repo,
        input=raw_input,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )


def _init_repo(tmp_dir: Path, _unused: object = None) -> Path:
    repo = tmp_dir / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "IDEAS.md").write_text(
        "# Test Ledger (`IDEAS.md`)\n\n## Stage 4: Active (WIP <= 1)\n(empty)\n\n## Stage 3: Hardened\n- [P-OLD] Parked.\n",
        encoding="utf-8",
    )
    _git(repo, "add", "IDEAS.md")
    _git(repo, "commit", "-m", "Initial baseline")
    return repo


class TestCrucibleGate(unittest.TestCase):
    """End-to-end CLI verification of session-start, pre-tool, check, and export-map."""

    def test_session_start_emits_valid_system_map_and_pre_tool_blocks_asana_url(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _init_repo(Path(tmp))
            ss = _run_gate(repo, "session-start")
            self.assertEqual(ss.returncode, 0, ss.stderr)
            ss_data = json.loads(ss.stdout)
            msg = ss_data["injectSteps"][0]["systemMessage"]["systemMessage"]
            self.assertIn("SHIFTING_SAND:", msg)
            self.assertNotIn("Active WIP:", msg)

            cpl_dir = repo / "Calgary Public Library"
            cpl_dir.mkdir()
            (cpl_dir / "GROUND_TRUTH.md").write_text("# CPL Ground Truth\n", encoding="utf-8")

            deny_asana = _run_gate(
                repo,
                "pre-tool",
                stdin_payload={
                    "toolCall": {
                        "name": "write_file",
                        "args": {
                            "Path": str(cpl_dir / "brief.md"),
                            "Content": "Ref: https://app.asana.com/0/12345/list\n",
                        },
                    }
                },
            )
            self.assertEqual(deny_asana.returncode, 0, deny_asana.stderr)
            deny_data = json.loads(deny_asana.stdout)
            self.assertEqual(deny_data.get("decision"), "deny")
            self.assertIn("ASANA_BOUNDARY", deny_data.get("reason", ""))

            allow_clean = _run_gate(
                repo,
                "pre-tool",
                stdin_payload={
                    "toolCall": {
                        "name": "write_file",
                        "args": {
                            "Path": str(cpl_dir / "brief.md"),
                            "Content": "Clean public summary.\n",
                        },
                    }
                },
            )
            self.assertEqual(allow_clean.returncode, 0, allow_clean.stderr)
            self.assertEqual(json.loads(allow_clean.stdout), {"decision": "allow"})


    def test_check_blocks_invalid_primitives_json(self) -> None:
        valid_primitives = {
            "schema_version": 1,
            "families": ["intake-grounding"],
            "primitives": [
                {
                    "id": "PRIM-01",
                    "name": "Ground-Truth Intake Gate",
                    "family": "intake-grounding",
                    "domains": ["systems"],
                    "inputs": "Empty folder",
                    "mechanism": "Require GROUND_TRUTH.md before deliverables.",
                    "outputs": "Bounded scope",
                    "breakpoints": "Hallucinated deliverables",
                    "status": "WIRED_HERE",
                    "sources": ["AGENTS.md"],
                    "receiving_check": "PreToolUse denies ungrounded writes.",
                }
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            repo = _init_repo(Path(tmp), None)
            (repo / "Knowledge").mkdir(parents=True)
            prim_path = repo / "Knowledge" / "Crucible_Primitives.json"
            prim_path.write_text(json.dumps(valid_primitives, indent=2), encoding="utf-8")

            ok_proc = _run_gate(repo, "check")
            self.assertEqual(ok_proc.returncode, 0, ok_proc.stdout + ok_proc.stderr)
            self.assertIn("PASS:", ok_proc.stdout)

            invalid_schema = {
                "families": ["intake-grounding"],
                "primitives": [
                    {
                        "id": "PRIM-99",
                        "name": "Broken Primitive",
                        "family": "unknown-family",
                        "status": "INVALID_STATUS",
                    }
                ],
            }
            prim_path.write_text(json.dumps(invalid_schema, indent=2), encoding="utf-8")
            bad_schema_proc = _run_gate(repo, "check")
            self.assertEqual(bad_schema_proc.returncode, 1, bad_schema_proc.stdout + bad_schema_proc.stderr)
            self.assertIn("BLOCKED:", bad_schema_proc.stdout)
            self.assertIn("Crucible_Primitives.json", bad_schema_proc.stdout)

            prim_path.write_text("{not valid json", encoding="utf-8")
            bad_json_proc = _run_gate(repo, "check")
            self.assertEqual(bad_json_proc.returncode, 1, bad_json_proc.stdout + bad_json_proc.stderr)
            self.assertIn("BLOCKED:", bad_json_proc.stdout)
            self.assertIn("invalid JSON", bad_json_proc.stdout)

    def test_check_blocks_python_syntax_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _init_repo(Path(tmp), None)
            pkg_dir = repo / ".agents" / "scripts" / "crucible"
            pkg_dir.mkdir(parents=True)
            sample_py = pkg_dir / "sample.py"
            sample_py.write_text("VALUE = 42\n", encoding="utf-8")

            ok_proc = _run_gate(repo, "check")
            self.assertEqual(ok_proc.returncode, 0, ok_proc.stdout + ok_proc.stderr)
            self.assertIn("PASS:", ok_proc.stdout)

            sample_py.write_text("def broken(:\n", encoding="utf-8")
            bad_proc = _run_gate(repo, "check")
            self.assertEqual(bad_proc.returncode, 1, bad_proc.stdout + bad_proc.stderr)
            self.assertIn("BLOCKED:", bad_proc.stdout)
            self.assertIn("sample.py", bad_proc.stdout)

    def test_check_blocks_staged_asana_url_in_cpl(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _init_repo(Path(tmp), None)
            cpl_dir = repo / "Calgary Public Library"
            cpl_dir.mkdir(parents=True)
            notes = cpl_dir / "notes.md"
            notes.write_text("# CPL Notes\nClean public summary.\n", encoding="utf-8")
            _git(repo, "add", "Calgary Public Library/notes.md")

            ok_proc = _run_gate(repo, "check")
            self.assertEqual(ok_proc.returncode, 0, ok_proc.stdout + ok_proc.stderr)
            self.assertIn("PASS:", ok_proc.stdout)

            notes.write_text("# CPL Notes\nTask: https://app.asana.com/0/12345/list\n", encoding="utf-8")
            _git(repo, "add", "Calgary Public Library/notes.md")

            bad_proc = _run_gate(repo, "check")
            self.assertEqual(bad_proc.returncode, 1, bad_proc.stdout + bad_proc.stderr)
            self.assertIn("BLOCKED:", bad_proc.stdout)
            self.assertIn("app.asana.com", bad_proc.stdout)

    def test_check_blocks_staged_drive_temp_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _init_repo(Path(tmp), None)
            sync_dir = repo / ".tmp.drivedownload"
            sync_dir.mkdir()
            (sync_dir / "sync.tmp").write_text("partial sync", encoding="utf-8")
            _git(repo, "add", "-f", ".tmp.drivedownload/sync.tmp")

            bad_proc = _run_gate(repo, "check")
            self.assertEqual(bad_proc.returncode, 1, bad_proc.stdout + bad_proc.stderr)
            self.assertIn("BLOCKED:", bad_proc.stdout)
            self.assertIn(".tmp.drive", bad_proc.stdout)

    def test_check_blocks_test_quality_gate_violation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _init_repo(Path(tmp), None)
            tests_dir = repo / ".agents" / "scripts" / "tests"
            tests_dir.mkdir(parents=True)
            sample_test = tests_dir / "test_bad_sample.py"
            sample_test.write_text("def test_tautology():\n    assert True\n", encoding="utf-8")

            bad_proc = _run_gate(repo, "check")
            self.assertEqual(bad_proc.returncode, 1, bad_proc.stdout + bad_proc.stderr)
            self.assertIn("BLOCKED:", bad_proc.stdout)
            self.assertIn("TQ-01", bad_proc.stdout)

            sample_test.write_text("def test_good():\n    assert (2 + 2) != 5\n", encoding="utf-8")
            ok_proc = _run_gate(repo, "check")
            self.assertEqual(ok_proc.returncode, 0, ok_proc.stdout + ok_proc.stderr)
            self.assertIn("PASS:", ok_proc.stdout)

    def test_pre_tool_shifting_sand_blocks_edit_file_and_allows_ground_truth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _init_repo(Path(tmp), None)
            (repo / "Personal Work").mkdir()

            deny_proc = _run_gate(
                repo,
                "pre-tool",
                stdin_payload={
                    "toolCall": {
                        "name": "edit_file",
                        "args": {"Path": str(repo / "Personal Work" / "draft.md")},
                    }
                },
            )
            self.assertEqual(deny_proc.returncode, 0, deny_proc.stderr)
            deny_data = json.loads(deny_proc.stdout)
            self.assertEqual(deny_data.get("decision"), "deny")
            self.assertIn("SHIFTING_SAND", deny_data.get("reason", ""))

            allow_proc = _run_gate(
                repo,
                "pre-tool",
                stdin_payload={
                    "toolCall": {
                        "name": "edit_file",
                        "args": {"Path": str(repo / "Personal Work" / "GROUND_TRUTH.md")},
                    }
                },
            )
            self.assertEqual(allow_proc.returncode, 0, allow_proc.stderr)
            self.assertEqual(json.loads(allow_proc.stdout), {"decision": "allow"})

    def test_check_blocks_missing_ideas_md(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _init_repo(Path(tmp), None)
            (repo / "IDEAS.md").unlink()

            bad_proc = _run_gate(repo, "check")
            self.assertEqual(bad_proc.returncode, 1, bad_proc.stdout + bad_proc.stderr)
            self.assertIn("BLOCKED:", bad_proc.stdout)
            self.assertIn("IDEAS.md missing", bad_proc.stdout)

    def test_session_start_includes_execution_profile(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _init_repo(Path(tmp))
            proc = _run_gate(repo, "session-start")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            data = json.loads(proc.stdout)
            msg = data["injectSteps"][0]["systemMessage"]["systemMessage"]
            self.assertIn("Spokes: writers-room, story-lane, crucible-observatory", msg)
            self.assertIn("Verify: scripts/verify_all.ps1", msg)

    def test_pre_tool_blocks_destructive_and_grant_tampering_run_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _init_repo(Path(tmp))
            deny_push = _run_gate(
                repo,
                "pre-tool",
                stdin_payload={
                    "toolCall": {
                        "name": "run_command",
                        "args": {"CommandLine": "git push origin main"},
                    }
                },
            )
            self.assertEqual(deny_push.returncode, 0, deny_push.stderr)
            push_data = json.loads(deny_push.stdout)
            self.assertEqual(push_data.get("decision"), "deny")
            self.assertIn("AUTHORITY_GUARD", push_data.get("reason", ""))

            deny_grant = _run_gate(
                repo,
                "pre-tool",
                stdin_payload={
                    "toolCall": {
                        "name": "run_command",
                        "args": {"CommandLine": "echo '{}' > .agents/operator_grants.json"},
                    }
                },
            )
            self.assertEqual(deny_grant.returncode, 0, deny_grant.stderr)
            grant_data = json.loads(deny_grant.stdout)
            self.assertEqual(grant_data.get("decision"), "deny")
            self.assertIn("AUTHORITY_GUARD", grant_data.get("reason", ""))

            allow_ls = _run_gate(
                repo,
                "pre-tool",
                stdin_payload={
                    "toolCall": {
                        "name": "run_command",
                        "args": {"CommandLine": "git status -s"},
                    }
                },
            )
            self.assertEqual(allow_ls.returncode, 0, allow_ls.stderr)
            self.assertEqual(json.loads(allow_ls.stdout), {"decision": "allow"})

    def test_campaign_run_records_completed_slice_checkpoint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _init_repo(Path(tmp))
            (repo / "target.txt").write_text("hello\n", encoding="utf-8")
            (repo / "verify_ok.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
            py_exe = sys.executable if " " not in sys.executable else "python"
            spec = {
                "name": "demo-pass",
                "repo_root": str(repo),
                "max_rounds": 3,
                "slices": [
                    {
                        "id": "s1",
                        "target_paths": ["target.txt"],
                        "depends_on": [],
                        "verify_cmd": f"{py_exe} verify_ok.py",
                    }
                ],
            }
            (repo / "spec.json").write_text(json.dumps(spec), encoding="utf-8")

            proc = _run_gate(repo, "campaign", "run", "spec.json", "--cache", "cp.json", "--json")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            data = json.loads(proc.stdout)
            self.assertTrue(data["ok"])
            self.assertEqual(data["slice_id"], "s1")
            self.assertEqual(data["exit_code"], 0)
            self.assertEqual(data["status"], "PASS")
            self.assertEqual(data["rounds_used"], 1)
            self.assertEqual(data["max_rounds"], 3)
            self.assertEqual(len(data["input_sha256"]), 64)

            cp_data = json.loads((repo / "cp.json").read_text(encoding="utf-8"))
            self.assertEqual(cp_data["campaign_name"], "demo-pass")
            self.assertEqual(cp_data["completed_slices"], {"s1": data["input_sha256"]})
            self.assertEqual(cp_data["failed_slices"], {})
            self.assertEqual(cp_data["rounds_used"], 1)

    def test_campaign_run_failure_records_failed_slice_and_halts_at_max_rounds(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _init_repo(Path(tmp))
            (repo / "target.txt").write_text("hello\n", encoding="utf-8")
            (repo / "verify_fail.py").write_text(
                "import sys\nsys.stderr.write('boom\\n')\nsys.exit(3)\n",
                encoding="utf-8",
            )
            py_exe = sys.executable if " " not in sys.executable else "python"
            spec = {
                "name": "demo-fail",
                "repo_root": str(repo),
                "max_rounds": 1,
                "slices": [
                    {
                        "id": "s1",
                        "target_paths": ["target.txt"],
                        "depends_on": [],
                        "verify_cmd": f"{py_exe} verify_fail.py",
                    }
                ],
            }
            (repo / "spec.json").write_text(json.dumps(spec), encoding="utf-8")

            proc = _run_gate(repo, "campaign", "run", "spec.json", "--cache", "cp.json", "--json")
            self.assertEqual(proc.returncode, 1, proc.stdout + proc.stderr)
            data = json.loads(proc.stdout)
            self.assertFalse(data["ok"])
            self.assertEqual(data["slice_id"], "s1")
            self.assertEqual(data["exit_code"], 3)
            self.assertEqual(data["status"], "ROLLED_BACK")
            self.assertEqual(data["rounds_used"], 1)
            self.assertEqual(data["max_rounds"], 1)

            cp_data = json.loads((repo / "cp.json").read_text(encoding="utf-8"))
            self.assertEqual(cp_data["completed_slices"], {})
            self.assertIn("s1", cp_data["failed_slices"])
            self.assertEqual(cp_data["rounds_used"], 1)

            proc2 = _run_gate(repo, "campaign", "run", "spec.json", "--cache", "cp.json", "--json")
            self.assertEqual(proc2.returncode, 1, proc2.stdout + proc2.stderr)
            data2 = json.loads(proc2.stdout)
            self.assertFalse(data2["ok"])
            self.assertEqual(data2["status"], "HALT_MAX_ROUNDS")
            self.assertEqual(data2["rounds_used"], 1)

    def test_ast_scan_discover_story_and_g5_cli_subcommands(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _init_repo(Path(tmp))
            (repo / ".agents" / "scripts" / "crucible").mkdir(parents=True, exist_ok=True)
            (repo / ".agents" / "scripts" / "crucible" / "mod_a.py").write_text(
                "def helper() -> int:\n    return 7\n",
                encoding="utf-8",
            )
            (repo / ".agents" / "scripts" / "crucible" / "mod_b.py").write_text(
                "from crucible.mod_a import helper\n\ndef run() -> int:\n    return helper()\n",
                encoding="utf-8",
            )

            scan_proc = _run_gate(repo, "ast-scan", "--import-root", ".agents/scripts", "--json")
            self.assertEqual(scan_proc.returncode, 0, scan_proc.stdout + scan_proc.stderr)
            scan_data = json.loads(scan_proc.stdout)
            self.assertGreaterEqual(scan_data["unit_count"], 2)
            self.assertGreaterEqual(scan_data["edge_count"], 1)

            # Negative: missing G5 ledger fails g5-check
            g5_missing = _run_gate(repo, "g5-check", "--json")
            self.assertEqual(g5_missing.returncode, 1)
            self.assertFalse(json.loads(g5_missing.stdout)["passed"])

            # Positive: story select + CHG-01 validation
            transcript = repo / "clip_src.json"
            transcript.write_text(
                json.dumps(
                    {
                        "segments": [
                            {"id": "s1", "start": 0.0, "end": 4.0, "text": "library opening", "arc_hint": "OPEN"},
                            {"id": "s2", "start": 4.0, "end": 9.0, "text": "library studio", "arc_hint": "DEVELOP"},
                            {"id": "s3", "start": 9.0, "end": 13.0, "text": "library impact", "arc_hint": "PAYOFF_CLOSE"},
                        ]
                    }
                ),
                encoding="utf-8",
            )
            out_dir = repo / "story_out"
            story_proc = _run_gate(
                repo,
                "story",
                "select",
                str(transcript),
                "--terms",
                "library",
                "--max-duration",
                "20",
                "--output-dir",
                str(out_dir),
                "--json",
            )
            self.assertEqual(story_proc.returncode, 0, story_proc.stdout + story_proc.stderr)
            story_data = json.loads(story_proc.stdout)
            self.assertTrue(story_data["selection"]["story_arc_complete"])
            manifest_file = Path(story_data["manifest_path"])
            self.assertTrue(manifest_file.is_file())

            chg_ok = _run_gate(repo, "story", "chg01", str(manifest_file), str(transcript), "--json")
            self.assertEqual(chg_ok.returncode, 0, chg_ok.stdout + chg_ok.stderr)
            self.assertFalse(json.loads(chg_ok.stdout)["stale"])

            # Negative: 1-byte transcript change triggers CHG-01 invalidation
            transcript.write_text(
                transcript.read_text(encoding="utf-8").replace("impact", "impacts"),
                encoding="utf-8",
            )
            chg_stale = _run_gate(repo, "story", "chg01", str(manifest_file), str(transcript), "--json")
            self.assertEqual(chg_stale.returncode, 1)
            self.assertTrue(json.loads(chg_stale.stdout)["stale"])

            # Replay-verified campaign run with --replay-out
            (repo / "verify_ok.py").write_text("import sys\nsys.exit(0)\n", encoding="utf-8")
            py_exe = sys.executable if " " not in sys.executable else "python"
            spec = {
                "name": "replay-cli",
                "repo_root": str(repo),
                "max_rounds": 2,
                "slices": [
                    {
                        "id": "s1",
                        "target_paths": [".agents/scripts/crucible/mod_a.py"],
                        "depends_on": [],
                        "verify_cmd": f"{py_exe} verify_ok.py",
                    }
                ],
            }
            (repo / "spec.json").write_text(json.dumps(spec), encoding="utf-8")
            rep_proc = _run_gate(repo, "campaign", "run", "spec.json", "--replay-out", "trace.jsonl", "--json")
            self.assertEqual(rep_proc.returncode, 0, rep_proc.stdout + rep_proc.stderr)
            rep_data = json.loads(rep_proc.stdout)
            self.assertTrue(rep_data["ok"])
            self.assertTrue(rep_data["replay_verified"])
            self.assertTrue((repo / "trace.jsonl").is_file())

            # Discover command runs cleanly and emits campaign JSON
            disc_proc = _run_gate(repo, "discover", "--emit-campaign", "disc.json", "--json")
            self.assertIn(disc_proc.returncode, (0, 1))
            self.assertTrue((repo / "disc.json").is_file())


if __name__ == "__main__":
    unittest.main()
