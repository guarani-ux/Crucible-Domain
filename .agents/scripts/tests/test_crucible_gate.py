#!/usr/bin/env python3
"""Red-capable end-to-end tests for the Crucible Domain Contract Stop Gate."""

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


def _render_ideas(contract_obj: dict[str, object] | None) -> str:
    lines = [
        "# Test Ledger (`IDEAS.md`)",
        "",
        "## Stage 4: Active (WIP <= 1)",
        "- [P-TEST] Active test slice.",
    ]
    if contract_obj is not None:
        lines.extend(
            [
                "",
                "```contract",
                json.dumps(contract_obj, indent=2),
                "```",
            ]
        )
    lines.extend(["", "## Stage 3: Hardened", "- [P-OLD] Parked."])
    return "\n".join(lines) + "\n"


def _init_repo(tmp_dir: Path, contract_obj: dict[str, object] | None) -> Path:
    repo = tmp_dir / "repo"
    repo.mkdir()
    _git(repo, "init")
    _git(repo, "config", "user.name", "Test User")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "IDEAS.md").write_text(_render_ideas(contract_obj), encoding="utf-8")
    _git(repo, "add", "IDEAS.md")
    _git(repo, "commit", "-m", "Initial baseline")
    return repo


class TestCrucibleGateContractStop(unittest.TestCase):
    """End-to-end CLI verification of verify, stop, and session-start base tracking."""

    def test_passing_contract(self) -> None:
        contract = {
            "intent": "Create app module inside src scope.",
            "allowed_paths": ["src/*.py"],
            "checks": ["python -c \"print('ok')\""],
        }
        with tempfile.TemporaryDirectory() as tmp:
            repo = _init_repo(Path(tmp), contract)
            ss = _run_gate(repo, "session-start")
            self.assertEqual(ss.returncode, 0, ss.stderr)

            (repo / "src").mkdir()
            (repo / "src" / "app.py").write_text("VALUE = 1\n", encoding="utf-8")

            ver = _run_gate(repo, "verify")
            self.assertEqual(ver.returncode, 0, ver.stdout + ver.stderr)
            self.assertIn("PASS:", ver.stdout)

            stp = _run_gate(
                repo,
                "stop",
                stdin_payload={"terminationReason": "NO_TOOL_CALL", "executionNum": 0},
            )
            self.assertEqual(stp.returncode, 0, stp.stderr)
            self.assertEqual(json.loads(stp.stdout), {"decision": "allow"})

    def test_failing_check_command(self) -> None:
        contract = {
            "intent": "Verify failing check blocks with output tail.",
            "allowed_paths": ["src/*.py"],
            "checks": ["python -c \"print('boom_marker_line'); raise SystemExit(2)\""],
        }
        with tempfile.TemporaryDirectory() as tmp:
            repo = _init_repo(Path(tmp), contract)
            self.assertEqual(_run_gate(repo, "session-start").returncode, 0)

            ver = _run_gate(repo, "verify")
            self.assertEqual(ver.returncode, 1, ver.stdout + ver.stderr)
            self.assertIn("BLOCKED:", ver.stdout)
            self.assertIn("boom_marker_line", ver.stdout)

            stp = _run_gate(
                repo,
                "stop",
                stdin_payload={"terminationReason": "NO_TOOL_CALL", "executionNum": 0},
            )
            self.assertEqual(stp.returncode, 0, stp.stderr)
            data = json.loads(stp.stdout)
            self.assertEqual(data.get("decision"), "continue")
            self.assertIn("boom_marker_line", data.get("reason", ""))

    def test_file_outside_scope(self) -> None:
        contract = {
            "intent": "Only allow files under src/.",
            "allowed_paths": ["src/*.py"],
            "checks": ["python -c \"print('ok')\""],
        }
        with tempfile.TemporaryDirectory() as tmp:
            repo = _init_repo(Path(tmp), contract)
            self.assertEqual(_run_gate(repo, "session-start").returncode, 0)

            (repo / "outside.txt").write_text("stray file\n", encoding="utf-8")

            ver = _run_gate(repo, "verify")
            self.assertEqual(ver.returncode, 1, ver.stdout + ver.stderr)
            self.assertIn("BLOCKED:", ver.stdout)
            self.assertIn("outside.txt", ver.stdout)

            stp = _run_gate(
                repo,
                "stop",
                stdin_payload={"terminationReason": "NO_TOOL_CALL", "executionNum": 0},
            )
            self.assertEqual(stp.returncode, 0, stp.stderr)
            data = json.loads(stp.stdout)
            self.assertEqual(data.get("decision"), "continue")
            self.assertIn("outside.txt", data.get("reason", ""))

    def test_contract_edited_mid_session(self) -> None:
        initial_contract = {
            "intent": "Frozen contract baseline.",
            "allowed_paths": ["src/*.py"],
            "checks": ["python -c \"print('ok')\""],
        }
        tampered_contract = {
            "intent": "Tampered contract mid-session.",
            "allowed_paths": ["IDEAS.md", "src/*.py"],
            "checks": [
                "python -c \"from pathlib import Path; Path('sentinel.txt').write_text('ran', encoding='utf-8')\""
            ],
        }
        with tempfile.TemporaryDirectory() as tmp:
            repo = _init_repo(Path(tmp), initial_contract)
            self.assertEqual(_run_gate(repo, "session-start").returncode, 0)

            (repo / "IDEAS.md").write_text(_render_ideas(tampered_contract), encoding="utf-8")

            ver = _run_gate(repo, "verify")
            self.assertEqual(ver.returncode, 1, ver.stdout + ver.stderr)
            self.assertIn("contract changed mid-session; Levi must approve and commit it.", ver.stdout)
            self.assertFalse((repo / "sentinel.txt").exists())

            stp = _run_gate(
                repo,
                "stop",
                stdin_payload={"terminationReason": "NO_TOOL_CALL", "executionNum": 0},
            )
            self.assertEqual(stp.returncode, 0, stp.stderr)
            data = json.loads(stp.stdout)
            self.assertEqual(data.get("decision"), "continue")
            self.assertIn("contract changed mid-session; Levi must approve and commit it.", data.get("reason", ""))

    def test_no_contract_blocks_verify_and_allows_stop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _init_repo(Path(tmp), None)
            self.assertEqual(_run_gate(repo, "session-start").returncode, 0)

            ver = _run_gate(repo, "verify")
            self.assertEqual(ver.returncode, 1, ver.stdout + ver.stderr)
            self.assertIn("BLOCKED:", ver.stdout)

            stp = _run_gate(
                repo,
                "stop",
                stdin_payload={"terminationReason": "NO_TOOL_CALL", "executionNum": 0},
            )
            self.assertEqual(stp.returncode, 0, stp.stderr)
            self.assertEqual(json.loads(stp.stdout), {"decision": "allow"})

    def test_stop_execution_num_cap_allows(self) -> None:
        contract = {
            "intent": "Failing check capped after 3 continuations.",
            "allowed_paths": ["src/*.py"],
            "checks": ["python -c \"print('fail'); raise SystemExit(2)\""],
        }
        with tempfile.TemporaryDirectory() as tmp:
            repo = _init_repo(Path(tmp), contract)
            self.assertEqual(_run_gate(repo, "session-start").returncode, 0)

            stp = _run_gate(
                repo,
                "stop",
                stdin_payload={"terminationReason": "NO_TOOL_CALL", "executionNum": 3},
            )
            self.assertEqual(stp.returncode, 0, stp.stderr)
            self.assertEqual(json.loads(stp.stdout), {"decision": "allow"})

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


if __name__ == "__main__":
    unittest.main()
