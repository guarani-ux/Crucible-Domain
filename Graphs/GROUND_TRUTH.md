# Graphs — Ground Truth & Domain Intake (`GROUND_TRUTH.md`)

- **Domain:** `Graphs/` (Cross-Project & Whole-System Architectural Views)
- **Receiving Standard:** [Work Operating System Graph Catalog](../Project/Work%20Operating%20System/Work_Operating_System_Graph_Catalog.md) (`P-WOS`, 7-Graph Standard)
- **Audience:** Levi (Systems Architect), **Neon** (next-stage orchestrator / refactoring model), and cold-start Antigravity sessions.
- **Purpose:** Eliminate repeated multi-file grepping and context thrashing by maintaining canonical, ID-linked Mermaid views of Crucible Domain's topology, runtime hooks, coupling boundaries, file reachability, and prioritized refactoring plan.

## Operating Workflow
1. **Orient in 1 read:** Start at [00_System_Atlas_and_Neon_Handoff.md](./00_System_Atlas_and_Neon_Handoff.md) for the file-to-purpose map and Neon execution brief.
2. **Inspect by WOS Graph Type:**
   - [01_System_Topology_and_Runtime.md](./01_System_Topology_and_Runtime.md) — **Target System Architecture** & **Reference Process Model** (actual hook chains, RAM index, and storage boundaries).
   - [02_Coupling_and_Reachability_Audit.md](./02_Coupling_and_Reachability_Audit.md) — **Outcome Map** & **Capability Inventory** (what is over-coupled, what is under-coupled, and what is misplaced).
   - [03_Neon_Refactoring_Plan.md](./03_Neon_Refactoring_Plan.md) — **Planning Decision Flow** & **Plan Dependency Graph** (ordered, decoupled slices for Neon).
3. **Verify before handoff:** Run `python ".agents/scripts/crucible_gate.py" check` and `python ".agents/scripts/crucible_gate.py" doctor` after edits.
