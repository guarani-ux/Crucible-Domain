# 01 — Target System Architecture & Locations (`IG-ARCH`)

**WOS Graph Type:** `Target system architecture` (*How should the system be wired? Components, interfaces, information flows, and authority boundaries.*)  
**Related Records:** `P-INNER-GRAVITY`, `P-WOS`, `K-WOS-01`, `K-SIDECAR-01`, `K-GRAPH-01`, `A02` (Kageyoni), `A06` (Knowledge Sidecar)

---

## 1. Observed Current Wiring vs. Target Installed Wiring (`IG-ARCH-01`)

Solid edges (`-->`) represent **observed active links** in session `79d6267e-43c7-484f-9c9d-4e6762060706`. Dashed edges (`-.->`) represent **staged target links** in [`./install_pack/`](./install_pack/) waiting to be installed into `Crucible Domain` (`K-GRAPH-01`).

```mermaid
flowchart LR
    subgraph HUB["Workspace Hub · Crucible Domain (OneDrive)"]
        CD_README["README.md (Hub Entry)"]
        PROJ_REG["Project/Project_Register.md (P-WOS, P-STORY-LANE, P-CONSTELLATION)"]
        WOS_DIR["Project/Work Operating System/ (7-Graph Standard)"]
        IG_DIR["Project/Inner Gravity/ (P-INNER-GRAVITY + install_pack/)"]
        KNOW_REG["Knowledge/Knowledge_Register.md (K-WOS-01..03, K-ARCH-01..03)"]
        ARCH_EX["Knowledge/Repository Archaeology/ (A01..A10 Exhibits)"]
        GRAPHS_DIR["Graphs/ (Cross-project views · currently empty)"]

        WS_AGENTS["AGENTS.md (Staged in install_pack/)"]
        WS_IDEAS["IDEAS.md (Staged in install_pack/)"]
        WS_ACC[".agents/acceptance.lock.json (Staged in install_pack/)"]
    end

    subgraph GEM["Global Root · C:/Users/flowe/.gemini"]
        GEM_MD["GEMINI.md (5,100 B · Sovereign Constitution)"]
        SET_JSON["settings.json (oauth-personal)"]
    end

    subgraph CFG["Protected Config Root · C:/Users/flowe/.gemini/config"]
        CFG_AGENTS["AGENTS.md (160 B pointer)"]
        HOOKS_JSON["hooks.json (reliability_v4 + operator-crucible)"]
        MCP_JSON["mcp_config.json (7 server defs)"]
        SKILLS_JSON["skills.json (31-entry whitelist)"]
        HV4["scripts/hook_v4.py (1,374 lines · AST/Shell/Stop guard)"]
        OR_PY["scripts/operator_router.py (202 lines · SessionStart/PreInvocation)"]
        CG_PY["scripts/code_graph.py (Forensic symbol scanner)"]
    end

    subgraph AGY["Runtime State · C:/Users/flowe/.gemini/antigravity"]
        BRAIN_CUR["brain/79d6267e.../ (Baselines + reliability-events.jsonl)"]
        BRAIN_ALL["brain/ (359 historical conversation dirs)"]
        KNOW_STORE["knowledge/ (knowledge.lock only · empty)"]
    end

    subgraph EXT["External Roots"]
        KAG_SKILLS["C:/Kageyoni/.agents/skills/ (12 of 31 loaded)"]
        WSL_LEDGER["WSL · /home/flowe/.../IDEAS.md (Skipped by UNC guard)"]
    end

    CFG_AGENTS -->|"Redirects global rules to"| GEM_MD
    HOOKS_JSON -->|"Invokes via absolute path"| HV4
    HOOKS_JSON -->|"Invokes via relative ./scripts/ path"| OR_PY
    SKILLS_JSON -->|"Filters include_only from"| KAG_SKILLS
    HV4 -->|"Reads baselines & appends events to"| BRAIN_CUR
    OR_PY -.->|"Emits static text fallback when local IDEAS.md missing"| WSL_LEDGER

    IG_DIR -.->|"Stages and installs"| WS_AGENTS
    IG_DIR -.->|"Stages and installs"| WS_IDEAS
    IG_DIR -.->|"Stages and installs"| WS_ACC

    WS_IDEAS -.->|"Intercepted at SessionStart by"| OR_PY
    WS_ACC -.->|"Enforced at Stop gate by"| HV4
    WS_AGENTS -.->|"Binds session entry to"| CD_README
    WS_AGENTS -.->|"Enforces 7-graph grammar from"| WOS_DIR
    WS_AGENTS -.->|"Requires lookup in"| PROJ_REG
    WS_AGENTS -.->|"Requires lookup in"| KNOW_REG
```

