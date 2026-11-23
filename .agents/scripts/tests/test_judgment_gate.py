#!/usr/bin/env python3
"""3-case qualification tests (bad / good / changed) for judgment_gate.py (JG-01..JG-04)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import judgment_gate  # noqa: E402


class TestJudgmentGateHardLayer(unittest.TestCase):
    """Verify JG-01..JG-04 enforce hard floors for bad inputs while allowing good and changed flows."""

    def test_jg01_pointer_integrity_bad_good_changed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            good_py = root / "engine.py"
            good_py.write_text("VALUE = 1\n", encoding="utf-8")
            missing_py = root / "missing_hook.py"
            gemini_md = root / "GEMINI.md"
            gemini_md.write_text(
                "# Constitution\n\n## System Pointers\n"
                f"- Core: `{good_py}`\n"
                f"- Missing: `{missing_py}`\n",
                encoding="utf-8",
            )

            # BAD: missing pointer triggers HOLD on SessionStart and continue on Stop
            ss_bad = judgment_gate.handle_session_start({}, gemini_md_path=gemini_md)
            msg_bad = ss_bad["injectSteps"][0]["systemMessage"]["systemMessage"]
            self.assertIn("HOLD [JG-01", msg_bad)
            self.assertIn("missing_hook.py", msg_bad)

            stop_bad = judgment_gate.handle_stop({"terminationReason": "NO_TOOL_CALL", "executionNum": 0}, gemini_md_path=gemini_md)
            self.assertEqual(stop_bad["decision"], "continue")
            self.assertIn("JG-01", stop_bad["reason"])

            # BAD (syntax error): broken Python pointer also fails JG-01
            missing_py.write_text("def broken(:\n    pass\n", encoding="utf-8")
            _, syn_errors = judgment_gate.check_system_pointers(gemini_md)
            self.assertTrue(any("SyntaxError" in e for e in syn_errors))

            # CHANGED -> GOOD: valid pointer passes both SessionStart and Stop
            missing_py.write_text("def ok() -> int:\n    return 2\n", encoding="utf-8")
            ss_ok = judgment_gate.handle_session_start({}, gemini_md_path=gemini_md)
            msg_ok = ss_ok["injectSteps"][0]["systemMessage"]["systemMessage"]
            self.assertIn("2/2 GEMINI.md system pointers verified", msg_ok)
            stop_ok = judgment_gate.handle_stop({"terminationReason": "NO_TOOL_CALL", "executionNum": 0}, gemini_md_path=gemini_md)
            self.assertEqual(stop_ok["decision"], "allow")

    def test_jg02_skill_chaining_blocks_third_skill_and_resets_on_action_or_new_turn(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = {"conversationId": "conv-1", "artifactDirectoryPath": tmp}
            for idx in (1, 2):
                p = {**base, "toolCall": {"name": "read_file", "args": {"Path": str(Path(tmp) / f"s{idx}" / "SKILL.md")}}}
                self.assertEqual(judgment_gate.handle_pre(p)["decision"], "allow")
                judgment_gate.handle_post(p)

            # BAD: 3rd distinct SKILL.md without acting is hard-denied
            third = {**base, "toolCall": {"name": "read_file", "args": {"Path": str(Path(tmp) / "s3" / "SKILL.md")}}}
            res_bad = judgment_gate.handle_pre(third)
            self.assertEqual(res_bad["decision"], "deny")
            self.assertIn("JG-02", res_bad["reason"])

            # GOOD: normal non-skill file reads remain unaffected
            normal = {**base, "toolCall": {"name": "read_file", "args": {"Path": str(Path(tmp) / "README.md")}}}
            self.assertEqual(judgment_gate.handle_pre(normal)["decision"], "allow")

            # CHANGED: performing an edit resets the skill budget
            edit = {**base, "toolCall": {"name": "edit_file", "args": {"Path": str(Path(tmp) / "app.py")}}}
            judgment_gate.handle_post(edit)
            self.assertEqual(judgment_gate.handle_pre(third)["decision"], "allow")

    def test_jg03_serial_gh_api_blocked_on_third_call_and_resets_on_new_prompt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = {"conversationId": "conv-2", "artifactDirectoryPath": tmp}
            judgment_gate.handle_pre_invocation({**base, "lastUserInput": "inspect repo"})

            for endpoint in ("commits", "contents/README.md"):
                p = {**base, "toolCall": {"name": "run_command", "args": {"CommandLine": f"gh api repos/acme/demo/{endpoint}"}}}
                self.assertEqual(judgment_gate.handle_pre(p)["decision"], "allow")
                judgment_gate.handle_post(p)

            # BAD: 3rd serial gh api call to same repo is denied
            third = {**base, "toolCall": {"name": "run_command", "args": {"CommandLine": "gh api repos/acme/demo/contents/store.py"}}}
            res_bad = judgment_gate.handle_pre(third)
            self.assertEqual(res_bad["decision"], "deny")
            self.assertIn("JG-03", res_bad["reason"])

            # GOOD: different repo or local git command still allowed
            other_repo = {**base, "toolCall": {"name": "run_command", "args": {"CommandLine": "gh api repos/acme/other/commits"}}}
            self.assertEqual(judgment_gate.handle_pre(other_repo)["decision"], "allow")
            local_git = {**base, "toolCall": {"name": "run_command", "args": {"CommandLine": "git fetch origin"}}}
            self.assertEqual(judgment_gate.handle_pre(local_git)["decision"], "allow")

            # CHANGED: new user prompt resets per-turn gh api counter
            judgment_gate.handle_pre_invocation({**base, "lastUserInput": "now check another endpoint"})
            self.assertEqual(judgment_gate.handle_pre(third)["decision"], "allow")

    def test_jg04_redundant_verification_blocked_until_edit_and_cli_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = {"conversationId": "conv-3", "artifactDirectoryPath": tmp}
            doc_cmd = {**base, "toolCall": {"name": "run_command", "args": {"CommandLine": 'python ".agents/scripts/crucible_gate.py" doctor'}}}
            test_cmd = {**base, "toolCall": {"name": "run_command", "args": {"CommandLine": "python -m unittest discover -s tests"}}}

            # GOOD: first doctor run succeeds and records edit_seq=0
            self.assertEqual(judgment_gate.handle_pre(doc_cmd)["decision"], "allow")
            judgment_gate.handle_post(doc_cmd)

            # BAD: repeating doctor with 0 edits since last PASS is hard-denied
            res_dup = judgment_gate.handle_pre(doc_cmd)
            self.assertEqual(res_dup["decision"], "deny")
            self.assertIn("JG-04", res_dup["reason"])

            # GOOD: running a different verification class (unittest) is still allowed
            self.assertEqual(judgment_gate.handle_pre(test_cmd)["decision"], "allow")

            # GOOD: if unittest FAILED, retrying it without an edit is NOT blocked
            judgment_gate.handle_post({**test_cmd, "error": "exit code 1"})
            self.assertEqual(judgment_gate.handle_pre(test_cmd)["decision"], "allow")

            # CHANGED: editing a file advances edit_seq and unlocks doctor again
            judgment_gate.handle_post({**base, "toolCall": {"name": "write_file", "args": {"Path": str(Path(tmp) / "x.py")}}})
            self.assertEqual(judgment_gate.handle_pre(doc_cmd)["decision"], "allow")

            # Live subprocess CLI check with CRUCIBLE_GEMINI_MD pointing to temp valid pointer
            ok_script = Path(tmp) / "live_ptr.py"
            ok_script.write_text("OK = True\n", encoding="utf-8")
            md = Path(tmp) / "GEMINI.md"
            md.write_text(f"## System Pointers\n- Live: `{ok_script}`\n", encoding="utf-8")
            env = dict(os.environ, CRUCIBLE_GEMINI_MD=str(md))
            proc = subprocess.run(
                [sys.executable, str(SCRIPTS_DIR / "judgment_gate.py"), "session-start"],
                input="{}",
                text=True,
                capture_output=True,
                env=env,
                check=False,
            )
            payload = json.loads(proc.stdout)
            self.assertIn("1/1 GEMINI.md system pointers verified", payload["injectSteps"][0]["systemMessage"]["systemMessage"])


if __name__ == "__main__":
    unittest.main()
