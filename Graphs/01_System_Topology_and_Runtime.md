# 01 — System Topology & Runtime Lifecycle

**WOS Graph Types:** `Target system architecture` & `Reference process model` (`P-WOS` / `P-INNER-GRAVITY` / `K-GRAPH-01`)

> Solid arrows (`-->`) represent verified, active runtime paths observed in `.agents/hooks.json`, `crucible_gate.py`, and `doctor` output. Dashed arrows (`-.->`) represent fragile, overlapping, or host-coupled boundaries.

---

## 1. Three-Chain Hook Execution Model (Per-Turn Lifecycle)

Every Antigravity turn inside `C:\crucible-domain` currently triggers **three separate hook configurations**:
1. **Global Config (`~/.gemini/config/hooks.json`):** `operator_router.py` (`SessionStart`, `PreInvocation`) + `hook_v4.py` (`PreToolUse`, `PostToolUse`, `Stop`).
2. **Workspace Gate (`.agents/hooks.json`):** `crucible_gate.py` (`SessionStart`, `PreToolUse`, `Stop`).
3. **Workspace Plugin (`.agents/plugins/inner-gravity/hooks.json`):** `observe.py` (`SessionStart`, `Stop`).

```mermaid
sequenceDiagram
    autonumber
    participant AGY as Antigravity Host
    participant GLB as Global Hooks (~/.gemini/config)
    participant WSP as Workspace Gate (.agents/hooks.json)
    participant IG as Inner Gravity Plugin (observe.py)
    participant IDX as crucible_index.py (RAM)

    AGY->>GLB: SessionStart -> operator_router.py
    GLB-->>AGY: Inject IDEAS.md summary + Mode-Reframe modulator
    AGY->>WSP: SessionStart -> crucible_gate.py session-start
    WSP->>IDX: build_index() (~32ms RAM)
    WSP-->>AGY: Inject domain counts, git HEAD, WIP, SHIFTING_SAND
    AGY->>IG: SessionStart -> observe.py session-start

    Note over AGY,WSP: Agent attempts write_file or edit_file
    AGY->>GLB: PreToolUse -> hook_v4.py (PROTECTED_FILES / safety)
    AGY->>WSP: PreToolUse -> crucible_gate.py pre-tool
    alt Target in empty CPL / Personal / Graphs without GROUND_TRUTH.md
        WSP-->>AGY: DENY (SHIFTING_SAND)
    else Ground truth exists or non-empty domain
        WSP-->>AGY: ALLOW
    end

    Note over AGY,IG: Agent finishes turn
    AGY->>GLB: Stop -> hook_v4.py
    AGY->>WSP: Stop -> crucible_gate.py stop (contract + acceptance.lock)
    AGY->>IG: Stop -> observe.py stop (receipt)
```

---

## 2. Internal Anatomy of `crucible_index.py` (The 2,552-Line Monolith)

Currently, [`crucible_index.py`](../.agents/scripts/crucible_index.py) houses **five unrelated subsystems** in one file, while [`crucible_gate.py`](../.agents/scripts/crucible_gate.py) dynamically imports it via `_resolve_index_module()`.

```mermaid
flowchart LR
    GATE["crucible_gate.py (736L)<br/>Hooks + Contract + CLI Dispatch"] -->|"_resolve_index_module()"| MONO

    subgraph MONO["crucible_index.py (2,552L · 53 top-level defs)"]
        P1["1. Parsers & RAM Indexer<br/>build_index, _index_procedures/roles/exhibits/skills/primitives"]
        P2["2. Query Router & Forge<br/>route_query, forge_brief, _score_entries"]
        P3["3. Health & Hook Doctor<br/>run_doctor, _audit_hooks, _audit_links_and_bindings"]
        P4["4. GitHub Ore Sieve<br/>fetch_github_repos, compute_melt_diff, run_melt_scan"]
        P5["5. CLI & Text Formatters<br/>_format_*_text, main"]
    end

    P1 -->|"Feeds CapabilityIndex"| P2
    P1 -->|"Feeds CapabilityIndex"| P3
    P3 -.->|"Hardcoded Path.home()/.gemini/config"| HOST["Host Global Config"]
    P4 -.->|"Shells out to gh api (network)"| GH["GitHub API (guarani-ux)"]
```

### Why this matters for runtime & maintenance
- **Cold-start speed is great (~32 ms)** because `build_index()` only reads local Markdown/JSON files.
- **Cognitive & edit friction is high** because `melt-scan` (networked GitHub API sieving), `doctor` (host-coupled hook auditing), `forge` (heuristics), and `build_index` (core parser) all live in the same 2,552-line file.
