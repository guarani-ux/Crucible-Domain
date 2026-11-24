---
depends_on:
  - Personal Work/GROUND_TRUTH.md
  - Graphs/00_System_Atlas_and_Neon_Handoff.md
  - Knowledge/Knowledge_Register.md
depends_on_sha256:
  Graphs/00_System_Atlas_and_Neon_Handoff.md: 7a8a7d3fd2e21c9f14877c12080af561c72dada587138e7ffb414bd510479fe2
---

# Crucible Domain — Computer Science & Engineering Architecture Manual

> **Purpose:** Operational Computer Science, Computer Engineering, and Software Engineering manual governing `Crucible Domain` — mapping degree-level computing foundations (CS2023 undergraduate core, Master's specialization tracks, and PhD evidence standards) directly onto our 16-core hardware configuration, in-RAM transaction engine, DAG compiler, and thin-orchestrator sub-agent loop.
> **Scope:** Sovereign systems engineering (`PW-01`–`PW-03`). Literal CS/CE/SE terminology only: CPU, RAM, disk I/O, OS processes, ASTs, type systems, DAGs, CAS, and state machines.

---

## 1. Foundational Engineering Invariants & Full Computing Stack

Every design decision in `Crucible Domain` obeys four cross-level invariants from *Computer Science: From a Degree to a Working Practice*:

1. **A representation is not the world.** A task record, manifest, or frontmatter entry does not prove target state. Inspect bytes, exit codes, and the receiving boundary directly.
2. **A tool result is not permission.** A SHA-256 digest proves byte identity against a trusted record, not authorization. Scope clearance to actor, action, object, and intended use (`ig-evidence-review`, read-only Asana boundary).
3. **A solution is not its evidence.** Passing unit tests verify only tested inputs. Pair every positive case with deliberate violations, stale-proof controls, and unrelated negative controls.
4. **A method is valuable when the next action improves.** Prefer a deterministic schema and exact hash check over probabilistic inference when the check is decidable; measure recipient usability, intervention count, and wall-clock latency.

### Five-Step Verification Cadence
`Predict expected state` -> `Trace small instance manually` -> `Implement & execute test` -> `Inject realistic fault / stale artifact` -> `Bound assumptions (safety invariant vs. progress condition)`.

### Full Computing Stack Dataflow

```mermaid
flowchart LR
    PROMPT["Contract & Bounded Brief"] --> INF["Information Theory & Neural Inference (KV-Cache / Context Entropy)"]
    INF --> TYPES["PL Type Schemas (CampaignSpec / SliceNode / JSON)"]
    TYPES --> DAG["Compiler DAG & Topological Waves (campaign_ir.py)"]
    DAG --> OS["OS Process & Worktree Isolation (slice-worker / stdio JSON-RPC 2.0)"]
    OS --> DB["Storage ACID & Optimistic CAS (tx_patch.py / os.replace / results.tsv)"]
    DB --> HW["16-Core Hardware Execution (verify_all.ps1 / 34.0 GB RAM)"]
    HW --> CTRL["Formal State Machine & Circuit Breaker (LoopStateMachine / ErrorCircuitBreaker)"]
```

---

## 2. Core CS Curriculum -> Crucible Physical Mapping

Integrates the 17 CS2023 knowledge areas, Master's systems/verification/AI tracks, and PhD empirical evidence patterns into concrete `Crucible Domain` modules:

| CS Discipline & Curriculum Core | Physical Mechanism (CPU / RAM / Disk / AST / Network) | Crucible Domain Implementation & Operational Effect |
| :--- | :--- | :--- |
| **1. Algorithms & Complexity** *(CS2023 `AL`, `MSF`; Master's Track 1)* | Graph reachability, cycle detection, Kahn's topological sort (O(V+E)), levelized wave partitioning, and asymptotic vs. empirical cost separation. | `campaign_ir.py` (`compile_campaign`, `_topological_order`) detects dependency cycles pre-execution and partitions independent slices into parallel `execution_waves`. |
| **2. Data Structures & Graphs** *(CS2023 `AL`, `DM`; Master's Track 8)* | Adjacency lists, typed edge tables (`-->` blocking vs. `-.->` advisory), content-addressable hash maps, and in-RAM flat indexing (~30ms reads vs. cold disk scans). | `router.py` / `indexer.py` serve capability routing in RAM (~30ms); `receipt_cache.json` keys memoized slice outputs by `compute_slice_input_sha256`; `crucible_gate.py` checks `depends_on_sha256` before `mtime`. |
| **3. Operating Systems & Concurrency** *(CS2023 `OS`, `AR`, `SF`, `PDC`; Master's Track 2)* | Memory hierarchy gap (nanosecond L1/RAM vs. millisecond NTFS metadata and process forks), Copy-on-Write Git worktrees, thread pools, and crash-recovery idempotency. | `verify_all.ps1` runs 11 subprocesses concurrently via `ThreadPoolExecutor`; `slice-worker` executes in isolated `Workspace="share"` CoW directories so parallel writes cannot race on a shared working tree. |
| **4. Databases & ACID / CAS** *(CS2023 `DM`, `PDC`; Master's Track 2 & 8)* | In-RAM Copy-on-Write overlay, atomic file swap (`tempfile.mkstemp` + `os.replace()`), `before_bytes` rollback, optimistic Compare-And-Swap, and append-only WAL. | `tx_patch.py` (`TransactionBuffer`) guarantees all-or-nothing multi-file disk commits; `campaign_ir.py` (`save_receipt_cache_cas`, `file_sha256`, `_path_lock`, `merge_receipt_cache`) prevents lost updates via `CacheConflictError`; `append_ratchet_ledger` logs immutable TSV rows to `results.tsv`. |
| **5. Compilers & AST / IR** *(CS2023 `FPL`; Master's Track 3)* | Static typed Intermediate Representation, schema validation, Python bytecode syntax checking (`compile(..., "exec")`), and AST traversal prior to execution. | `campaign_ir.py` lowers JSON specs into typed `CampaignSpec`, `SliceNode`, `PlannedSlice`, and `CompiledCampaign` dataclasses (`CampaignCompileError`); `tx_patch.py` runs `compile()` and `test_quality_gate.py` AST rules in RAM before touching disk. |
| **6. Networks & IPC** *(CS2023 `NC`, `PDC`; Master's Track 2)* | Process-isolated stdio JSON-RPC 2.0 message passing across domain spokes; timeout-as-unknown-outcome semantics requiring state reconciliation prior to retry. | Hub coordinates `.agents/plugins/` spokes (`writers-room`, `crucible-observatory`, `story-lane`) over bounded stdio IPC, keeping third-party parsers out of the Hub process heap. |
| **7. Security & Capabilities** *(CS2023 `SEC`, `SEP`; Master's Track 7)* | Least-privilege object-capability containment, canonical path resolution rejecting directory traversal, and strict separation of untrusted text from capability-bearing code. | `TransactionBuffer._resolve` enforces `is_relative_to(self.root)`; `compile_campaign` enforces `_resolve_allowed_roots` / `_is_within_any`; Asana remains strictly read-only; external/destructive mutations require Tier 1/2 operator gates. |
| **8. Information Theory & Neural Inference** *(CS2023 `AI`, `HCI`; Master's Track 4 & 5)* | Transformer attention dilution over long contexts ("Lost in the Middle"), KV-cache token budgets, matched-arm evaluation, and holding out by task family. | `build_slice_worker_prompt` strips multi-round history and injects only the bounded slice spec, `target_paths`, and `verify_cmd`, preserving token signal-to-noise and separating model proposals from deterministic gate enforcement. |
| **9. Formal Methods & Verification** *(CS2023 `MSF`, `FPL`, `SE`; Master's Track 3 & PhD)* | Deterministic Finite State Machines, safety invariants vs. progress conditions, property-based fuzzing, mutation testing, and falsifiable replication traces. | `LoopStateMachine` rejects illegal round transitions (`StateTransitionError`); `test_property_fuzz_crucible_gate.py` fuzzes 220+ frontmatter states; `mutation_gate.py` and `ErrorCircuitBreaker` verify defect detection and halt duplicate failure loops. |

---

## 3. Hardware-Matched Execution Configuration

Current workstation hardware baseline: **`16` logical CPU cores**, **`34.0 GB` physical RAM**, **`12.4 GB` free RAM**. Every execution primitive is tuned to saturate local I/O and CPU concurrency without exhausting RAM or thrashing NTFS:

| Component | Hardware-Matched Configuration | Physical Rationale & Observed Performance |
| :--- | :--- | :--- |
| **`scripts/verify_all.ps1`** | **`22` concurrent workers** via `ThreadPoolExecutor(max_workers=len(STEPS))`: `Hub Gate (--strict)`, `Hub Doctor`, `Mutation Kill Gate`, `Story-Lane Pytest`, and **`18` Hub `pytest` file workers** (`.agents/scripts/tests/test_*.py`). | Saturates local cores in parallel while isolating each check in its own subprocess (`60-120s` per-step timeout). Full-suite wall-clock is **`~86s`** with `Mutation Kill Gate` (`~15-27s` without mutations). |
| **`.agents/scripts/crucible/tx_patch.py`** | **`TransactionBuffer` in-RAM Copy-on-Write overlay** (`_overlay: dict[Path, bytes | None]`), executed via `python -` without temporary script files. | Absorbs multi-file reads/edits in the `12.4 GB` free RAM budget, runs `validate()` (`compile()`, `json.loads()`, `test_quality_gate.py`) before any syscall writes, then commits atomically via `tempfile.mkstemp` + `os.replace()` with full `before_bytes` rollback on exception. |
| **`.agents/scripts/crucible/campaign_ir.py`** | **DAG wave scheduler + SHA-256 content cache** (`compile_campaign`, `optimize_campaign`, `compute_slice_input_sha256`, `save_receipt_cache_cas`). | Partitions slices into disjoint parallel `execution_waves`, hashes exact target + dependency contents to emit `SKIP_CACHED` at `0` LLM tokens on unchanged inputs, and serializes cache updates via `_path_lock` + CAS digest checks (`CacheConflictError`). |
| **`slice-worker` Sub-Agents** | **`Model="flash"`, `Workspace="share"`**, bounded single-slice prompt (`build_slice_worker_prompt`), strict JSON receipt output. | `Workspace="share"` isolates each parallel worker in a CoW worktree; `Model="flash"` minimizes inference latency and KV-cache footprint for single-slice surgical edits verified by deterministic terminal gates. |

---

## 4. How We Test, Slice & Orchestrate Sub-Agents

### A. Property-Based Fuzzing, Negative Controls & Mutation Rigor
* **Property Fuzzing (`.agents/scripts/tests/test_property_fuzz_crucible_gate.py`):** Uses deterministic stdlib PRNG (`random.Random(20261123)`) to generate `220` randomized frontmatter/SHA-256 cases covering valid block lists, malformed YAML, missing keys, and digest mismatches. Paired with spoke fuzzing (`tests/test_storylane_fuzz_and_replay.py`).
* **Three-Arm Experimental Control:** Every verification suite and handoff check separates: (1) valid clean baseline, (2) deliberate fault / stale-SHA violation (must be rejected by trusted code, not merely noticed in prose), and (3) unrelated negative control (valid adjacent artifacts must remain unblocked).
* **Mutation Verification (`.agents/scripts/mutation_gate.py`):** Injects controlled mutations to confirm tests actually fail when invariants break rather than passing vacuously.

### B. Mechanical AST Test Quality Gate (`.agents/scripts/test_quality_gate.py`, `TQ-01`–`TQ-05`)
Executed automatically in RAM during `TransactionBuffer.validate()` on every staged `test_*.py` / `*_test.py` file and via CLI:
1. **`TQ-01` (Assertion Presence & Non-Tautology):** Rejects tests with zero assertions or tautologies (`assert True`, `assert x == x`).
2. **`TQ-02` (No Dead/Skipped Tests):** Rejects unconditional skips (`@unittest.skip`, `@pytest.mark.skip`) and hidden inactive test functions.
3. **`TQ-03` (Host Portability):** Rejects machine-coupled user home paths (`C:\Users\...`, `/home/...`) and hardcoded local session UUIDs.
4. **`TQ-04` (No Mocked E2E Boundaries):** Rejects skipped execution flags (`execute_hooks=False`) without live execution tests and blocks mocking out integration/E2E boundaries.
5. **`TQ-05` (Mandatory Negative Paths):** Requires every test module with `>= 2` tests to assert failure/rejection behavior (`assertRaises`, `FAIL`, `BLOCKED`, `returncode`, etc.).

### C. Deterministic Loop State Machine (`LoopStateMachine`)
Enforces strict per-round lifecycle ordering in `campaign_ir.py`:
* **Legal Transitions:** `PLAN -> STAGE -> VERIFY -> COMMIT -> CACHE` (plus `FAILED` on non-zero verification exit).
* **Invariant Enforcement:** Any out-of-order transition or stale `staged_sha256` passed to `verify(exit_code, staged_sha256, error_output)` raises `StateTransitionError`, making unverified commits unrepresentable in runtime state.

### D. Error-Hash Circuit Breaker (`ErrorCircuitBreaker`)
Prevents stochastic retry loops from burning quota on identical failures:
* **Digest Normalization:** `hash_error_output` normalizes failure stderr into `error_sha256`.
* **Trip Threshold (`BreakerState`):** Halts slice retries immediately on **2 consecutive identical `error_sha256`** hashes or **3 consecutive failed rounds**, logging `TRIPPED` to `results.tsv` and escalating for root-cause reassessment.

### E. Thin-Orchestrator Delegation (`O(1)` Parent Context)
1. **Compile & Optimize First:** Run `crucible_gate.py campaign` (`load_campaign_spec` -> `compile_campaign` -> `optimize_campaign`) to validate `CRUCIBLE_ALLOWED_ROOTS`, detect DAG cycles, and skip `SKIP_CACHED` slices before spawning agents.
2. **Disjoint Wave Fan-Out:** Dispatch each `execution_waves` level via `run_workflow` with `Model="flash"` and `Workspace="share"` on disjoint `target_paths`.
3. **Structured Receipt Merge Only:** Workers return only the typed JSON receipt (`slice_id`, `commit_sha`, `after_sha256`, `passed`, `summary`); raw file reads, intermediate diffs, and full test logs never enter parent context.
4. **Monotonic Ratchet Persistence:** Record `KEEP`, `REVERT`, `SKIP_CACHED`, or `TRIPPED` via `append_ratchet_ledger` (`results.tsv`) and persist cache entries atomically via `merge_receipt_cache`.

---

## 5. Causality Matrix (`Symptom -> CS Root Cause -> Physical Code Fix`)

| Observed Symptom | CS Root Cause | Physical Code Fix & Exact Mechanism |
| :--- | :--- | :--- |
| **Model drift & context rot across rounds** | Unbounded autoregressive context growth dilutes attention over stale history and unrelated files; unconstrained loop phases allow ad-hoc re-planning mid-edit. | `slice-worker` executes fresh-context single-slice prompts from `campaign_ir.py` (`build_slice_worker_prompt`) under `LoopStateMachine` (`PLAN -> STAGE -> VERIFY -> COMMIT -> CACHE`). |
| **Slow sub-agents & verification stalls** | Serial disk I/O roundtrips per file edit and sequential subprocess execution (`check` -> `doctor` -> `pytest` -> spoke tests) compound process-fork overhead. | `tx_patch.py` batches edits in RAM via `TransactionBuffer`; `scripts/verify_all.ps1` runs all `11` verification checks concurrently via `ThreadPoolExecutor` (`12.86s`); `campaign_ir.py` schedules independent slices in parallel `execution_waves`. |
| **Partial commits & half-written files on failure** | Non-atomic direct writes leave mutated files on disk if a later file fails validation or process execution aborts mid-batch. | `tx_patch.py` (`TransactionBuffer.commit`) runs `validate()` in RAM, stages temp files with atomic `os.replace()`, and executes full `before_bytes` rollback on any exception. |
| **Lost cache keys under concurrent slice workers** | Uncoordinated read-modify-write updates to `receipt_cache.json` drop earlier workers' entries when two slices finish concurrently. | `campaign_ir.py` (`save_receipt_cache_cas`, `_path_lock`, `merge_receipt_cache`) verifies the prior cache `file_sha256` before atomic write and raises `CacheConflictError` on mismatch. |
| **False staleness & wasted re-runs after Git checkout** | Filesystem `mtime` timestamps reset on `git checkout` or `git clone`, causing wall-clock dependency checks to flag unchanged upstream files as modified. | `crucible_gate.py` checks `depends_on_sha256` content digests before falling back to `mtime`, and `campaign_ir.py` (`compute_slice_input_sha256`, `optimize_campaign`) hashes target/dependency contents to skip unchanged slices at `0` tokens. |
| **Repeated identical error loops** | Stochastic retry without failure-state memory repeats the same failing patch across consecutive iterations. | `campaign_ir.py` (`ErrorCircuitBreaker`, `hash_error_output`) hashes normalized failure diagnostics and trips `BreakerState` once consecutive identical error hashes hit threshold. |

---

## 6. Verified Vertical Slices (#1–#6) & Open CS Frontiers

### Verified Vertical Slices (#1–#6)

| Rank | Vertical Slice | CS Primitives Combined | Why Build It First | Status & Verified Commits |
| :---: | :--- | :--- | :--- | :--- |
| **#1** | **Content-Hash Staleness & Spoke Memoization** | `DAGs` + `Content-Addressable SHA-256 Caching` | Highest immediate leverage with minimal code (~60L). Eliminates false `mtime` staleness in `crucible_gate.py check --strict` and lets spokes return instant cached receipts when inputs haven't changed. | **COMPLETED** — Hub `a1811eb` (`main`), Spoke `b6b3238` (`main`) |
| **#2** | **Capability-Scoped Spoke Sandbox** | `Microkernel IPC` + `Capability-Based Security` | Hardens the `Calgary Public Library/` vs. `Personal Work/` boundary at the process level so autonomous loops can never leak across domains. | **COMPLETED** — Hub `a39a3c2` (`loop/cs-v1-campaign`), Spoke `ba06e49` (`loop/cs-v1-campaign`) |
| **#3** | **Property-Based Fuzzing & Replay Harness** | `Property-Based Testing` + `Event Sourcing` | Turns every real Hub→Spoke session into a permanent regression suite and catches malformed JSON/timestamp/frontmatter edge cases automatically. | **COMPLETED** — Hub `048ba70` (`loop/cs-v1-campaign`), Spoke `4acd1cb` (`loop/cs-v1-campaign`) |
| **#4** | **In-RAM Transactional Patcher & Terminal Runner** | `Copy-on-Write ACID` + `AST/TQ Pre-Commit Gate` | Eliminates per-file tool roundtrips and guarantees zero disk corruption on failed multi-file edits. | **COMPLETED** — `tx_patch.py` (`2a6f06b`) + `scripts/verify_all.ps1` (`36d1db0`, merged to `main`) |
| **#5** | **Campaign IR Compiler Front-End & v3 Loop** | `Typed DAG IR` + `Incremental Cache` + `Error-Hash Circuit Breaker` | Compiles campaigns before Round 1, skips unchanged slices at 0 LLM tokens, and halts identical-error loops immediately. | **COMPLETED** — `campaign_ir.py` (`2aa5922`) + `depends_on_sha256` (`e4f7d26`, merged to `main`) |
| **#6** | **v4 Thin-Orchestrator, CAS Cache, FSM & Ratchet Ledger** | `Optimistic CAS` + `Finite State Machine` + `Append-Only Event Log` | Enforces `PLAN → STAGE → VERIFY → COMMIT → CACHE` in code, prevents concurrent cache lost updates, logs every round to TSV, and exposes `crucible_gate.py campaign` CLI. | **COMPLETED** — `campaign_ir.py` (`7abe2f6`) + `crucible_gate.py campaign` (`loop/v4-thin-orchestrator`) |
| **#7** | **BM25 + Graph-Walk Retrieval (`router.py`)** | `IR + Bounded k-Hop BFS` + `Structural Filtering` | Combines BM25 lexical scoring with cycle-safe `k`-hop traversal over `related_ids` and `domain`/`kind` filters inside the sub-100ms RAM budget. | **COMPLETED** — `router.py` (`ee42caa`, `main`) |
| **#8** | **Spoke Design-by-Contract (`contracts.py`)** | `Formal Pre/Postconditions` + `Frame Invariants` | Enforces `requires`, `ensures`, and `unchanged_roots` SHA-256 frame invariants across spoke ABI calls. | **COMPLETED** — `contracts.py` + `test_contracts.py` |
| **#9** | **SAT/SMT Constraint Solving (`solver.py`)** | `Z3 SAT/SMT` + `Disjoint Path & Authority Feasibility` | Proves wave schedule feasibility (disjoint `target_paths`, single-domain isolation, authority holds) prior to spawning workers. | **COMPLETED** — `solver.py` + `test_solver.py` |
| **#10** | **Autonomous Self-Discovery & Replay Loop (`replay_loop.py`)** | `AST Call-Edge Scanner` + `Worktree/RAM Tx` + `Double-Run Replay` | Discovers structural/contract gaps in RAM (`discover`), executes bounded fixes in isolated worktrees/RAM, rolls back faults automatically, and surfaces only replay-verified diffs. | **WAVE 4.5** — `replay_loop.py` + `crucible_gate.py` |
| **#11** | **Unified CS-First-Principles Story Engine (`story_engine.py`)** | `Form Grammars` + `DP Story-Arc Clip Selection` + `CHG-01 SHA-256` | Re-invents `writers-room` + `story-lane` capabilities from CS first principles with exact `OPEN -> DEVELOP -> PAYOFF_CLOSE` DP selection, `CHG-01` invalidation, and `K-MCP-01` compatibility. | **WAVE 4.5** — `story_engine.py` + `storylane_spoke` |
| **#12** | **Cross-Repo Portability & G5 Ledger (`CD-W19` / `CD-W20`)** | `Relative MCP Paths` + `Non-Vanity G5 Outcome Ledger` | Eliminates hardcoded drive-letter paths across all 4 `.agents/plugins/*/mcp_config.json` files and verifies 10 compounding non-commit-counting improvements (`g5-check`). | **WAVE 4.5** — `doctor.py` + `outcome_ledger.py` |

### Open CS Frontiers (Unbuilt Domains)

1. **Spoke Design-by-Contract (`Formal Pre/Postconditions & Runtime Invariants`)**
   * Enforce machine-checkable preconditions, postconditions, and frame invariants (`requires` / `ensures` / `unchanged_roots`) across every MCP spoke ABI call (`recognize`, `prepare`, `deliver`), turning spoke contracts into runtime-verified assertions rather than prose rules.
2. **BM25 + Graph-Walk Retrieval in `router.py` (`IR + Relational Traversal`)**
   * Combine ranked lexical BM25 scoring with bounded `k`-hop traversal over capability/dependency edges in `router.py`, enabling synonym-tolerant and structural queries (filtering by domain, authority tier, and execution stage) inside the sub-100ms RAM budget.
3. **SAT/SMT Constraint Solving (`Automated Schedule, Authority & Path Feasibility`)**
   * Encode slice resource locks, disjoint `target_paths`, domain-isolation policies, and authority holds as Boolean/linear constraints solved via SAT/SMT before execution, proving plan feasibility and zero-conflict parallel scheduling prior to spawning workers.
