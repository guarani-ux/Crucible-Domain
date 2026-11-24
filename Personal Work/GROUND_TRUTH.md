# Personal Work — Canonical Ground Truth (`GROUND_TRUTH.md`)

> **Owner & Authority:** Elijah-Levi Flowers-Nelson ("Levi") — sovereign personal workspace.  
> **Domain Isolation Boundary:** Strictly separate from `Calgary Public Library/`. Zero employer-restricted material, zero coworker names, and zero internal CPL Asana URLs belong here.  
> **Status:** Active (`SHIFTING_SAND` satisfied; synthesized from verified local records in [README.md](../README.md) and [Project_Register.md](../Project/Project_Register.md)).

---

## 1. What Belongs in `Personal Work/` (Boundary Clarification)

`Personal Work/` is the home for **Levi's sovereign personal workstreams** — both **systems/AI engineering** and **independent creative/media work**.

To prevent agents from misreading shared system directories as "distraction" or treating `Personal Work/` as empty:
- **`Personal Work/`** holds active personal workstream briefs, roadmaps, architecture decision logs, creative/media drafts, and standalone personal deliverables.
- **`Project/`**, **`.agents/`**, **`Graphs/`**, and **`Knowledge/`** hold the shared reusable infrastructure, registers, and executable code that power both personal streams and `Calgary Public Library/`.
- **`Calgary Public Library/`** holds strictly authorized Library-scoped work and deliverables.

> **Core Recognition:** Building, verifying, and evolving **`Crucible Domain` (`P-CRUCIBLE`)** itself is **Personal Workstream #1** — an active, self-directed AI systems-engineering project started in January 2026. Crucible serves as the **Orchestrator-Producer Hub (single control plane)** that frames assignments, resolves local ground truth and authority, supplies craft methods, and drives lightweight domain MCP spokes (`.agents/plugins/<spoke>/`, starting with `the-writers-room` and extending to `Story-Lane`). Its live code lives at the repo root (`.agents/`, `Project/`, `Graphs/`, `Knowledge/`) so it can govern every domain, while its personal roadmap, architectural critique, and slice tracking anchor here.

---

## 2. Active & Observed Personal Workstreams `[VERIFIED LOCAL]`

| Stream ID | Personal Workstream | Primary Purpose | Current Home / Observed Artifacts | Status |
| :--- | :--- | :--- | :--- | :--- |
| **PW-01** | **Crucible Domain (`P-CRUCIBLE`)** | Sovereign **Orchestrator-Producer Hub** & AI Work Operating System: single control plane over domain MCP spokes (`K-MCP-01`), deterministic verification gates, RAM capability routing (`149` capabilities in ~30ms), testing philosophy (`K-TEST-01`), mutation kills, and graph-linked project custody. | [Project_Register.md](../Project/Project_Register.md) · [00_System_Atlas_and_Neon_Handoff.md](../Graphs/00_System_Atlas_and_Neon_Handoff.md) · [Testing_Philosophy.md](../Knowledge/Testing_Philosophy.md) · `.agents/plugins/` · `.agents/scripts/` | **Active Flagship** (`C:\crucible-domain`: `22 PASS \| 0 WARN \| 0 FAIL`, CI green) |
| **PW-02** | **Work Operating System & Inner Gravity (`P-WOS`)** | Seven-graph work representation standard, `ig-reconcile` / `ig-evidence-review` / `ig-improve` verification methods, and portable host adapters. | [Project/Work Operating System/README.md](../Project/Work%20Operating%20System/README.md) · [Project/Inner Gravity/README.md](../Project/Inner%20Gravity/README.md) | **Active Architecture** (plugin `v0.1.1` verified on Windows; Issue `#1` closed) |
| **PW-03** | **Independent Media & Story Spokes** | Domain MCP spokes and personal filmmaking/story engines driven by Crucible (`the-writers-room` active spoke at `ef2d065`; `Story-Lane`, `Video-House`, `Story-House`, `nelson-media`). | [.agents/plugins/writers-room/skills/writers-room/SKILL.md](../.agents/plugins/writers-room/skills/writers-room/SKILL.md) · [Project_Register.md](../Project/Project_Register.md) · [Crucible_Primitives.md](../Knowledge/Crucible_Primitives.md) | **Active Spoke Floor** (`writers-room` MCP live; `Story-Lane` next candidate spoke) |

---

## 3. Working Defaults `[PROPOSED DEFAULT]`

1. **One Live Working Copy:** All active work runs in `C:\crucible-domain` (OneDrive copy retired and deleted to eliminate Git/sync split-brain).
2. **PW-01..03 Qualification Gate (Replaces Blanket Freeze — 2026-11-23):** Levi is a first-class operator-recipient of `PW-01..03`. Systems upgrades to Crucible Domain, WOS/Inner Gravity, and domain MCP spokes are explicitly authorized under `WIP <= 1` and `K-TEST-01` 3-case qualification (`bad` miss caught, `good` normal work unbroken, `changed` scoped cleanly); only speculative/untested bolt-ons remain frozen.
3. **Evidence-Bound Progress (`K-TEST-01`):** Every upgrade to `PW-01` (`Crucible Domain`) must close a real architectural gap and pass 3 qualification cases — no speculative bolt-ons.
4. **Deliverable Parity:** Non-code outputs (briefs, scripts, plans) get the same custody rigor as Python code (explicit `depends_on` dependencies, stale detection, plain-English receiver separation where appropriate).

---

## 4. Current Personal Architecture Backlog (`PW-01 · Crucible Domain`)

1. **Completed (`952a5ab`):** Split hot-path safety gate (`crucible_gate.py` + 5-piece `crucible/` kernel) from offline research/mining tools (`forge`, `melt-diff`, `melt-scan`, `risk`, `export-map` moved to `crucible-observatory` MCP spoke).
2. **Demoted / Parked (`2026-11-23`):** `Knowledge/outcome_ledger.json` parked as an optional manual log inside `crucible-observatory` (no automated write-back hook in the `<40ms` Hub kernel).
3. **Active — Slice A (Hub Closure):** Reconcile self-model docs (`00_System_Atlas`, `Personal Work/GROUND_TRUTH.md`), add deterministic plugin/kernel drift check and `depends_on` staleness check (`--strict` option) to `crucible_gate.py check`, and formalize `CAPABILITY_PRECEDENCE` in `router.py`.
4. **Next — Slice B (Spoke Ergonomics):** Lighten the exploratory authoring path (`treatment`, `production_brief`) in `writers-room` (`K-MCP-01`) before cloning the Universal MCP Spoke Template to `Story-Lane`.

---

## 5. Open Personal Intake Holds `[UNKNOWN — OWNER TO CONFIRM]`

| Hold | Question for Levi | Effect Until Confirmed |
| :--- | :--- | :--- |
| `PW-HOLD-01` | Which personal stream runs next after `PW-01` closure (e.g., `PW-01` architectural tightening vs. a `PW-03` personal creative/media slice)? | Keep `Personal Work/` grounded here; do not spawn speculative personal project folders without an explicit target. |
| `PW-HOLD-02` | Public vs. private publication intent for any personal writing, demos, or portfolio pieces derived from `Crucible Domain`. | Keep all personal notes local/private to `guarani-ux/Crucible-Domain` until explicitly cleared for external sharing. |
