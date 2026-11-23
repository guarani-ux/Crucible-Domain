# Crucible Domain — Workspace Agent Constitution (AGENTS.md)

> Scope: Applies to all sessions operating inside `Crucible Domain`. Inherits global rules from `~/.gemini/GEMINI.md`.

## 1. Local-First Entry & RAM Capability Routing (`K-WOS-01`, `K-WOS-03`)
Before proposing new folders, plans, or cross-project work, resolve what exists locally first:
- Hub Overview: [README.md](README.md)
- Active & Reviewed Projects: [Project/Project_Register.md](Project/Project_Register.md)
- Cross-Project Findings & Limits: [Knowledge/Knowledge_Register.md](Knowledge/Knowledge_Register.md)
- Historical System Exhibits: [Knowledge/Repository Archaeology/00-Exhibit_Index.md](Knowledge/Repository%20Archaeology/00-Exhibit_Index.md)
- Media Agency Role Cards & Procedures (55): [Knowledge/Media Agency/Skills and Workflows/README.md](Knowledge/Media%20Agency/Skills%20and%20Workflows/README.md) · [Knowledge/Media Agency/Media_Work_Routing.md](Knowledge/Media%20Agency/Media_Work_Routing.md)
- Work Operating System & 7-Graph Standard: [Project/Work Operating System/Work_Operating_System_Graph_Catalog.md](Project/Work%20Operating System/Work_Operating_System_Graph_Catalog.md)
- Antigravity Harness Self-Model: [Project/Inner Gravity/README.md](Project/Inner%20Gravity/README.md)

Route any task, canonical ID (`MW-04`, `PROD-S`, `K-WOS-02`), or legacy ChatGPT `skill_id` in RAM (<100ms):
```sh
python ".agents/scripts/crucible_gate.py" route "<task or ID>"
python ".agents/scripts/crucible_gate.py" doctor
```

## 2. Work Operating System (`P-WOS`) & Boundary Rules
1. **Seven Graph Types:** Classify new graph views as capability inventory, reference process model, planning decision flow, plan dependency graph, execution and provenance trace, outcome map, or target system architecture.
2. **Stable Record IDs (`K-SIDECAR-01`):** Use shared IDs (`P-*`, `K-*`, `A01..A10`, `MW/MP/MK/CD/CH/OP-*`) across registers, prose, and Mermaid nodes.
3. **Blocking vs. Advisory Edges (`K-GRAPH-01`):** Use solid arrows (`-->`) for verified/blocking dependencies and dashed arrows (`-.->`) for advisory or unverified links.
4. **Planned vs. Observed Separation (`K-WOS-03`, `K-ARCH-03`):** Bind claims to the exact session, revision, or receipt.
5. **External Source Boundaries:** Keep Asana strictly read-only. Keep restricted employer material in its authorized source system.
