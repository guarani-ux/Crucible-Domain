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

## 2. Modular Package Architecture (`crucible/` + Thin Shim)

Following Wave 1 (`de90370`) and Wave 2 (`97a5b61`, `13152ec`), the former 2,552-line `crucible_index.py` monolith is split into focused acyclic modules under [`.agents/scripts/crucible/`](../.agents/scripts/crucible/__init__.py) behind a 102-line backwards-compatible shim at [`crucible_index.py`](../.agents/scripts/crucible_index.py), while [`crucible_gate.py`](../.agents/scripts/crucible_gate.py) (805L) imports it via `_resolve_index_module()`.

```mermaid
flowchart LR
    GATE["crucible_gate.py (805L)<br/>Hooks + Contract + CLI Dispatch"] -->|"_resolve_index_module()"| SHIM["crucible_index.py (102L)<br/>Backwards-compatible shim"]

    subgraph PKG[".agents/scripts/crucible/ (8 Modular Files)"]
        MOD["models.py (575L)<br/>Dataclasses, constants, CORE_ENTRY_DOCS"]
        IDX["indexer.py (545L)<br/>build_index (~32-37ms RAM) + primitive validation"]
        RTR["router.py (178L)<br/>route_query, lexical/ID scoring"]
        FRG["forge.py (403L)<br/>forge_brief domain synthesis"]
        DOC["doctor.py (443L)<br/>run_doctor, links, [INFO] portability"]
        SIV["sieve.py (489L · Standalone)<br/>fetch_github_repos, melt-diff, melt-scan"]
        EXP["exporter.py (88L)<br/>write_capability_map -> capability_map.json"]
    end

    SHIM --> PKG
    IDX -->|"Data types & maps"| MOD
    RTR -->|"Data types & stopwords"| MOD
    FRG -->|"Domain cues + scoring"| RTR
    DOC -->|"Index + primitive checks"| IDX
    DOC -.->|"Optional Path.home()/.gemini/config"| HOST["Host Global Config ([INFO] when absent)"]
    SIV -.->|"Shells out to gh api (network)"| GH["GitHub API (guarani-ux)"]
    EXP -->|"Writes 146 capabilities"| MAP["Graphs/capability_map.json"]
```

### Why this matters for runtime & maintenance
- **Cold-start speed stays ~32–37 ms** because `build_index()` only parses local Markdown and JSON files.
- **Clean boundaries:** Networked GitHub sieving (`sieve.py`), portability-aware diagnostics (`doctor.py`), heuristic synthesis (`forge.py`), and JSON map export (`exporter.py`) are decoupled from core parsing (`indexer.py`).
