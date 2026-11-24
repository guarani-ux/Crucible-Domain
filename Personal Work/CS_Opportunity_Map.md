---
depends_on:
  - Personal Work/GROUND_TRUTH.md
  - Graphs/00_System_Atlas_and_Neon_Handoff.md
  - Knowledge/Knowledge_Register.md
---

# Crucible Domain — Computer Science Opportunity Map

> **Purpose:** Map the Computer Science primitives already powering `Crucible Domain`, identify high-leverage CS primitives *not yet in play*, and show what becomes possible when they work together as one system.  
> **Scope:** Sovereign personal systems-engineering (`PW-01`–`PW-03`). Every concept is tied to physical mechanisms on disk, not abstract theory.

---

## 1. The 5 Active CS Pillars (What You Already Run & Where Each Hits Its Ceiling)

| CS Pillar | Live Crucible Implementation | What It Physically Guarantees Today | Current Ceiling (Where It Stops) |
| :--- | :--- | :--- | :--- |
| **1. Microkernel & IPC (`OS Architecture`)** | 5-piece `<40ms` Hub kernel (`.agents/scripts/crucible/`) + 3-tool stdio JSON-RPC 2.0 MCP spokes (`writers-room`, `crucible-observatory`, `story-lane`) | Policy, routing, and safety stay in a tiny kernel; domain parsers/renderers run in isolated user-space processes over a uniform 3-call ABI (`recognize / prepare / deliver`). | Spokes still run with **ambient host filesystem permissions**—nothing prevents a buggy spoke from reading/writing outside its assigned directory. |
| **2. Static Analysis (`Compilers / AST`)** | `test_quality_gate.py` (`TQ-01..05`), `py_compile`, `mutation_gate.py` | Parses Python test files into an AST to catch tautological asserts, missing negative paths, and hardcoded host paths before commit. | Only checks **static test syntax** and hand-written test cases; does not generate adversarial inputs or prove invariants across arbitrary payloads. |
| **3. Dependency Graphs (`DAGs & Cache Invalidation`)** | 7-Graph WOS standard (`K-GRAPH-01`), `depends_on:` frontmatter staleness check in `crucible_gate.py check --strict` | Models blocking vs. advisory dependencies and flags when an upstream `GROUND_TRUTH.md` changes after a downstream artifact. | Uses **file `mtime`** (wall-clock timestamps) rather than **content hashes**, so touching a file without changing meaning triggers false staleness, and unchanged inputs still re-run LLM turns. |
| **4. Information Retrieval (`BM25 & Precedence`)** | `router.py` indexing 150 capabilities in ~30ms RAM with `CAPABILITY_PRECEDENCE` and selective abstention | Resolves canonical IDs in `O(1)` and natural-language queries in milliseconds without burning tokens grepping disk. | Purely **lexical** (token overlap); cannot match conceptual synonyms unless shared tokens appear, and has no structured query algebra (e.g., filter by domain + authority + stage). |
| **5. Transactional Checkpoints (`Version Control`)** | `crucible-loop` (1 verified Git commit per round on `loop/<slug>`) + `check_artifact.py` SHA-256 verification | Every autonomous round is an atomic, rewindable transaction; any bad round rolls back cleanly without corrupting `main`. | Commits capture **final file state**, not the **event trace** of tool calls/spoke inputs that produced it—so you can rewind state, but you cannot deterministically *replay* a run offline. |

---

## 2. Five High-Leverage CS Elements NOT Yet in Play

These five primitives are battle-tested in compilers, build systems, and distributed infrastructure—and each one directly breaks a ceiling from Section 1:

1. **Content-Addressable Memoization (`SHA-256 Build Caching` — like Bazel / Nix)**
   * **Mechanism:** Hash `(spoke_name, tool_name, normalized_inputs, pinned_craft_sha)` into a deterministic cache key. If the hash matches a prior verified receipt, return the cached result in `1ms` with **zero LLM tokens and zero re-execution**.
   * **What it unlocks individually:** Eliminates redundant LLM/spoke runs when upstream inputs haven't actually changed; replaces fragile `mtime` staleness with cryptographic content-hash staleness.

2. **Formal State Machines & Type-State Contracts (`Finite Automata`)**
   * **Mechanism:** Represent every deliverable lifecycle (`INTAKE → DRAFT → EXPLORATORY_REVIEW → LOCKED_CUT → DELIVERED`) as an explicit finite state machine where each transition declares its required guard (e.g., `LOCKED_CUT` is mathematically unreachable without a signed `project_authority` token).
   * **What it unlocks individually:** Makes illegal transitions (like approving an editorial cut inside a spoke, or shipping an unaudited final script) **impossible by construction** rather than relying on prompt reminders.

