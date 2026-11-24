# 01 — System Topology & Runtime Lifecycle

**WOS Graph Types:** `Target system architecture` & `Reference process model` (`P-WOS` / `P-INNER-GRAVITY` / `K-GRAPH-01`)

> Solid arrows (`-->`) represent verified, active runtime paths observed in `.agents/hooks.json`, `crucible_gate.py`, and `doctor` output. Dashed arrows (`-.->`) represent fragile, overlapping, or host-coupled boundaries.

---

## 1. Three-Chain Hook Execution Model (Per-Turn Lifecycle)

Every Antigravity turn inside `C:\crucible-domain` currently triggers **three separate hook configurations**:
1. **Global Config (`~/.gemini/config/hooks.json`):** `operator_router.py` (`SessionStart`, `PreInvocation`) + `sentinel.py` (`PreToolUse`, `PostToolUse`, `Stop`).
2. **Workspace Gate (`.agents/hooks.json`):** `crucible_gate.py` (`SessionStart`, `PreToolUse`).
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
    GLB-->>AGY: Inject global constitution status
    AGY->>WSP: SessionStart -> crucible_gate.py session-start
    WSP->>IDX: build_index() (~32ms RAM)
    WSP-->>AGY: Inject domain counts, git HEAD, spokes, SHIFTING_SAND
    AGY->>IG: SessionStart -> observe.py session-start

    Note over AGY,WSP: Agent attempts write_file or edit_file
    AGY->>GLB: PreToolUse -> sentinel.py (Orient-Before-Edit, 3-Strike, AST, RW-04)
    AGY->>WSP: PreToolUse -> crucible_gate.py pre-tool
    alt Target in empty CPL / Personal / Graphs without GROUND_TRUTH.md
        WSP-->>AGY: DENY (SHIFTING_SAND)
    else Ground truth exists or non-empty domain
        WSP-->>AGY: ALLOW
    end

    Note over AGY,IG: Agent finishes turn
    AGY->>GLB: Stop -> sentinel.py (Verify-Before-Stop + acceptance.lock)
    AGY->>IG: Stop -> observe.py stop (receipt)
```

---

## 2. Modular Package Architecture (`crucible/` + Control Plane + Spokes)

Following Waves 1–4.5 (`de90370` -> `a3b9f4a`), the former `crucible_index.py` monolith is split into **13 focused modules** under [`.agents/scripts/crucible/`](../.agents/scripts/crucible/__init__.py) behind a backwards-compatible shim at [`crucible_index.py`](../.agents/scripts/crucible_index.py), while [`crucible_gate.py`](../.agents/scripts/crucible_gate.py) serves as the unified CLI/hook control plane. Offline research/mining (`forge`, `sieve`, `exporter`, `ledger`) runs inside the `crucible-observatory` MCP spoke.

```mermaid
flowchart LR
    GATE["crucible_gate.py<br/>Hooks + CLI (discover, campaign, story, g5-check, kernel)"] -->|"_resolve_index_module()"| SHIM["crucible_index.py<br/>Backwards-compatible shim"]

    subgraph PKG[".agents/scripts/crucible/ (13 Modular Files)"]
        CORE["__init__.py, models.py, indexer.py, router.py, doctor.py"]
        EXEC["tx_patch.py, campaign_ir.py, contracts.py, solver.py"]
        AUTO["ast_scanner.py, replay_loop.py, story_engine.py, outcome_ledger.py"]
    end

    subgraph ENGINE["Control Plane & Verification Scripts (.agents/scripts/)"]
        KERN["crucible_kernel.py + ram_ml_engine.py + ram_ml_daemon.py"]
        VER["verify_all.py (22 parallel checks) + mutation_gate.py (5/5 kills) + test_quality_gate.py"]
    end

    SHIM --> PKG
    GATE --> ENGINE
    GATE --> PKG
    CORE -.->|"Optional Path.home()/.gemini/config"| HOST["Host Global Config ([INFO] when absent)"]
    OBS["crucible-observatory MCP Spoke<br/>(forge, sieve, exporter -> capability_map.json)"] -.->|"Imports crucible.indexer"| CORE
```

### Why this matters for runtime & maintenance
- **Cold-start speed stays ~33–37 ms** because `build_index()` only parses local Markdown and JSON files.
- **Clean separation:** Heavy offline mining (`forge`/`sieve`/`exporter` in `crucible-observatory`) stays out of the hot `<50ms` path while `tx_patch.py`, `campaign_ir.py`, `solver.py`, `ast_scanner.py`, `replay_loop.py`, `story_engine.py`, and `outcome_ledger.py` stay deterministic and 0-LLM inside `.agents/scripts/crucible/`.
