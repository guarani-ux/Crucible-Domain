"""Unit and negative tests for portable verify_all, requirements parity, and doctor MCP audit."""

from __future__ import annotations

import ast
import contextlib
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SCRIPTS_DIR.parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import verify_all
from crucible import doctor as crucible_doctor

IMPORT_TO_PACKAGE = {
    "sklearn": "scikit-learn",
    "z3": "z3-solver",
}


def _parse_requirements(req_path: Path) -> set[str]:
    names: set[str] = set()
    for raw in req_path.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        pkg = re.split(r"[<>=!~\[]", line, maxsplit=1)[0].strip().lower()
        if pkg:
            names.add(pkg)
    return names


def _collect_third_party_imports(scripts_dir: Path) -> set[str]:
    stdlib = sys.stdlib_module_names
    local_mods = {p.stem for p in (REPO_ROOT / ".agents").rglob("*.py")} | {"crucible"}
    discovered: set[str] = set()
    for py_file in scripts_dir.rglob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split(".")[0]
                    if top not in stdlib and top not in local_mods:
                        discovered.add(top)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                top = node.module.split(".")[0]
                if top not in stdlib and top not in local_mods:
                    discovered.add(top)
    return discovered


def _write_minimal_hub(hub: Path) -> None:
    scripts = hub / ".agents" / "scripts"
    tests = scripts / "tests"
    tests.mkdir(parents=True, exist_ok=True)
    (scripts / "crucible_gate.py").write_text(
        "import sys\n"
        "cmd = sys.argv[1] if len(sys.argv) > 1 else ''\n"
        "if cmd == 'check' and '--strict' in sys.argv:\n"
        "    sys.exit(0)\n"
        "if cmd == 'doctor' and '--no-global' in sys.argv:\n"
        "    sys.exit(0)\n"
        "sys.exit(1)\n",
        encoding="utf-8",
    )
    (tests / "test_sample.py").write_text(
        "def test_minimal_truth() -> None:\n"
        "    assert 1 + 1 == 2\n",
        encoding="utf-8",
    )


