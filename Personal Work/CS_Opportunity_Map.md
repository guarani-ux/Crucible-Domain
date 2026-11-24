---
depends_on:
  - Personal Work/GROUND_TRUTH.md
  - Graphs/00_System_Atlas_and_Neon_Handoff.md
  - Knowledge/Knowledge_Register.md
---

# Crucible Domain — 10-Pillar CS & CE Stack Blueprint

> **Purpose:** Map the full Computer Science and Computer Engineering stack governing `Crucible Domain` from neural token inference down to disk I/O and control loops.
> **Scope:** Sovereign systems engineering (`PW-01`–`PW-03`). Every layer links a physical mechanism in CPU, RAM, disk, ASTs, or solvers to observed agent and build behavior.

---

## 1. Full Computing Stack Dataflow

```mermaid
flowchart LR
    PROMPT["Prompt & Contract"] --> INF["Information Theory & LLM Inference (Token Budget / KV-Cache)"]
    INF --> TYPES["PL Type Schemas (JSON Spec / Dataclasses)"]
    TYPES --> DAG["Compiler DAG (campaign_ir.py)"]
    DAG --> OS["OS / Sub-Agent Worktrees (slice-worker / stdio IPC)"]
    OS --> DB["Database ACID / CAS (tx_patch.py / os.replace)"]
    DB --> HW["Hardware Latency (RAM vs. Disk I/O / ThreadPool)"]
    HW --> CTRL["Control Ratchet (results.tsv / ErrorCircuitBreaker)"]
```

---

## 2. Pillars 1–5: Hardware, OS, Storage, Distributed Systems, Security

| Pillar & Core Law | Physical Mechanism (CPU/RAM/Disk/Net) | Impact on Prompts, Sub-Agents & Builds |
| :--- | :--- | :--- |
| **1. Hardware & Computer Architecture** *(Memory Hierarchy, I/O Latency Gap)* | L1/RAM operations execute in nanoseconds; NTFS metadata lookups, process forks, and sequential subprocess spawning cost tens to hundreds of milliseconds. | Packing capability indexing (`router.py`) into ~30ms RAM reads and running 4 verification suites concurrently via `ThreadPoolExecutor` in `scripts/verify_all.ps1` cuts suite wall-clock latency to the slowest critical-path process (~15.6s). |
| **2. Operating Systems** *(Process Isolation, IPC, Copy-on-Write Worktrees)* | Separate OS processes communicate over stdio JSON-RPC 2.0 (`writers-room`, `crucible-observatory`, `story-lane`); isolated Git worktrees and `slice-worker` sub-agents decouple working directories and process heaps. | Keeps Hub routing and policy checks in a thin kernel while isolating third-party parsers, LLM tool sessions, and parallel slice execution from mutating shared working trees. |
| **3. Storage & Databases** *(ACID Atomicity, Copy-on-Write, Append-Only WAL)* | `tx_patch.py` (`TransactionBuffer`) buffers edits in RAM, validates syntax/AST before disk touch, writes temp files, commits atomically via `os.replace()`, and restores `before_bytes` on failure; `append_ratchet_ledger` appends immutable TSV rows to `results.tsv`. | Eliminates partial multi-file writes on mid-edit crashes, removes serial disk write roundtrips, and preserves a monotonic append-only execution log (`results.tsv`) per round. |
| **4. Distributed Systems** *(Optimistic Concurrency Control / CAS, Idempotency)* | `campaign_ir.py` (`save_receipt_cache_cas`, `file_sha256`, `_path_lock`) verifies the expected cache SHA-256 before writing and raises `CacheConflictError` on concurrent mismatch; `compute_slice_input_sha256` keys memoized receipts by exact target + dependency hashes. | Prevents parallel workers from silently overwriting each other's cached slice receipts (lost-update anomaly) and enables deterministic idempotent skips across rounds. |
| **5. Security** *(Object-Capability Model, Least-Privilege Containment)* | `TransactionBuffer._resolve` rejects path traversal outside `root`; `compile_campaign` enforces `allowed_roots` containment (`_is_within_any`); MCP spokes enforce explicit directory capability bounds and read-only external boundaries. | Bounds `slice-worker` and spoke file access mathematically at path resolution rather than relying on natural-language prompt compliance. |

---

## 3. Pillars 6–10: Information Theory, PL/Types, Compilers, Formal Methods, Control Theory

