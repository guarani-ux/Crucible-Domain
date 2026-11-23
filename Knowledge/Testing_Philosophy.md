# Crucible Domain Testing Philosophy (`K-TEST-01`)

> **Core Principle:** A test does not exist to prove code runs—it exists to **name one real failure you refuse to tolerate, fail loudly when that failure happens, and state which rung of reality is still unproven.**

---

## 1. The 4 Evidence Rungs (Report Rungs, Not Raw Pass Counts)

| Rung | What It Tests | Passing Proves | Passing Does NOT Prove |
| :--- | :--- | :--- | :--- |
| **Rung 1 · Mechanical Invariant** | Deterministic scripts & rules ([crucible_gate.py](../.agents/scripts/crucible_gate.py), [check_artifact.py](../.agents/plugins/inner-gravity/skills/ig-reconcile/scripts/check_artifact.py), [crucible_index.py](../.agents/scripts/crucible_index.py)) | A specific forbidden action is physically blocked on disk or in CLI/RAM (`TQ-01..TQ-05` clean). | That tests fail if the guard is deleted, or that agents make good editorial/domain judgments. |
| **Rung 2 · Red-First & Mutation Kill** | Running a new test **before** the fix (or breaking a guard via a temporary mutant) | The test genuinely turns **RED** when the promise breaks—eliminating "made-to-pass" checks. | That prompts, skills, or subagents catch subtle real-world context failures. |
| **Rung 3 · Planted-Defect Behavioral Eval** | Running an auditor/router (`ig-evidence-review`, RAM lexical benchmark) blindly against known planted bugs + a clean control | The judgment layer actually detects planted defects (`+4s` drift, fake URLs, inferred approvals) with low false alarms (`K-ARCH-02`). | That a real human colleague in their workplace can act on a real deliverable without help. |
| **Rung 4 · Field / Receiver Proof** | Real deliverable opened by its actual recipient (`G05`) in the real environment | The system worked end-to-end for its human purpose with zero reconstruction. | Permanent immunity—drift returns unless Rungs 1–3 stay active. |

---

## 2. The 3 Non-Negotiable Test Laws

1. **Name the failure, not the function.** Every test's docstring or name states in one line *what breaks for the user/workflow if this guard lies*. If no real failure can be named, delete the test.
2. **Pair every `allow` with a `deny` on the exact seam.** Never test only happy paths or only failure triggers. Every boundary test must prove both sides: clean input passes, broken input blocks—and clearing the defect flips the result back.
3. **Never trust a test you never saw RED.** Either observe a new test fail **before** implementing the fix, or kill a temporary mutant of the guard under test before claiming verification.

---

## 3. Minimum Python Test Template & Mechanical Enforcement

```python
def test_blocks_real_failure_and_allows_valid_case(self) -> None:
    """Fails if <specific invariant> silently allows <specific bad state>."""
    with tempfile.TemporaryDirectory() as tmp:  # Portable, zero host/UUID coupling (TQ-03)
        # 1. Negative / Reject side FIRST (assertIn("BLOCKED:", ...) or assertRaises(...))
        # 2. Positive / Allow side on the same seam (zero assert True / x == x)
        # 3. Live execution when testing hooks (never pass execute_hooks=False in a 'live' test)
```

- **Crucible Suites & Fixtures:** [.agents/scripts/tests/](../.agents/scripts/tests/) · [Rung-3 Planted-Defect Eval](../.agents/scripts/tests/fixtures/rung3_planted_defect_eval/SCORING_KEY.md) · `C:/Users/flowe/.gemini/config/scripts/test_quality_gate.py` (AST `TQ-01..TQ-05`)
