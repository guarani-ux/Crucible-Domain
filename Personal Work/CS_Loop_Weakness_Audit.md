---
title: Crucible Loop — Forensic CS Weakness & Unleveraged-Domain Audit
status: resolved
branch: main
depends_on:
  - .agents/scripts/crucible/tx_patch.py
  - .agents/scripts/crucible/campaign_ir.py
  - scripts/verify_all.ps1
depends_on_sha256:
  .agents/scripts/crucible/tx_patch.py: 857e9e127769200bd5e8950c75081f961ace38066f219bacbc5d99b7dc86d984
  .agents/scripts/crucible/campaign_ir.py: 19fc7539243cd6473d99a37b7677ac3284e26cd164be5fd704639ebd81cd9bce
  scripts/verify_all.ps1: dba15afec46ba76bf13b40491a3005ccaa13554ba9b570f77cf575e23cdb9567
---

# Crucible Loop — Forensic CS Weakness & Unleveraged-Domain Audit

> **Scope:** Historical code-grounded audit of the `crucible-loop` v3 stack (`tx_patch.py`, `campaign_ir.py`, `verify_all.ps1`) whose weaknesses (`W1`–`W6`) and previously unleveraged CS domains are now resolved across Waves 1–4.5 on `main` (see Section 2 and Section 4 below).

---

## 1. Observed Weaknesses in Live Code (Layer-3 Mechanics)

| # | Component | Observed Physical Weakness | Missing CS Domain Primitive | Concrete Fix |
| :---: | :--- | :--- | :--- | :--- |
| **W1** | `tx_patch.py` (`commit()`) | Loops `os.replace()` one file at a time. If file #3 fails (e.g., Windows file lock or permission error), files #1 and #2 remain mutated on disk — **not true multi-file Atomicity**. | **Database Recovery (WAL / Undo Journal)** | Snapshot `before_bytes` in RAM; on any mid-commit exception, restore already-written files in reverse order before re-raising. |
| **W2** | `campaign_ir.py` (`hash_error_output()`) | Hashes raw error text. Identical bugs with changing temp paths (`pytest-21` vs `pytest-22`), timestamps, or memory addresses (`0x...`) produce different hashes, **defeating the circuit breaker**. | **Program Analysis (Canonical Stack Fingerprinting)** | Strip volatile tokens (timestamps, `tmp_path` run IDs, hex addresses, line-timing durations) before hashing `error_sha256`. |
| **W3** | `campaign_ir.py` (`compute_slice_input_sha256()`) | Only hashes `target_paths`, ignoring imported/read dependencies. Editing a shared module (`tx_patch.py`) will not invalidate a downstream slice unless manually listed. | **Static Program Analysis (`ast` Import Graph)** | Parse Python `import` / `from ... import` edges via `ast` to include local transitive dependencies in `input_sha256`. |
| **W4** | `campaign_ir.py` (`_topological_order()`) | Flattens the DAG into a serial list instead of grouping independent slices into **parallel execution waves**. | **Parallel Compilers (DAG Levelization / Critical Path)** | Emit `list[list[PlannedSlice]]` waves so independent slices can run concurrently or be sharded cleanly. |
| **W5** | `campaign_ir.py` (`save_receipt_cache()`) | Read-modify-write on `receipts.json` has no concurrency control; two parallel workers updating the cache suffer a **lost update**. | **Concurrency Control (Optimistic CAS / File Lock)** | Compare-and-swap on file SHA-256 (or merge-on-write with lockfile) before `os.replace()`. |
| **W6** | `scripts/verify_all.ps1` | Runs all 4 checks serially (~21s) on every round even when only 1 doc or 1 module changed. | **OS Parallelism + Test Impact Analysis (TIA)** | Run independent checks concurrently (`Start-ThreadJob` / parallel jobs) and add a `--fast` mode that runs only tests affected by `git diff`. |

---

## 2. Previously Unleveraged CS Domains (Resolved in Waves 1–4.5)

