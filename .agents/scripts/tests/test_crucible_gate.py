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

    def test_export_map_writes_valid_json(self) -> None:
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
            tmp_path = Path(tmp)
            repo = _init_repo(tmp_path, None)
            (repo / "Knowledge" / "Media Agency" / "Skills and Workflows").mkdir(parents=True)
            (repo / "Knowledge" / "Media Agency" / "Skills and Workflows" / "media-writing.md").write_text(
                "## MW-04: Write A/V Script\n\nDual-channel script draft.\n",
                encoding="utf-8",
            )
            (repo / "Knowledge" / "Media Agency" / "PROD-S.md").write_text(
                "# PROD-S — Production Specialist\n\nOwns media execution.\n",
                encoding="utf-8",
            )
            (repo / "Knowledge" / "Knowledge_Register.md").write_text(
                "| ID | Topic | Rule | Status |\n| --- | --- | --- | --- |\n| K-WOS-01 | Graphs | Use 7 graph types | Live |\n",
                encoding="utf-8",
            )
            (repo / "Knowledge" / "Crucible_Primitives.json").write_text(
                json.dumps(valid_primitives, indent=2),
                encoding="utf-8",
            )
            skill_dir = repo / ".agents" / "plugins" / "inner-gravity" / "skills" / "ig-demo"
            skill_dir.mkdir(parents=True)
            (skill_dir / "SKILL.md").write_text(
                "---\nname: ig-demo\ndescription: Demo local skill.\n---\n# ig-demo\n",
                encoding="utf-8",
            )

            proc = _run_gate(repo, "export-map", "--no-global")
            self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
            map_path = repo / "Graphs" / "capability_map.json"
            self.assertTrue(map_path.is_file())

            first_text = map_path.read_text(encoding="utf-8")
            payload = json.loads(first_text)
            self.assertEqual(payload["schema"], "crucible-capability-map/v1")
            self.assertEqual(payload["total"], 5)
            self.assertEqual(len(payload["entries"]), payload["total"])
            self.assertEqual(sum(payload["counts_by_kind"].values()), payload["total"])

            ids = [entry["id"] for entry in payload["entries"]]
            self.assertEqual(ids, sorted(ids))
            self.assertEqual(ids, ["K-WOS-01", "MW-04", "PRIM-01", "PROD-S", "ig-demo"])

            expected_keys = {"id", "kind", "title", "path", "line", "domain", "reachability", "summary"}
            for entry in payload["entries"]:
                self.assertEqual(set(entry.keys()), expected_keys)
            by_id = {entry["id"]: entry for entry in payload["entries"]}
            self.assertEqual(by_id["ig-demo"]["path"], ".agents/plugins/inner-gravity/skills/ig-demo/SKILL.md")

            custom_out = Path("custom") / "map.json"
            proc_custom = _run_gate(repo, "export-map", "--no-global", "--json", "--output", str(custom_out))
            self.assertEqual(proc_custom.returncode, 0, proc_custom.stdout + proc_custom.stderr)
            self.assertEqual((repo / custom_out).read_text(encoding="utf-8"), first_text)
            self.assertEqual(json.loads(proc_custom.stdout), payload)

            bad_dir_proc = _run_gate(repo, "export-map", "--no-global", "--output", "Graphs")
            self.assertNotEqual(bad_dir_proc.returncode, 0)
            self.assertIn("BLOCKED:", bad_dir_proc.stderr)

            missing_root_proc = subprocess.run(
                [sys.executable, str(GATE_SCRIPT), "--root", str(tmp_path / "missing-repo"), "export-map", "--no-global"],
                cwd=tmp_path,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            self.assertNotEqual(missing_root_proc.returncode, 0)
            self.assertIn("BLOCKED:", missing_root_proc.stderr)

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

    def test_check_blocks_invalid_outcome_ledger_json(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _init_repo(Path(tmp), None)
            (repo / "Knowledge").mkdir(parents=True)
            ledger_path = repo / "Knowledge" / "outcome_ledger.json"

            ok_learn = _run_gate(
                repo,
                "learn",
                "--verdict",
                "PASS",
                "--source",
                "ci:test",
                "--cap",
                "CRUCIBLE-ATLAS",
            )
            self.assertEqual(ok_learn.returncode, 0, ok_learn.stdout + ok_learn.stderr)
            ok_proc = _run_gate(repo, "check")
            self.assertEqual(ok_proc.returncode, 0, ok_proc.stdout + ok_proc.stderr)
            self.assertIn("PASS:", ok_proc.stdout)

            ledger_path.write_text(
                json.dumps({"schema_version": 99, "capability_priors": {}, "file_risk": {}, "events": []}),
                encoding="utf-8",
            )
            bad_schema = _run_gate(repo, "check")
            self.assertEqual(bad_schema.returncode, 1, bad_schema.stdout + bad_schema.stderr)
            self.assertIn("BLOCKED:", bad_schema.stdout)
            self.assertIn("outcome_ledger.json", bad_schema.stdout)

            ledger_path.write_text("{corrupt json", encoding="utf-8")
            bad_json = _run_gate(repo, "check")
            self.assertEqual(bad_json.returncode, 1, bad_json.stdout + bad_json.stderr)
            self.assertIn("BLOCKED:", bad_json.stdout)
            self.assertIn("invalid JSON", bad_json.stdout)


if __name__ == "__main__":
    unittest.main()