| Pillar & Core Law | Physical Mechanism (Tokens/ASTs/Graphs/Solvers) | Impact on Prompts, LLM Behavior & Builds |
| :--- | :--- | :--- |
| **6. Information Theory & Neural Inference** *(Shannon Entropy, Context Dilution, KV-Cache Budget)* | Autoregressive transformer attention degrades as irrelevant context tokens accumulate; `build_slice_worker_prompt` injects only the bounded slice spec, target paths, and `verify_cmd`. | Stripping conversation history and multi-slice noise in `slice-worker` keeps attention entropy focused on target symbols, reducing hallucinated edits and token cost per round. |
| **7. Programming Languages & Type Systems** *(Static Schemas, Algebraic Error Types)* | `campaign_ir.py` (`CampaignSpec`, `SliceNode`, `PlannedSlice`, `_expect_str_list`) enforces typed schemas at load time; `tx_patch.py` validates Python syntax (`compile`) and JSON parsing in RAM before `os.replace()`. | Converts malformed LLM outputs and invalid JSON specs into deterministic pre-execution parse failures (`CampaignCompileError`, `TransactionValidationError`) with zero side effects. |
| **8. Compilers & Graph Theory** *(Typed DAG IR, Topological Wave Scheduling, AST Gates)* | `compile_campaign` lowers campaign specs into an acyclic dependency graph (`_topological_order` via Kahn's algorithm) grouped into parallel `execution_waves`; `test_quality_gate.py` (`TQ-01..05`) parses test ASTs prior to commit. | Detects dependency cycles before Round 1, exposes parallelizable slice waves to the orchestrator, and blocks tautological assertions at compile/stage time. |
| **9. Formal Methods & Logic** *(Finite State Machines, Invariants, Property Testing)* | `LoopStateMachine` (`PLAN -> STAGE -> VERIFY -> COMMIT -> CACHE`) rejects out-of-order round transitions with `StateTransitionError`; property-based tests and `mutation_gate.py` assert invariants across randomized inputs. | Prevents an autonomous loop from committing unverified code or skipping cache invalidation by making illegal round transitions unrepresentable in runtime state. |
| **10. Control Theory & Amdahl's Law** *(Closed-Loop Ratchet, Circuit Breaking, Critical Path)* | `ErrorCircuitBreaker` hashes normalized stderr (`hash_error_output`) and trips on repeated identical failures; `results.tsv` records pass/fail deltas; `verify_all.ps1` parallelizes independent gates. | Halts runaway retry loops deterministically on identical error hashes, ensures round-over-round monotonic progress, and bounds verification latency by the slowest single check rather than their sum. |

---

## 4. Causality Matrix (`Symptom -> CS Root Cause -> Physical Code Fix`)

| Observed Symptom | CS Root Cause | Physical Code Fix & Exact Mechanism |
| :--- | :--- | :--- |
| **Model drift & context rot across rounds** | Unbounded autoregressive context growth dilutes attention over stale history and unrelated files; unconstrained loop phases allow ad-hoc re-planning mid-edit. | `slice-worker` executes fresh-context single-slice prompts from `campaign_ir.py` (`build_slice_worker_prompt`) under `LoopStateMachine` (`PLAN -> STAGE -> VERIFY -> COMMIT -> CACHE`). |
| **Slow sub-agents & verification stalls** | Serial disk I/O roundtrips per file edit and sequential subprocess execution (`check` -> `doctor` -> `pytest` -> spoke tests) compound process-fork overhead. | `tx_patch.py` batches edits in RAM via `TransactionBuffer`; `scripts/verify_all.ps1` runs all 4 verification suites concurrently via `ThreadPoolExecutor(max_workers=4)`; `campaign_ir.py` schedules independent slices in parallel `execution_waves`. |
| **Partial commits & half-written files on failure** | Non-atomic direct writes leave mutated files on disk if a later file fails validation or process execution aborts mid-batch. | `tx_patch.py` (`TransactionBuffer.commit`) runs `validate()` in RAM, stages temp files with atomic `os.replace()`, and executes full `before_bytes` rollback on any exception. |
| **Lost cache keys under concurrent slice workers** | Uncoordinated read-modify-write updates to `receipt_cache.json` drop earlier workers' entries when two slices finish concurrently. | `campaign_ir.py` (`save_receipt_cache_cas`, `_path_lock`, `merge_receipt_cache`) verifies the prior cache `file_sha256` before atomic write and raises `CacheConflictError` on mismatch. |
| **False staleness & wasted re-runs after Git checkout** | Filesystem `mtime` timestamps reset on `git checkout` or `git clone`, causing wall-clock dependency checks to flag unchanged upstream files as modified. | `crucible_gate.py` checks `depends_on_sha256` content digests before falling back to `mtime`, and `campaign_ir.py` (`compute_slice_input_sha256`, `optimize_campaign`) hashes target/dependency contents to skip unchanged slices at 0 tokens. |
| **Repeated identical error loops** | Stochastic retry without failure-state memory repeats the same failing patch across consecutive iterations. | `campaign_ir.py` (`ErrorCircuitBreaker`, `hash_error_output`) hashes failure diagnostics and trips the breaker (`BreakerState`) once consecutive identical error hashes hit threshold. |

---

## 5. Verified Vertical Slices (#1–#6) & Open CS Frontiers

### Verified Vertical Slices (#1–#6)

| Rank | Vertical Slice | CS Primitives Combined | Why Build It First | Status & Verified Commits |
| :---: | :--- | :--- | :--- | :--- |
| **#1** | **Content-Hash Staleness & Spoke Memoization** | `DAGs` + `Content-Addressable SHA-256 Caching` | Highest immediate leverage with minimal code (~60L). Eliminates false `mtime` staleness in `crucible_gate.py check --strict` and lets spokes return instant cached receipts when inputs haven't changed. | **COMPLETED** — Hub `a1811eb` (`main`), Spoke `b6b3238` (`main`) |
| **#2** | **Capability-Scoped Spoke Sandbox** | `Microkernel IPC` + `Capability-Based Security` | Hardens the `Calgary Public Library/` vs. `Personal Work/` boundary at the process level so autonomous loops can never leak across domains. | **COMPLETED** — Hub `a39a3c2` (`loop/cs-v1-campaign`), Spoke `ba06e49` (`loop/cs-v1-campaign`) |
| **#3** | **Property-Based Fuzzing & Replay Harness** | `Property-Based Testing` + `Event Sourcing` | Turns every real Hub→Spoke session into a permanent regression suite and catches malformed JSON/timestamp/frontmatter edge cases automatically. | **COMPLETED** — Hub `048ba70` (`loop/cs-v1-campaign`), Spoke `4acd1cb` (`loop/cs-v1-campaign`) |
| **#4** | **In-RAM Transactional Patcher & Terminal Runner** | `Copy-on-Write ACID` + `AST/TQ Pre-Commit Gate` | Eliminates per-file tool roundtrips and guarantees zero disk corruption on failed multi-file edits. | **COMPLETED** — `tx_patch.py` (`2a6f06b`) + `scripts/verify_all.ps1` (`36d1db0`, merged to `main`) |
| **#5** | **Campaign IR Compiler Front-End & v3 Loop** | `Typed DAG IR` + `Incremental Cache` + `Error-Hash Circuit Breaker` | Compiles campaigns before Round 1, skips unchanged slices at 0 LLM tokens, and halts identical-error loops immediately. | **COMPLETED** — `campaign_ir.py` (`2aa5922`) + `depends_on_sha256` (`e4f7d26`, merged to `main`) |
| **#6** | **v4 Thin-Orchestrator, CAS Cache, FSM & Ratchet Ledger** | `Optimistic CAS` + `Finite State Machine` + `Append-Only Event Log` | Enforces `PLAN → STAGE → VERIFY → COMMIT → CACHE` in code, prevents concurrent cache lost updates, logs every round to TSV, and exposes `crucible_gate.py campaign` CLI. | **COMPLETED** — `campaign_ir.py` (`7abe2f6`) + `crucible_gate.py campaign` (`loop/v4-thin-orchestrator`) |

### Open CS Frontiers (Unbuilt Domains)

1. **Spoke Design-by-Contract (`Formal Pre/Postconditions & Runtime Invariants`)**
   * Enforce machine-checkable preconditions, postconditions, and frame invariants (`requires` / `ensures` / `unchanged_roots`) across every MCP spoke ABI call (`recognize`, `prepare`, `deliver`), turning spoke contracts into runtime-verified assertions rather than prose rules.
2. **BM25 + Graph-Walk Retrieval in `router.py` (`IR + Relational Traversal`)**
   * Combine ranked lexical BM25 scoring with bounded `k`-hop traversal over capability/dependency edges in `router.py`, enabling synonym-tolerant and structural queries (filtering by domain, authority tier, and execution stage) inside the sub-100ms RAM budget.
3. **SAT/SMT Constraint Solving (`Automated Schedule, Authority & Path Feasibility`)**
   * Encode slice resource locks, disjoint `target_paths`, domain-isolation policies, and authority holds as Boolean/linear constraints solved via SAT/SMT before execution, proving plan feasibility and zero-conflict parallel scheduling prior to spawning workers.
