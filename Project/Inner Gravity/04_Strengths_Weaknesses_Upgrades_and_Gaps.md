# 04 — Planning Decision Flow, Dependency Graph & Outcome Map (`IG-DEC`, `IG-PLAN`, `IG-OUT`)

**WOS Graph Types:**
- `Planning decision flow` (*How do we make a plan? Request, evidence, options, capacity, decisions, and authority.*)
- `Plan dependency graph` (*What needs to happen on this project? Named assignments, prerequisites, parallel work, and receiving checks.*)
- `Outcome map` (*What should change, and how will we know? Desired changes and the evidence that would establish them.*)

**Related Records:** `P-INNER-GRAVITY`, `P-WOS`, `K-WOS-01..03`, `K-ARCH-01..03`, `K-GRAPH-01`, `K-SIDECAR-01`

---

## 1. Planning Decision Flow: Upgrading the Harness for `Crucible Domain` (`IG-DEC-01`)

```mermaid
flowchart TD
    req["Request · Upgrade Antigravity harness to scale with Crucible Domain & P-WOS"] -->|"Grounded by"| ev["Evidence · Direct config inspection + 4-Subagent Frontier Benchmark + WOS Catalog"]

    ev -->|"Exposes constraint"| auth_bound["Authority Boundary · .gemini/config & GEMINI.md are Protected (hook_v4.py RW-04)"]
    ev -->|"Exposes gap"| ws_blind["Workspace Gap · Crucible Domain has no local AGENTS.md, IDEAS.md, or acceptance.lock.json"]

    auth_bound -->|"Evaluates"| opt1["Option A · Mutate global .gemini/config directly (Rejected: violates Protected File boundary)"]
    ws_blind -->|"Evaluates"| opt2["Option B · Stage and inspect files and operator specs in Inner Gravity (Selected)"]

    opt2 -->|"Authorized under Tier 0/1 by"| dec["Decision · Build 7-Graph WOS Suite + Stage & Verify install_pack/ before root promotion"]
```

---

## 2. Plan Dependency Graph: Staged Installation & Receiving Checks (`IG-PLAN-01`)

