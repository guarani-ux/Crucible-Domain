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
