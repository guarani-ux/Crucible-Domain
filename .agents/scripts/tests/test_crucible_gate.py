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

    def test_asana_url_blocks_real_links_but_allows_negative_disclaimer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _init_repo(Path(tmp), None)
            cpl_dir = repo / "Calgary Public Library"
            cpl_dir.mkdir()
            note = cpl_dir / "note.md"

            note.write_text("Policy: zero app.asana.com URLs allowed.\n", encoding="utf-8")
            _git(repo, "add", "Calgary Public Library/note.md")
            clean = _run_gate(repo, "check")
            self.assertEqual(clean.returncode, 0, clean.stdout + clean.stderr)
            self.assertIn("PASS:", clean.stdout)

            note.write_text("Task link: https://app.asana.com/0/12345/67890\n", encoding="utf-8")
            _git(repo, "add", "Calgary Public Library/note.md")
            https_hit = _run_gate(repo, "check")
            self.assertEqual(https_hit.returncode, 1, https_hit.stdout + https_hit.stderr)
            self.assertIn("BLOCKED:", https_hit.stdout)

            note.write_text("Bare link: app.asana.com/0/12345\n", encoding="utf-8")
            _git(repo, "add", "Calgary Public Library/note.md")
            bare_hit = _run_gate(repo, "check")
            self.assertEqual(bare_hit.returncode, 1, bare_hit.stdout + bare_hit.stderr)
            self.assertIn("BLOCKED:", bare_hit.stdout)

    def test_shifting_sand_blocks_deliverable_until_ground_truth_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = _init_repo(Path(tmp), None)
            cpl_dir = repo / "Calgary Public Library"
            cpl_dir.mkdir()

            deny_resp = _run_gate(
                repo,
                "pre-tool",
                stdin_payload={
                    "toolCall": {
                        "name": "write_file",
                        "args": {"Path": str(cpl_dir / "pitch.md")},
                    }
                },
            )
            self.assertEqual(deny_resp.returncode, 0, deny_resp.stderr)
            deny_data = json.loads(deny_resp.stdout)
            self.assertEqual(deny_data.get("decision"), "deny")
            self.assertIn("SHIFTING_SAND", deny_data.get("reason", ""))

            allow_gt = _run_gate(
                repo,
                "pre-tool",
                stdin_payload={
                    "toolCall": {
                        "name": "write_file",
                        "args": {"Path": str(cpl_dir / "GROUND_TRUTH.md")},
                    }
                },
            )
            self.assertEqual(allow_gt.returncode, 0, allow_gt.stderr)
            self.assertEqual(json.loads(allow_gt.stdout), {"decision": "allow"})

            (cpl_dir / "GROUND_TRUTH.md").write_text("# Ground Truth\n", encoding="utf-8")
            allow_after = _run_gate(
                repo,
                "pre-tool",
                stdin_payload={
                    "toolCall": {
                        "name": "write_file",
                        "args": {"Path": str(cpl_dir / "pitch.md")},
                    }
                },
            )
            self.assertEqual(allow_after.returncode, 0, allow_after.stderr)
            self.assertEqual(json.loads(allow_after.stdout), {"decision": "allow"})

    def test_untracked_and_pretool_asana_url_leaks_are_blocked(self) -> None:
        """Fails if an untracked CPL file or write_file payload leaks a real Asana URL."""
        with tempfile.TemporaryDirectory() as tmp:
            repo = _init_repo(Path(tmp), None)
            cpl_dir = repo / "Calgary Public Library"
            cpl_dir.mkdir()
            (cpl_dir / "GROUND_TRUTH.md").write_text("# Ground Truth\n", encoding="utf-8")

            untracked = cpl_dir / "draft.md"
            untracked.write_text("Link: https://app.asana.com/0/999/111\n", encoding="utf-8")
            chk_untracked = _run_gate(repo, "check")
            self.assertEqual(chk_untracked.returncode, 1, chk_untracked.stdout + chk_untracked.stderr)
            self.assertIn("BLOCKED:", chk_untracked.stdout)

            deny_write = _run_gate(
                repo,
                "pre-tool",
                stdin_payload={
                    "toolCall": {
                        "name": "write_file",
                        "args": {
                            "Path": str(cpl_dir / "draft.md"),
                            "Content": "Internal: https://app.asana.com/0/999/111\n",
                        },
                    }
                },
            )
            self.assertEqual(deny_write.returncode, 0, deny_write.stderr)
            deny_data = json.loads(deny_write.stdout)
            self.assertEqual(deny_data.get("decision"), "deny")
            self.assertIn("ASANA_BOUNDARY", deny_data.get("reason", ""))

            allow_clean = _run_gate(
                repo,
                "pre-tool",
                stdin_payload={
                    "toolCall": {
                        "name": "write_file",
                        "args": {
                            "Path": str(cpl_dir / "draft.md"),
                            "Content": "Policy: zero app.asana.com URLs allowed.\n",
                        },
                    }
                },
            )
            self.assertEqual(allow_clean.returncode, 0, allow_clean.stderr)
            self.assertEqual(json.loads(allow_clean.stdout), {"decision": "allow"})


if __name__ == "__main__":
    unittest.main()