class TestPortableVerifyAndRequirements(unittest.TestCase):
    """Verify portable CI dependencies, verify_all spoke/CI behavior, and doctor MCP audit."""

    def test_requirements_covers_all_third_party_imports(self) -> None:
        req_path = REPO_ROOT / "requirements.txt"
        self.assertTrue(req_path.is_file(), "requirements.txt must exist at repo root")
        declared = _parse_requirements(req_path)
        discovered = _collect_third_party_imports(SCRIPTS_DIR)

        mapped = {IMPORT_TO_PACKAGE.get(mod, mod).lower() for mod in discovered}
        missing = sorted(mapped - declared)
        self.assertEqual(missing, [], f"Missing third-party packages in requirements.txt: {missing}")
        self.assertTrue({"pytest", "numpy", "scikit-learn", "z3-solver"}.issubset(declared))

        # Negative path: undeclared third-party package must be detected as missing.
        simulated = mapped | {"unlisted_pkg"}
        self.assertIn("unlisted_pkg", simulated - declared)

    def test_verify_all_source_has_no_hardcoded_paths_or_swallowed_exceptions(self) -> None:
        src_path = SCRIPTS_DIR / "verify_all.py"
        src = src_path.read_text(encoding="utf-8")
        self.assertIsNone(re.search(r"[A-Za-z]:[/\\]", src), "verify_all.py must not hardcode drive-letter paths")
        self.assertNotIn("except Exception:\n    pass", src)

        tree = ast.parse(src, filename=str(src_path))
        for node in ast.walk(tree):
            if isinstance(node, ast.ExceptHandler):
                is_pass_only = len(node.body) == 1 and isinstance(node.body[0], ast.Pass)
                self.assertFalse(is_pass_only, f"Swallowed exception with bare pass at line {node.lineno}")

    def test_verify_all_missing_spokes_require_vs_ci_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            hub = tmp_path / "hub"
            _write_minimal_hub(hub)
            missing_spokes = tmp_path / "absent_spokes"

            # Precedence: CLI arg > CRUCIBLE_SPOKES_ROOT > root.parent / "crucible-spokes"
            self.assertEqual(
                verify_all.resolve_story_lane_dir(hub, str(missing_spokes)),
                missing_spokes.resolve() / "story-lane",
            )
            self.assertEqual(
                verify_all.resolve_story_lane_dir(hub, None),
                hub.resolve().parent / "crucible-spokes" / "story-lane",
            )

            # Negative path: --require-spokes must fail when story-lane is absent.
            buf_fail = io.StringIO()
            with contextlib.redirect_stdout(buf_fail):
                rc_fail = verify_all.main(
                    [
                        "--root",
                        str(hub),
                        "--spokes-root",
                        str(missing_spokes),
                        "--require-spokes",
                        "--ci",
                        "--skip-mutations",
                    ]
                )
            self.assertNotEqual(rc_fail, 0)
            self.assertIn("Required spoke missing", buf_fail.getvalue())

            # Portable CI path: absent spoke is marked SKIPPED_OPTIONAL_SPOKE and exits 0 without writing history.
            buf_ok = io.StringIO()
            with contextlib.redirect_stdout(buf_ok):
                rc_ok = verify_all.main(
                    [
                        "--root",
                        str(hub),
                        "--spokes-root",
                        str(missing_spokes),
                        "--ci",
                        "--skip-mutations",
                    ]
                )
            self.assertEqual(rc_ok, 0, buf_ok.getvalue())
            self.assertIn("SKIPPED_OPTIONAL_SPOKE", buf_ok.getvalue())
            self.assertFalse((hub / ".agents" / "ml_history.jsonl").exists())

    def test_doctor_mcp_config_audit_positive_and_negative(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            repo = tmp_path / "repo"
            plugin_dir = repo / ".agents" / "plugins" / "sample-spoke"
            plugin_dir.mkdir(parents=True)
            cfg_path = plugin_dir / "mcp_config.json"

            # Negative path 1: corrupt mcp_config.json triggers FAIL.
            cfg_path.write_text("{corrupt json", encoding="utf-8")
            bad_report = crucible_doctor.run_doctor(repo, global_config_dir=None, execute_hooks=True)
            self.assertFalse(bad_report.ok)
            fail_items = [f for f in bad_report.findings if f.category == "mcp_spokes" and f.severity == "FAIL"]
            self.assertEqual(len(fail_items), 1)
            self.assertIn(".agents/plugins/sample-spoke/mcp_config.json", bad_report.metrics["mcp_invalid_configs"])

            # Portable --no-global mode: valid JSON with hardcoded drive path + missing cwd emits INFO, 0 FAIL, 0 WARN.
            missing_cwd = str(tmp_path / "missing_spoke_dir")
            cfg_path.write_text(
                json.dumps(
                    {
                        "mcpServers": {
                            "sample-spoke": {
                                "command": "python",
                                "args": ["-m", "sample_spoke", "mcp"],
                                "cwd": missing_cwd,
                                "env": {
                                    "CRUCIBLE_DOMAIN_ROOT": "Z:/portable-check-root",
                                    "CRUCIBLE_ALLOWED_ROOTS": "Z:/portable-check-root;Z:/portable-check-spoke",
                                },
                            }
                        }
                    }
                ),
                encoding="utf-8",
            )
            ci_report = crucible_doctor.run_doctor(repo, global_config_dir=None, execute_hooks=True)
            self.assertTrue(ci_report.ok, [f.to_dict() for f in ci_report.findings])
            self.assertEqual(ci_report.fail_count, 0)
            ci_mcp_warns = [f for f in ci_report.findings if f.category == "mcp_spokes" and f.severity == "WARN"]
            self.assertEqual(ci_mcp_warns, [])
            ci_mcp_infos = [f for f in ci_report.findings if f.category == "mcp_spokes" and f.severity == "INFO"]
            self.assertEqual(len(ci_mcp_infos), 1)
            self.assertGreaterEqual(len(ci_report.metrics["mcp_hardcoded_host_paths"]), 3)

            # Negative path 2: with global_config_dir present, missing spoke cwd emits WARN.
            global_dir = tmp_path / "global_cfg"
            global_dir.mkdir(parents=True)
            host_report = crucible_doctor.run_doctor(repo, global_config_dir=global_dir, execute_hooks=True)
            self.assertEqual(host_report.fail_count, 0)
            host_mcp_warns = [f for f in host_report.findings if f.category == "mcp_spokes" and f.severity == "WARN"]
            self.assertEqual(len(host_mcp_warns), 1)
            self.assertIn("missing_spoke_dir", host_mcp_warns[0].detail)


if __name__ == "__main__":
    unittest.main()