1. **Formal State Machines (Round Lifecycle Enforcement) — RESOLVED (`LoopStateMachine`, `7abe2f6`):**
   - *Gap:* The `PLAN -> STAGE -> VERIFY -> COMMIT -> CACHE` cycle was enforced by prompt prose in `SKILL.md`, not by code.
   - *CS Primitive:* **Finite State Machine (FSM)** controller that rejects `COMMIT` unless `VERIFY` passed on the exact staged `after_sha256`.
2. **Programming Languages (Design-by-Contract on Spoke Boundaries) — RESOLVED (`contracts.py`, Slice `#8`):**
   - *Gap:* Hub <-> Spoke JSON-RPC calls lacked machine-checked pre/post-condition contracts.
   - *CS Primitive:* **Refinement Types / Runtime Contracts** (`SpokeContract`, `verify_spoke_call`, `snapshot_roots`) validating preconditions, postconditions, and SHA-256 `unchanged_roots` frame invariants at the spoke boundary.
3. **Information Retrieval (BM25 + Graph-Walk Orientation) — RESOLVED (`router.py`, Slice `#7`, `ee42caa`):**
   - *Gap:* `crucible_gate.py route` used basic lexical matching.
   - *CS Primitive:* Zero-dependency local **BM25 + bounded `k`-hop dependency-graph ranking** in `router.py` inside the sub-100ms RAM budget.
4. **Distributed Systems (Append-Only Event Sourcing / Ratchet Ledger) — RESOLVED (`append_ratchet_ledger`, `7abe2f6`):**
   - *Gap:* Receipts were overwritten in `receipts.json` rather than appended as a replayable history.
   - *CS Primitive:* **Append-Only TSV/JSONL Event Log** (`results.tsv`, `replay_trace.jsonl`) turning every real campaign round into an offline regression fixture.

---

## 3. Recommended Hardening Order (Highest Leverage / Lowest Complexity)
1. **Slice A (`W1` + `W2`):** Add multi-file rollback journal to `tx_patch.py` + volatile-token canonicalization to `hash_error_output()` in `campaign_ir.py` (~40L total, immediate reliability jump).
2. **Slice B (`W3` + `W4`):** Add `ast` local-import hashing + parallel DAG wave emission to `campaign_ir.py`.
3. **Slice C (`W6`):** Parallelize `scripts/verify_all.ps1` (cut verification wall-clock time by ~60%).

---

## 4. Resolution Log
- **W1** (Multi-file rollback journal in `tx_patch.py`): **RESOLVED** (`b857c43`)
- **W2** (Canonical volatile-token error hashing in `campaign_ir.py`): **RESOLVED** (`b857c43`)
- **W3** (`ast` local-import dependency hashing in `campaign_ir.py`): **RESOLVED** (Round 03/12)
- **W4** (Parallel DAG `execution_waves` in `campaign_ir.py`): **RESOLVED** (Round 03/12)
- **W5** (Optimistic CAS `save_receipt_cache_cas` + `merge_receipt_cache` in `campaign_ir.py`): **RESOLVED** (`7abe2f6`, Round 01/12)
- **W6** (Parallel `scripts/verify_all.ps1` via Python `ThreadPoolExecutor` + scoped spoke tests): **RESOLVED** (Round 04/12)
- **Formal State Machines** (`LoopStateMachine` enforcing `PLAN -> STAGE -> VERIFY -> COMMIT -> CACHE` in `campaign_ir.py`): **RESOLVED** (`7abe2f6`, Round 01/12)
- **Append-Only Ratchet Ledger** (`append_ratchet_ledger` / `load_ratchet_ledger` TSV log in `campaign_ir.py` + `crucible_gate.py campaign ledger`): **RESOLVED** (`7abe2f6`, Round 01/12 + Round 02/12)
- **BM25 + Graph-Walk Retrieval** (`route_query` in `router.py`, Slice `#7`): **RESOLVED** (`ee42caa`)
- **Spoke Design-by-Contract** (`SpokeContract` / `verify_spoke_call` in `contracts.py`, Slice `#8`): **RESOLVED** (`test_contracts.py`)
- **Z3 Wave Feasibility + Replay Loop + Unified Story Engine + CD-W19/20** (`solver.py`, `replay_loop.py`, `story_engine.py`, `doctor.py`, `outcome_ledger.py`): **RESOLVED** (`a3b9f4a`, Wave 4.5)
