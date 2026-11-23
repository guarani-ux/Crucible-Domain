#!/usr/bin/env python3
"""Isolated tests for Knowledge/outcome_ledger.json, Bayesian routing priors, and risk escalation."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
GATE_SCRIPT = SCRIPTS_DIR / "crucible_gate.py"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from crucible import ledger as ledger_mod  # noqa: E402
from crucible.models import CapabilityEntry, CapabilityIndex  # noqa: E402
from crucible.router import route_query  # noqa: E402


def _git(repo: Path, *args: str) -> None:
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
        raise RuntimeError(f"git {' '.join(args)} failed: {proc.stderr or proc.stdout}")


class TestOutcomeLedgerAndLearning(unittest.TestCase):
    """Verify ledger validation, bounded Bayesian routing, and git-churn risk escalation."""

    def test_ledger_schema_validation_rejects_corrupt_entries(self) -> None:
        valid = ledger_mod.empty_ledger()
        self.assertEqual(ledger_mod.validate_ledger(valid), [])

        bad_version = {**valid, "schema_version": 99}
        self.assertTrue(ledger_mod.validate_ledger(bad_version))

        bad_alpha = {
            **valid,
            "capability_priors": {
                "PRIM-01": {"alpha": 0.0, "beta": 1.0, "trials": 1, "verified_passes": 0, "verified_fails": 1}
            },
        }
        self.assertTrue(ledger_mod.validate_ledger(bad_alpha))

        bad_risk = {
            **valid,
            "file_risk": {"foo.py": {"commits": 2, "fix_commits": 1, "risk_score": 1.5}},
        }
        self.assertTrue(ledger_mod.validate_ledger(bad_risk))

        bad_verdict = {
            **valid,
            "events": [{"source": "ci:1", "verdict": "MAYBE"}],
        }
        self.assertTrue(ledger_mod.validate_ledger(bad_verdict))

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            with self.assertRaises(ValueError):
                ledger_mod.record_outcome(root, source="ci:1", verdict="BOGUS")

    def test_adaptive_routing_lifts_proven_pass_over_fail_and_respects_no_learn(self) -> None:
        doc_a = CapabilityEntry(
            id="DOC-A",
            kind="doc",
            title="Workflow Architecture Guide",
            path="docs/a.md",
            line=1,
            domain="systems",
            summary="Workflow architecture routing checklist.",
            use_when="workflow architecture",
            reachability="local",
        )
        doc_b = CapabilityEntry(
            id="DOC-B",
            kind="doc",
            title="Workflow Architecture Guide",
            path="docs/b.md",
            line=1,
            domain="systems",
            summary="Workflow architecture routing checklist.",
            use_when="workflow architecture",
            reachability="local",
        )
        noise = CapabilityEntry(
            id="NOISE-1",
            kind="doc",
            title="Unrelated Cooking Note",
            path="docs/n.md",
            line=1,
            domain="general",
            summary="Soup recipe.",
            use_when="kitchen",
            reachability="local",
        )
        idx = CapabilityIndex(
            root=".",
            entries={"DOC-A": doc_a, "DOC-B": doc_b, "NOISE-1": noise},
            alias_map={"doc-a": "DOC-A", "doc-b": "DOC-B", "noise-1": "NOISE-1"},
            chatgpt_bindings={},
            counts_by_kind={"doc": 3},
            skill_frontmatter_bytes=0,
            build_ms=1.0,
        )

        # Static baseline breaks ties alphabetically: DOC-A precedes DOC-B.
        static_res = route_query(idx, "workflow architecture", ledger=None)
        self.assertEqual([m.entry.id for m in static_res.matches[:2]], ["DOC-A", "DOC-B"])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "repo"
            root.mkdir()
            ledger_mod.record_outcome(root, source="ci:1", verdict="PASS", capabilities=["DOC-B"])
            ledger_mod.record_outcome(root, source="ci:2", verdict="PASS", capabilities=["DOC-B"])
            ledger_mod.record_outcome(root, source="ci:3", verdict="FAIL", capabilities=["DOC-A"])
            learned = ledger_mod.load_ledger(root)

            learned_res = route_query(idx, "workflow architecture", ledger=learned)
            self.assertEqual([m.entry.id for m in learned_res.matches[:2]], ["DOC-B", "DOC-A"])
            self.assertGreater(learned_res.matches[0].score, learned_res.matches[1].score)
            self.assertIn("prior=", learned_res.matches[0].matched_via)

            # Exact ID lookups must NEVER be overridden by learned priors.
            exact_res = route_query(idx, "DOC-A", ledger=learned)
            self.assertEqual(exact_res.match_mode, "exact")
            self.assertEqual(exact_res.matches[0].entry.id, "DOC-A")

    def test_git_file_risk_and_escalation_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp) / "repo"
            repo.mkdir()
            _git(repo, "init")
            _git(repo, "config", "user.name", "Test User")
            _git(repo, "config", "user.email", "test@example.com")

            (repo / "IDEAS.md").write_text("# Ideas\n", encoding="utf-8")
            (repo / "flaky.py").write_text("x = 1\n", encoding="utf-8")
            (repo / "steady.md").write_text("# Steady\n", encoding="utf-8")
            _git(repo, "add", ".")
            _git(repo, "commit", "-m", "Initial baseline")

            for i in range(4):
                (repo / "flaky.py").write_text(f"x = {i + 2}\n", encoding="utf-8")
                _git(repo, "add", "flaky.py")
                _git(repo, "commit", "-m", f"fix: patch regression #{i + 1}")

            ledger = ledger_mod.record_outcome(
                repo,
                source="ci:test",
                verdict="PASS",
                refresh_git=True,
            )
            self.assertGreater(
                ledger["file_risk"]["flaky.py"]["risk_score"],
                ledger["file_risk"]["steady.md"]["risk_score"],
            )

            esc = ledger_mod.assess_risk(ledger, ["flaky.py"], threshold=0.45)
            self.assertTrue(esc["escalate"])
            self.assertIn("flaky.py", esc["high_risk_files"])
            self.assertIn("ESCALATE:", esc["recommended_action"])

            ref = ledger_mod.assess_risk(ledger, [".agents/scripts/crucible_gate.py"], threshold=0.95)
            self.assertTrue(ref["escalate"])
            self.assertIn(".agents/scripts/crucible_gate.py", ref["referee_touched"])

            clean = ledger_mod.assess_risk(ledger, ["steady.md"], threshold=0.45)
            self.assertFalse(clean["escalate"])
            self.assertIn("STANDARD:", clean["recommended_action"])

            proc = subprocess.run(
                [sys.executable, str(GATE_SCRIPT), "--root", str(repo), "risk", "flaky.py", "--json"],
                cwd=repo,
                capture_output=True,
                text=True,
                encoding="utf-8",
                check=False,
            )
            self.assertEqual(proc.returncode, 0, proc.stderr)
            cli_payload = json.loads(proc.stdout)
            self.assertTrue(cli_payload["escalate"])


if __name__ == "__main__":
    unittest.main()
