# Crucible Domain — Workspace Agent Constitution (AGENTS.md)

> Scope: Applies to all sessions operating inside `Crucible Domain`. Inherits global rules from `~/.gemini/GEMINI.md`.
> **Core Role:** `Crucible Domain` is the **Orchestrator-Producer Hub (Single Control Plane)**—not merely a knowledge archive or system builder. It frames assignments, resolves local project ground truth and approval authority, supplies non-evidentiary craft methods, commissions lightweight domain MCP spokes (`.agents/plugins/<spoke>/`), and judges whether deliverables serve the human recipient.

## 1. Local-First Entry & RAM Capability Routing (`K-WOS-01`, `K-WOS-03`, `K-MCP-01`)
Before proposing new folders, plans, or cross-project work, resolve what exists locally first:
- Hub Overview & Spoke Model: [README.md](README.md)
- Canonical Calgary Public Library Ground Truth: [Calgary Public Library/GROUND_TRUTH.md](Calgary%20Public%20Library/GROUND_TRUTH.md)
- Canonical Personal Work Ground Truth: [Personal Work/GROUND_TRUTH.md](Personal%20Work/GROUND_TRUTH.md)
- Testing Philosophy & 4 Evidence Rungs (`K-TEST-01`): [Knowledge/Testing_Philosophy.md](Knowledge/Testing_Philosophy.md)
- Active & Reviewed Projects: [Project/Project_Register.md](Project/Project_Register.md)
- Cross-Project Findings & Limits (`K-MCP-01`): [Knowledge/Knowledge_Register.md](Knowledge/Knowledge_Register.md)
- Historical System Exhibits: [Knowledge/Repository Archaeology/00-Exhibit_Index.md](Knowledge/Repository%20Archaeology/00-Exhibit_Index.md)
- Media Agency Role Cards & Procedures (55): [Knowledge/Media Agency/Skills and Workflows/README.md](Knowledge/Media%20Agency/Skills%20and%20Workflows/README.md) · [Knowledge/Media Agency/Media_Work_Routing.md](Knowledge/Media%20Agency/Media_Work_Routing.md)
- Work Operating System & 7-Graph Standard: [Project/Work Operating System/Work_Operating_System_Graph_Catalog.md](Project/Work%20Operating%20System/Work_Operating_System_Graph_Catalog.md)
- Antigravity Harness Self-Model: [Project/Inner Gravity/README.md](Project/Inner%20Gravity/README.md)
- Registered Domain MCP Spokes: [Writer's Room MCP Spoke](.agents/plugins/writers-room/skills/writers-room/SKILL.md) (`writers-room`)

Route any task, canonical ID (`MW-04`, `PROD-S`, `K-WOS-02`), or legacy ChatGPT `skill_id` in RAM (<100ms):
```sh
python ".agents/scripts/crucible_gate.py" route "<task or ID>"
python ".agents/scripts/crucible_gate.py" doctor
```

## 2. Autonomous Local-First Intake & Pre-Finish Audit (`Push Right`)
1. **Synthesize Before Asking:** When entering an empty or partial domain folder (`Calgary Public Library/`, `Personal Work/`), gather existing local ground truth first (`GROUND_TRUTH.md`, `Knowledge/`), tag reversible assumptions `[PROPOSED DEFAULT]` and missing facts `[UNKNOWN — OWNER TO CONFIRM]`, and execute end-to-end instead of stopping to quiz the operator.
2. **Mandatory Pre-Finish Audit:** Run a read-only `ig-evidence-review` subagent pass before handing off consequential deliverables or release packets to verify exact sources, version custody, and authority bounds.

## 3. Work Operating System (`P-WOS`) & Boundary Rules
1. **Seven Graph Types:** Classify new graph views as capability inventory, reference process model, planning decision flow, plan dependency graph, execution and provenance trace, outcome map, or target system architecture.
2. **Stable Record IDs (`K-SIDECAR-01`):** Use shared IDs (`P-*`, `K-*`, `A01..A10`, `MW/MP/MK/CD/CH/OP-*`) across registers, prose, and Mermaid nodes.
3. **Blocking vs. Advisory Edges (`K-GRAPH-01`):** Use solid arrows (`-->`) for verified/blocking dependencies and dashed arrows (`-.->`) for advisory or unverified links.
4. **Planned vs. Observed Separation (`K-WOS-03`, `K-ARCH-03`):** Bind claims to the exact session, revision, or receipt.
5. **External Source Boundaries:** Keep Asana strictly read-only. Keep restricted employer material in its authorized source system.

## 4. Orchestrator-Producer Role & Hub-and-Spoke MCP Rules (`K-MCP-01`)
1. **Single Control Plane (No Double Bureaucracy):** `Crucible Domain` is the sole orchestrator-producer. Domain systems (`the-writers-room`, future `Story-Lane`, etc.) connect via lightweight 3-file workspace plugins (`.agents/plugins/<spoke>/{plugin.json,mcp_config.json,skills/<spoke>/SKILL.md}`) and expose **deterministic domain mechanics** (form recognition, client templates, timing/cut math, `.md`/`.docx` export)—never a second competing orchestration loop.
2. **Selection != Craft:** Never pipe raw `crucible_gate.py route` lexical rankings directly into generation packets. Let the domain spoke recognize the deliverable form first and attach at most **one** form-pinned Crucible procedure (`MW-01`, `MW-02`, `MW-04`), abstaining (`null`) when no procedure is pinned for that form.
3. **Authority != Craft:** Crucible procedures enter spoke packets strictly as non-evidentiary craft guidance (`role: "method"`, `use: "craft"`). They never grant project facts, asset clearance, or cut approval; fresh or resumed cuts on existing material require project-bound decision authority or hold at preflight.
4. **Stage-Matched Verification (Producer Signal Over Compliance Churn):** Enforce strict claim-by-claim evidentiary and timing gates on locked downstream execution (`timed_av` cuts on existing material, public factual claims). On exploratory upstream creative forms (`treatment`, `production_brief`), audit real source/authority boundaries and recipient usability—never prosecute normal creative or art-direction prose for unlogged sensory details (such as fonts or lighting mood).