**Current pickup.** Inspect the desktop Crucible Domain root for `AGENTS.md`, `IDEAS.md`, and `.agents/acceptance.lock.json`. The [Drive pack](https://drive.google.com/drive/folders/1gZJYLX5FEI97KIYnOCCT5wajx1w16GDZ) contains the staged ledger and normalized hooks file. The two protected workspace specifications are embedded in the [Inner Gravity README](https://drive.google.com/file/d/1pyrr2O0dMqXnehJpjbR_I8RlpcnVJNQ6/view). Record current desktop state before any operator installation. Drive visibility and a fresh local session are separate receiving checks.

Solid edges (`-->`) are **blocking prerequisites**; dashed edges (`-.->`) are **optional/advisory follow-ons** (`K-GRAPH-01`).

```mermaid
flowchart TD
    ig01["IG-TASK-01 · Upgrade Inner Gravity 01..04 + README to 7-Graph WOS Standard"] -->|"Supplies exact schemas for"| ig02["IG-TASK-02 · Stage IDEAS ledger and normalized hooks file, embed protected specs in README"]

    ig02 -->|"Requires deterministic pre-install test in"| ig03["IG-TASK-03 · Check staged material and inspect the three target paths on desktop"]

    ig03 -->|"Unblocks workspace install"| ig04["IG-TASK-04 · Operator installs workspace files from the staged ledger and embedded specs"]
    ig03 -.->|"Supplies reviewed diff for operator-approved global update"| ig05["IG-TASK-05 · Replace ./scripts/ with absolute path in .gemini/config/hooks.json & archive .bak* files"]

    ig04 -->|"Verified by"| rc01["Receiving Check RC-01 · operator_router.py session-start reports Live IDEAS.md WIP counts"]
    ig04 -->|"Verified by"| rc02["Receiving Check RC-02 · hook_v4.py qualification() validates all required_files in Crucible Domain"]
    ig04 -.->|"Enables cross-project views in"| ig06["IG-TASK-06 · Populate Crucible Domain/Graphs/ & register P-INNER-GRAVITY in Project_Register.md"]
```

---

## 3. Outcome Map: Frontier Parity & WOS Alignment (`IG-OUT-01`)

```mermaid
flowchart LR
    subgraph CHANGES["Desired System Changes"]
        c1["IG-OUT-01 · Zero Cold-Start Blindness in Crucible Domain"]
        c2["IG-OUT-02 · Live WIP Ledger at SessionStart (No WSL Dead-End)"]
        c3["IG-OUT-03 · Deterministic Turn-End File & Syntax Verification"]
        c4["IG-OUT-04 · WOS 7-Graph & Provenance Custody Across Agents"]
    end

    subgraph EVIDENCE["Establishing Evidence & Receiving Checks"]
        e1["Fresh session auto-loads Crucible Domain/AGENTS.md & cites Project/Knowledge Registers at Turn 1"]
        e2["operator_router.py session-start outputs: Local IDEAS.md (IDEAS.md) — Active(WIP<=1): 1"]
        e3["hook_v4.py stop parses .agents/acceptance.lock.json & blocks missing/empty core artifacts"]
        e4["All Inner Gravity graphs use stable IDs (K-SIDECAR-01) and solid vs. dashed edges (K-GRAPH-01)"]
    end

    c1 -->|"Established when"| e1
    c2 -->|"Established when"| e2
    c3 -->|"Established when"| e3
    c4 -->|"Established when"| e4
```

---

## 4. Synthesis of the 4-Agent Frontier Benchmark & Upgrade Ledger

| Aspect | Observed or Reported Current Setup | Gap Identified | Proposed Change and Staging Status |
| --- | --- | --- | --- |
| **01 · Architecture & Locations** | Per-session baseline snapshots (`db-baseline.json`, `test-baseline.json`, `root-files-baseline.json`) + `skills.json` filtering | No workspace-local `AGENTS.md` or `IDEAS.md`; `.bak*` clutter; `antigravity/knowledge/` empty | Stages `install_pack/IDEAS.md`, embeds the protected `AGENTS.md` specification in the README, and maps `Crucible Domain/Knowledge/` (`Knowledge_Register.md` + `A01..A10`) as the canonical cross-project memory layer |
| **02 · Lifecycle & Hooks** | `hook_v4.py` AST & regex anti-reward-hacking (`RW-01..RW-11`), shell write-bypass blocking (`RW-03`), out-of-band test hash checks (`FM-BASE-01`) | Relative `./scripts/` path in `hooks.json`; `.agents/acceptance.lock.json` unwired | Embeds the protected `acceptance.lock.json` specification in the README and stages `install_pack/hooks.json.normalized`. Verify hook behavior in a fresh local session after authorized installation. |
| **03 · Tools, Skills & MCPs** | Progressive disclosure (lazy MCP schemas + on-demand `SKILL.md`); clean `browser` vs. `chrome-devtools-mcp` split; `subagent`/`workflow`/`swarm` range | Silent drift between `mcp_config.json` / `skills.json` (31 listed vs. 12 loaded) and live session; `gdocs`/`gsheets`/`gcalendar` disconnected | Documents exact verified vs. unverified capability inventory (`IG-CAP-01`) per `K-WOS-03` so plans never assume unverified tool access |
| **04 · WOS & Scale Readiness** | Strong individual safety & routing primitives | Graphs lacked `P-WOS` 7-graph typing, stable IDs (`K-SIDECAR-01`), and solid-vs-dashed dependency labeling (`K-GRAPH-01`) | Upgrades all `Inner Gravity` views to the `Work Operating System` 7-graph standard so agent and human handoffs share one visual and operational language |