3. **Property-Based Testing & Fuzzing (`Formal / Automated Verification`)**
   * **Mechanism:** Instead of only writing 3–5 hand-crafted unit tests, declare **invariants** (*"for any transcript JSON with arbitrary timestamps, `storylane_prepare` must reject `end <= start` and never crash"*) and auto-generate 200+ randomized/adversarial inputs per test run.
   * **What it unlocks individually:** Catches weird Unicode, negative timestamps, malformed frontmatter, and edge-case JSON-RPC payloads that human-written tests miss.

4. **Event Sourcing & Deterministic Replay (`Append-Only Log`)**
   * **Mechanism:** Record every Hub → Spoke JSON-RPC call (`request`, `response`, `input_sha256`, `exit_status`) as an immutable JSONL event log. Replay any historical run offline against a new spoke version to prove zero regressions.
   * **What it unlocks individually:** Turns every real work session into a permanent **regression test fixture**—giving you true Rung-3/Rung-4 proof without manually authoring fixtures.

5. **Capability-Based Security (`Least-Privilege Object Capabilities`)**
   * **Mechanism:** Instead of letting every spoke see the entire `C:\` drive, pass an explicit **scoped capability token** (`allowed_read_roots`, `allowed_write_root`, `read_only=True`) in `mcp_config.json` / `prepare()` and enforce path containment at the spoke boundary.
   * **What it unlocks individually:** Enforces domain isolation (`Calgary Public Library/` vs. `Personal Work/`, Asana read-only) at the OS/process boundary rather than trusting prompts.

---

## 3. Compound Synergies (What Happens When They Work Together)

Individually, each CS element solves one local bug. **Combined**, they turn Crucible Domain from a "well-organized agent workspace" into a **deterministic, incremental AI compiler for real-world work**:

```mermaid
flowchart LR
    INTENT["Human Intent (High-Level)"] --> LLM["Stochastic LLM Compiler"]
    LLM --> FSM["Formal State Machine\n(Valid Transitions Only)"]
    FSM --> CAP["Capability-Scoped\nMCP Spokes"]
    CAP --> CACHE["Content-Addressable\nMemoization (SHA-256)"]
    CACHE --> DAG["DAG Dependency Graph\n(depends_on)"]
    DAG --> REPLAY["Event-Sourced Replay\n+ Property Fuzzing"]
    REPLAY --> GIT["Rewindable Git Checkpoint\n(crucible-loop)"]
```

### Three Emergent Capabilities You Cannot Get Any Other Way
1. **Incremental, Zero-Waste AI Build Pipeline (`DAG` + `Content-Addressable Memoization` + `MCP Spokes`):**
   * Just like `Bazel` or `make` only recompiles the `.c` file that changed, changing one paragraph in `Calgary Public Library/GROUND_TRUTH.md` hashes down the DAG and **re-runs only the exact downstream script or brief whose input hash changed**, returning cached verified receipts for everything else in `1ms`.
2. **Self-Hardening Agent System (`Event Sourcing` + `Property-Based Fuzzing` + `AST Gates`):**
   * Every real Hub→Spoke call gets logged as a replayable event. Whenever you upgrade `writers-room` or `story-lane`, you replay your real historical work log + 200 fuzzed edge cases automatically. The system gets **more reliable every time you use it**, not more fragile.
3. **Zero-Trust Multi-Domain Execution (`Microkernel` + `Formal State Machines` + `Capability-Based Security`):**
   * You can safely run autonomous 12-round `crucible-loop` sessions across both `Personal Work/` and `Calgary Public Library/` because **illegal state transitions** (shipping unapproved cuts) and **cross-domain leaks** (CPL data touching Personal Work) are blocked mathematically at the spoke boundary.

---

## 4. Top 3 Ranked Vertical Slices (Leverage vs. Complexity)

| Rank | Vertical Slice | CS Primitives Combined | Why Build It First | Status & Verified Commits |
| :---: | :--- | :--- | :--- | :--- |
| **#1** | **Content-Hash Staleness & Spoke Memoization** | `DAGs` + `Content-Addressable SHA-256 Caching` | Highest immediate leverage with minimal code (~60L). Eliminates false `mtime` staleness in `crucible_gate.py check --strict` and lets spokes return instant cached receipts when inputs haven't changed. | **COMPLETED** — Hub `a1811eb` (`main`), Spoke `b6b3238` (`main`) |
| **#2** | **Capability-Scoped Spoke Sandbox** | `Microkernel IPC` + `Capability-Based Security` | Hardens the `Calgary Public Library/` vs. `Personal Work/` boundary at the process level so autonomous loops can never leak across domains. | **COMPLETED** — Hub `a39a3c2` (`loop/cs-v1-campaign`), Spoke `ba06e49` (`loop/cs-v1-campaign`) |
| **#3** | **Property-Based Fuzzing & Replay Harness** | `Property-Based Testing` + `Event Sourcing` | Turns every real Hub→Spoke session into a permanent regression suite and catches malformed JSON/timestamp/frontmatter edge cases automatically. | **COMPLETED** — Hub `048ba70` (`loop/cs-v1-campaign`), Spoke `4acd1cb` (`loop/cs-v1-campaign`) |
