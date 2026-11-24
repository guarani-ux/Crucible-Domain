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
            self.assertIn("Active WIP: none", msg)

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
            self.assertIn("slice-worker", msg)
            self.assertIn("verify_all.ps1", msg)
            self.assertIn(
                "Execution: workers=slice-worker (Model=flash) | tx=tx_patch.py | verify=scripts/verify_all.ps1 (16-core parallel)",
                msg,
            )
            self.assertIn("Next Slice: see Personal Work/CS_Opportunity_Map.md (Slice #7+)", msg)


if __name__ == "__main__":
    unittest.main()