---

## 2. Rule & Context Discovery Hierarchy (`IG-ARCH-02`)

```mermaid
flowchart TD
    TURN["Incoming Prompt in Crucible Domain"] -->|"Always injects"| GLOBAL["Global Layer · .gemini/GEMINI.md + .gemini/config/AGENTS.md"]
    TURN -->|"Runs SessionStart / PreInvocation"| ROUTER["Hook Layer · operator_router.py"]
    TURN -.->|"Will auto-load once installed"| LOCAL["Workspace Layer · Crucible Domain/AGENTS.md"]

    ROUTER -->|"Checks workspacePaths for"| FIND_LEDGER{"Crucible Domain/IDEAS.md exists?"}
    FIND_LEDGER -->|"No (Current State)"| FALLBACK["Inject static text pointer to WSL IDEAS.md"]
    FIND_LEDGER -.->|"Yes (After Install)"| LIVE_WIP["Parse Stage 1..4 & Shipped counts via parse_ledger_summary()"]

    LOCAL -.->|"Points agent at turn 1 to"| REGISTERS["Project_Register.md + Knowledge_Register.md + 00-Exhibit_Index.md"]
    LOCAL -.->|"Enforces"| WOS_RULES["P-WOS 7-Graph Grammar + K-GRAPH-01 + Asana Read-Only"]
```

---

## 3. Authority Boundaries & File Inventory (What the Graph Cannot Show)

| Layer ID | Exact Path | Authority Tier & Protection | Observed State & Scale Implication |
| --- | --- | --- | --- |
| `IG-ROOT-GLOBAL` | `C:\Users\flowe\.gemini\GEMINI.md` | **Protected (`hook_v4.py` `RW-04`)** · Global | 5,100 bytes. Defines 3-Tier Reversibility, `idea-crucible`, `mode-reframe`, and `mode-worktree-build`. |
| `IG-ROOT-CFG` | `C:\Users\flowe\.gemini\config\` | **Protected (`PROTECTED_PREFIXES`)** · Global | Contains `hooks.json`, `mcp_config.json`, `skills.json`, `scripts/`. Also contains 14 `.bak*` files (`GEMINI.md.bak*`, `AGENTS.md.bak*`, `hooks.json.bak*`, `config.json.bak*`, `hook_v4.py.bak*`, `pre_tool_guard.js.bak*`). |
| `IG-ROOT-BRAIN` | `C:\Users\flowe\.gemini\antigravity\brain\` | **Hook State Protected (`RW-06`)** · Per-Session | 359 conversation directories (`conversation_summaries.db` is 58.5 MB). Active dir `79d6267e-43c7-484f-9c9d-4e6762060706` holds `db-baseline.json` (2 B), `test-baseline.json` (2 B), `root-files-baseline.json` (2 B), and `reliability-events.jsonl`. |
| `IG-ROOT-KNOW` | `C:\Users\flowe\.gemini\antigravity\knowledge\` | Runtime Store | Contains only `knowledge.lock`. Cross-project lessons instead live in `Crucible Domain\Knowledge\Knowledge_Register.md` and `Repository Archaeology\`. |
| `IG-ROOT-HUB` | `C:\Users\flowe\OneDrive\Desktop\Crucible Domain\` | **Workspace Root (Tier 0/1)** | Synced with Google Drive (`1jpG-7DjOa2xtiYPbBhL07qmCRSVrK1fU`). Houses `Project\`, `Knowledge\`, `Graphs\`, `Calgary Public Library\`, and `Personal Work\`. |
