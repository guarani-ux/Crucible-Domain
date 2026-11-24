---
title: Crucible Domain — Code Process Validity & Engineering Maturity Scorecard
status: active
depends_on:
  - Personal Work/GROUND_TRUTH.md
  - Knowledge/Testing_Philosophy.md
depends_on_sha256:
  Personal Work/GROUND_TRUTH.md: 2fed8f09aecaeb1f012d4abb54fb719cfdc2f0fd01a1ea46c5cfada28bcaba09
  Knowledge/Testing_Philosophy.md: 20f4c10237a94d563a8d221e67c513cecee487721e284199f04adbb33cd664ab
---

# Crucible Domain — Code Process Validity & Engineering Maturity Scorecard

> **Purpose:** Reusable operational scorecard for measuring the validity, determinism, fault isolation, spoke portability, verification rigor, and formal bounds of `Crucible Domain` as a **sovereign systems-engineering platform (`PW-01`)** across waves. Domain capabilities (`Calgary Public Library`, `Story-Lane`, `Writer's Room`, `Meeting Prep`, `Crucible Observatory`) are plug-in features exercised on top of this engine and tracked separately from systems-builder maturity.
> **Rule (`K-TEST-01` / `G5`):** Scores require observable code mechanisms, measured non-vanity metrics (`outcome_ledger.py`), and explicit bottleneck/ceiling disclosure—never commit counts, LOC, or unverified claims.

---

## 1. Wave Comparison Scorecard (`ec89956` Baseline -> Wave 4.5 Verified)

| Dimension | Baseline (`ec89956`, Waves 1–4 Verified) | Wave 4.5 (`beast_gohan_mastered_god_ki`, Observed Local Run) | Systems-Builder Bottleneck / Honest Ceiling |
| :--- | :--- | :--- | :--- |
| **Determinism & Token Economy** | **9.5/10** — ~34ms in-RAM index, ML test-ranker, AST `TQ-01..05`, `campaign_ir.py` SHA-256 skip (`0` LLM tokens on unchanged slices). | **9.5/10** — Adds in-RAM AST gap discovery (`replay_loop.py`: `516` units / `492` edges in `~524ms`) + DP story-arc clip selection (`story_engine.py`) with `0` LLM calls. | `ram_ml_engine.py` generalizes only as far as local curated history; `verify_all.ps1` wall-clock is gated by sequential `mutation_gate.py` (~86s). |
| **Fault Isolation & Recovery** | **8.5/10** — `tx_patch.py` atomic `os.replace` + `before_bytes` rollback, `LoopStateMachine`, `ErrorCircuitBreaker`, `save_receipt_cache_cas`. | **9.2/10** — Adds isolated git worktree execution + double-run replay verification + automatic fault rollback (`VerifiedDiff`, `replay_loop.py`). | `discover` synthesizes `CampaignSpec` slices, but deterministic autofixers are not yet wired directly into `campaign run --worktree --replay-out`. |
| **Spoke Architecture (`K-MCP-01`)** | **8.0/10** — 3-tool stdio JSON-RPC spokes (`writers-room`, `story-lane`, `meeting-prep`, `crucible-observatory`), `contracts.py` frame invariants, `12` hardcoded `C:/` paths in `mcp_config.json` (`CD-W14`). | **9.0/10** — `CD-W19` removes hardcoded paths across all 4 `mcp_config.json` files (`doctor`: `23 PASS \| 0 WARN \| 0 FAIL`); `story_engine.py` unifies form grammars, DP clip selection, and `CHG-01` SHA-256 invalidation (`storylane_spoke` 9/9 tests). | Sibling spoke repos (`story-lane`, `the-writers-room`) assume a co-located sibling directory layout (`../crucible-spokes/...`, `../the-writers-room`). |
| **Verification Rigor (`K-TEST-01`)** | **9.0/10** — 20/20 parallel checks, `5/5` mutation kills (`mutation_gate.py`), 220-case property fuzzing, `TQ-01..TQ-05` AST test gate. | **9.3/10** — `22/22` parallel checks (`verify_all.ps1`), `5/5` mutation kills, replay-drift checks, and `10/10` non-vanity improvements (`outcome_ledger.py` `g5-check`). | `mutation_gate.py` currently kills 5 Hub-gate mutations sequentially (~86s) and does not yet mutate `replay_loop.py` or `story_engine.py` invariants. (Domain-plugin Rung-4 receipts are tracked separately per domain.) |
| **Formal & Constraint Guarantees** | **8.5/10** — Kahn's topological sort + Z3 SAT/SMT wave feasibility (`solver.py`, bounded to `finite_encoded_constraints_only`). | **8.8/10** — Adds formal form grammars and exact DP interval/arc selection (`story_engine.py`). | Bounded model checks only (`proves_unbounded_correctness=False`); no OS-level binary/syscall taint sandboxing beyond path containment and hooks. |

---

## 2. Scoring & Validity Protocol (Per-Wave Update Rules)

1. **Observable Evidence Binding (`K-ARCH-03`):** Every Baseline or Post-Wave cell must cite the exact commit SHA, verification command (`pwsh -File scripts/verify_all.ps1`, `python .agents/scripts/mutation_gate.py --json`, `crucible_gate.py doctor`), and pass/kill counts observed **after** the final edit.
2. **Non-Vanity Metric Gate (`CD-W20` / `outcome_ledger.py`):** Record measurable operator-workload, latency, defect-detection, or portability gains (`higher_is_better` / `lower_is_better`) backed by `verify_cmd` and `evidence_sha256`. Reject `commit`, `loc`, `line_count`, and `files_touched`.
3. **Explicit Ceiling Disclosure:** Never claim `10/10` while either (a) Rung-4 external recipient sign-off remains unexercised on a workstream deliverable, or (b) full-suite verification latency or sibling-layout coupling creates real operator friction.
4. **3-Arm Control Discipline (`K-TEST-01`):** Any score increase requires at least one clean positive case, one planted-fault/stale-SHA rejection case, and one unrelated negative control verified in automated tests.
