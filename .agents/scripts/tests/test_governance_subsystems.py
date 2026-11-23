#!/usr/bin/env python3
"""Targeted isolation tests for 0%-covered workspace governance subsystems."""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[3]
OBSERVE_SCRIPT = REPO_ROOT / ".agents" / "plugins" / "inner-gravity" / "scripts" / "observe.py"
CHECK_SYNC_SCRIPT = REPO_ROOT / "Project" / "Inner Gravity" / "check_sync.py"
INDEX_SCRIPT = SCRIPTS_DIR / "crucible_index.py"

if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import crucible_index  # noqa: E402
import test_quality_gate  # noqa: E402


def _load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestGovernanceSubsystems(unittest.TestCase):
    """Falsifying tests for test_quality_gate, observe.py, check_sync.py, shim, and fresh-clone doctor."""

    def test_tqg_tq01_tautology_and_zero_assert(self) -> None:
        bad_zero = "def test_empty():\n    x = 1 + 1\n"
        bad_true = "def test_true():\n    assert True\n"
        bad_self_eq = "def test_self():\n    x = 3\n    assert x == x\n"
        bad_unittest_eq = (
            "import unittest\n"
            "class T(unittest.TestCase):\n"
            "    def test_same(self):\n"
            "        self.assertEqual(len('ab'), len('ab'))\n"
        )
        for src in (bad_zero, bad_true, bad_self_eq, bad_unittest_eq):
            findings = test_quality_gate.check_test_source(src, "test_sample.py")
            self.assertTrue(any(f.rule_id == "TQ-01" for f in findings), f"Missed TQ-01 for:\n{src}")

        clean = "def test_real():\n    assert sum([1, 2]) == 3\n"
        self.assertEqual(test_quality_gate.check_test_source(clean, "test_sample.py"), [])

    def test_tqg_tq02_skip_and_tq03_machine_path(self) -> None:
        skip_dec = "import pytest\n@pytest.mark.skip(reason='later')\ndef test_s():\n    assert 1 == 2\n"
        skip_body = (
            "import unittest\nclass T(unittest.TestCase):\n"
            "    def test_s(self):\n        self.skipTest('x')\n        self.assertEqual(1, 1)\n"
        )
        for src in (skip_dec, skip_body):
            findings = test_quality_gate.check_test_source(src, "test_skip.py")
            self.assertTrue(any(f.rule_id == "TQ-02" for f in findings), f"Missed TQ-02 for:\n{src}")

        home_literal = "/ho" + "me/alice/repo/"
        win_literal = "C:" + "\\\\Users\\\\alice\\\\repo"
        uuid_literal = "session_id" + "='12345678-1234-1234-1234-123456789abc'"
        for bad_val in (home_literal, win_literal, uuid_literal):
            src = f'def test_path():\n    val = "{bad_val}"\n    assert val != ""\n'
            findings = test_quality_gate.check_test_source(src, "test_port.py")
            self.assertTrue(any(f.rule_id == "TQ-03" for f in findings), f"Missed TQ-03 for {bad_val}: {findings}")

        clean = "from pathlib import Path\ndef test_rel():\n    assert Path('README.md').name == 'README.md'\n"
        self.assertEqual(test_quality_gate.check_test_source(clean, "test_port.py"), [])

    def test_tqg_tq04_tq05_and_syntax_error(self) -> None:
        only_false = "def test_hooks():\n    run_doctor(repo, execute_hooks=False)\n    assert True is not False\n"
        f_tq04 = test_quality_gate.check_test_source(only_false, "test_hooks.py")
        self.assertTrue(any(f.rule_id == "TQ-04" for f in f_tq04))

        happy_only = (
            "def test_one():\n    assert 1 + 1 == 2\n"
            "def test_two():\n    assert 'a'.upper() == 'A'\n"
        )
        f_tq05 = test_quality_gate.check_test_source(happy_only, "test_happy.py")
        self.assertTrue(any(f.rule_id == "TQ-05" for f in f_tq05))

        f_syntax = test_quality_gate.check_test_source("def test_bad(:\n", "test_bad.py")
        self.assertTrue(any(f.rule_id == "TQ-SYNTAX" for f in f_syntax))

        with tempfile.TemporaryDirectory() as tmp:
            bad_file = Path(tmp) / "test_cli_bad.py"
            bad_file.write_text(only_false, encoding="utf-8")
            rc_bad = test_quality_gate.main(["--json", str(bad_file)])
            self.assertEqual(rc_bad, 1)

    def test_observe_cli_writes_atomic_receipts_and_rejects_invalid_payloads(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            artifact_dir = Path(tmp) / "artifacts"
            artifact_dir.mkdir()

            for event, extra in (
                ("session-start", {}),
                ("stop", {"executionNum": 1, "terminationReason": "NO_TOOL_CALL", "fullyIdle": True}),
            ):
                payload = {
                    "conversationId": "conv-test-001",
                    "artifactDirectoryPath": str(artifact_dir),
                    "modelName": "test-model",
                    **extra,
                }
                proc = subprocess.run(
                    [sys.executable, str(OBSERVE_SCRIPT), event],
                    input=json.dumps(payload),
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    check=False,
                )
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(json.loads(proc.stdout), {})

            receipt_dir = artifact_dir / "inner-gravity-observations"
            json_files = sorted(receipt_dir.glob("*.json"))
            tmp_files = list(receipt_dir.glob("*.tmp"))
            self.assertEqual(len(json_files), 2)
            self.assertEqual(tmp_files, [])

            events_seen = {}
            for jf in json_files:
                data = json.loads(jf.read_text(encoding="utf-8"))
                self.assertEqual(data["schema"], "inner-gravity-lifecycle/v1")
                self.assertEqual(data["session"], "conv-test-001")
                events_seen[data["event"]] = data
            self.assertEqual(set(events_seen.keys()), {"session-start", "stop"})
            self.assertEqual(events_seen["stop"]["attempt"], 1)
            self.assertEqual(events_seen["stop"]["termination_reason"], "NO_TOOL_CALL")

            # Negative paths: relative dir, missing conversationId, invalid JSON stdin
            for bad_stdin in (
                json.dumps({"conversationId": "c1", "artifactDirectoryPath": "relative/dir"}),
                json.dumps({"artifactDirectoryPath": str(artifact_dir)}),
                "{not-json",
            ):
                bad_proc = subprocess.run(
                    [sys.executable, str(OBSERVE_SCRIPT), "stop"],
                    input=bad_stdin,
                    capture_output=True,
                    text=True,
                    encoding="utf-8",
                    check=False,
                )
                self.assertEqual(bad_proc.returncode, 0)
                self.assertEqual(json.loads(bad_proc.stdout), {})
            self.assertEqual(len(list(receipt_dir.glob("*.json"))), 2)

    def test_check_sync_locks_root_installs_and_plugin_zips(self) -> None:
        check_sync = _load_module(CHECK_SYNC_SCRIPT, "crucible_check_sync")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "workspace"
            root.mkdir()
            self.assertEqual(check_sync.check_sync_locks(root), [])
            (root / ".tmp.driveupload").mkdir()
            self.assertEqual(check_sync.check_sync_locks(root), [".tmp.driveupload"])

            missing_installs = check_sync.check_root_installs(root)
            self.assertFalse(any(missing_installs.values()))

            (root / "IDEAS.md").write_text("# Ideas\n", encoding="utf-8")
            (root / "AGENTS.md").write_text("# Agents\n", encoding="utf-8")
            (root / ".agents" / "plugins" / "demo-plug").mkdir(parents=True)
            (root / ".agents" / "acceptance.lock.json").write_text("{}", encoding="utf-8")
            present_installs = check_sync.check_root_installs(root)
            self.assertTrue(all(present_installs.values()))

            zips_dir = root / "zips"
            zips_dir.mkdir()
            good_zip = zips_dir / "demo-plug.zip"
            with zipfile.ZipFile(good_zip, "w") as zf:
                zf.writestr("demo-plug/plugin.json", '{"name": "demo-plug"}')

            corrupt_zip = zips_dir / "broken.zip"
            corrupt_zip.write_text("not a zip archive", encoding="utf-8")

            before = check_sync.check_plugin_zips(root)
            by_zip = {str(entry["zip"]).replace("\\", "/"): entry for entry in before}
            self.assertFalse(by_zip["zips/demo-plug.zip"]["extracted"])
            self.assertIn("error", by_zip["zips/broken.zip"])

            (root / ".agents" / "plugins" / "demo-plug" / "plugin.json").write_text(
                '{"name": "demo-plug"}',
                encoding="utf-8",
            )
            after = check_sync.check_plugin_zips(root)
            by_zip_after = {str(entry["zip"]).replace("\\", "/"): entry for entry in after}
            self.assertTrue(by_zip_after["zips/demo-plug.zip"]["extracted"])

    def test_crucible_index_shim_exports_all_and_cli_runs(self) -> None:
        for sym in crucible_index.__all__:
            self.assertTrue(hasattr(crucible_index, sym), f"Missing shim export: {sym}")
            self.assertIsNotNone(getattr(crucible_index, sym))

        proc = subprocess.run(
            [sys.executable, str(INDEX_SCRIPT), "--root", str(REPO_ROOT), "doctor", "--json", "--no-global", "--skip-exec"],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )
        self.assertEqual(proc.returncode, 0, proc.stdout + proc.stderr)
        doc = json.loads(proc.stdout)
        self.assertTrue(doc["ok"])
        self.assertGreaterEqual(doc["metrics"]["indexed_total"], 120)

    def test_doctor_fresh_clone_missing_empty_domain_dirs_is_info_not_fail(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "fresh_clone"
            agents_scripts = repo / ".agents" / "scripts"
            agents_scripts.mkdir(parents=True)
            (agents_scripts / "smoke_hook.py").write_text("print('{}')\n", encoding="utf-8")
            (repo / "README.md").write_text(
                "# Crucible Domain\n"
                "- [CPL](Calgary%20Public%20Library)\n"
                "- [Personal](Personal%20Work)\n"
                "- [Graphs](Graphs)\n",
                encoding="utf-8",
            )
            (repo / ".agents" / "hooks.json").write_text(
                json.dumps(
                    {
                        "smoke": {
                            "enabled": True,
                            "SessionStart": [
                                {"type": "command", "command": "python scripts/smoke_hook.py"}
                            ],
                        }
                    }
                ),
                encoding="utf-8",
            )
            # Live execute_hooks=True sibling check (satisfies TQ-04 cleanly).
            live_report = crucible_index.run_doctor(repo, global_config_dir=None, execute_hooks=True)
            self.assertTrue(live_report.ok, [f.to_dict() for f in live_report.findings])
            self.assertEqual(live_report.fail_count, 0)
            info_items = [
                f for f in live_report.findings if f.category == "portability" and f.severity == "INFO"
            ]
            self.assertEqual(len(info_items), 3)

            # Negative path: real broken link inside README.md must FAIL even with fresh-clone rule.
            (repo / "README.md").write_text(
                "# Crucible Domain\n- [CPL](Calgary%20Public%20Library)\n- [Broken](missing_doc.md)\n",
                encoding="utf-8",
            )
            bad_report = crucible_index.run_doctor(repo, global_config_dir=None, execute_hooks=False)
            self.assertFalse(bad_report.ok)
            link_fails = [f for f in bad_report.findings if f.category == "links" and f.severity == "FAIL"]
            self.assertEqual(len(link_fails), 1)
            self.assertIn("missing_doc.md", link_fails[0].detail)


if __name__ == "__main__":
    unittest.main()
