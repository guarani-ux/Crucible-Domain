# 05 — Whole-System Observatory, Session `4188f88a` Causal Trace & Honest Gaps (`IG-OBS`, `IG-TRACE`, `IG-GAP`)

**WOS Graph Types:** `Target system architecture`, `Execution and provenance trace`, & `Outcome map` (`P-WOS` / `K-GRAPH-01` / `K-ARCH-03`)  
**Related Records:** `P-INNER-GRAVITY`, `P-CRUCIBLE-CIRCULATION`, `P-GOVERNANCE`, `P-STORAGE`, `K-WOS-03`, `K-ARCH-01..03`  
**Reproduce live metrics anytime:** `python "Project/Inner Gravity/collect_observatory.py"`

This document intentionally shows **both what works and what is weak, fragile, or untested** across `Crucible Domain`, `guarani-ux/antigravity-config`, external skill roots, and session `4188f88a-dc0c-4bba-96bb-c69ea9c4c1ee` (November 22–23, 2026).

---

## 1. Whole-System Topology & Cross-Boundary Coupling (`IG-OBS-01`)

Solid edges (`-->`) show **verified live active links**. Dashed edges (`-.->`) show **fragile, manual-sync, hardcoded-OS, or incomplete seams**.

```mermaid
flowchart LR
    subgraph CD["Repo 1 · guarani-ux/Crucible-Domain (OneDrive + Drive)"]
        CD_DOCS["README.md, Registers, 55 Procedures, 12 Roles, A01..A10"]
        CD_AGENTS["AGENTS.md + IDEAS.md + .agents/acceptance.lock.json"]
        CD_HOOKS[".agents/hooks.json (SessionStart, PreToolUse, Stop)"]
        CD_GATE[".agents/scripts/crucible_gate.py + crucible_index.py (13 tests)"]
        CD_IG[".agents/plugins/inner-gravity/ (rules + 3 ig-* skills + observe.py)"]
        CD_DRIVE["Sync Locks (.tmp.drivedownload / .tmp.driveupload)"]
    end

    subgraph AC["Repo 2 · guarani-ux/antigravity-config (~/.gemini/config)"]
        AC_GEM["GEMINI.global.md + bootstrap.ps1"]
        AC_HOOKS["hooks.json.portable (relative ./scripts/...)"]
        AC_LIVE_HOOKS["hooks.json (live copy · C:/Users/flowe/...)"]
        AC_HV4["scripts/hook_v4.py (1,486L · 0 unit tests!)"]
        AC_OR["scripts/operator_router.py (8 regexes · 4 unit tests)"]
        AC_SKJSON["skills.json (11 Kageyoni skills) + 14 global skills"]
        AC_MCP["mcp_config.json (2 GCP MCP URLs)"]
    end

    subgraph HOST["Untracked Host Runtime (~/.gemini/ & External Disk)"]
        HOST_GEM["~/.gemini/GEMINI.md (4,910B live system prompt)"]
        HOST_SECRETS["oauth_creds.json, google_accounts.json, config.json (excluded)"]
        HOST_BRAIN["~/.gemini/antigravity/brain/<session>/ (events + receipts + transcript)"]
        KAGE["C:/Kageyoni/.agents/skills/ (guarani-ux/Kageyoni · dirty uncommitted edits)"]
    end

    HOST_GEM -->|"Eager <RULE[user_global]> every turn"| TURN["Live Antigravity Turn"]
    CD_AGENTS -->|"Workspace rules"| TURN
    CD_IG -->|"Always-on inner-gravity.md + 32 stop receipts"| TURN

    AC_LIVE_HOOKS -->|"PreToolUse / PostToolUse / Stop"| AC_HV4
    AC_LIVE_HOOKS -->|"SessionStart / PreInvocation"| AC_OR
    CD_HOOKS -->|"SessionStart / PreToolUse / Stop"| CD_GATE
    CD_GATE -->|"Indexes in 26ms RAM"| CD_DOCS

    AC_GEM -.->|"Manual/bootstrap sync (drift risk if edited outside config/)"| HOST_GEM
    AC_HOOKS -.->|"Requires bootstrap.ps1 -Force to replace C:/Users/flowe path"| AC_LIVE_HOOKS
    AC_SKJSON -.->|"Hardcoded Windows path dependency"| KAGE
    CD -.->|"Git + OneDrive + Drive triple-sync risk"| CD_DRIVE
    AC_HV4 -->|"Writes telemetry to"| HOST_BRAIN
    CD_IG -->|"Writes JSON receipts to"| HOST_BRAIN
```

---

## 2. What Actually Influenced Session `4188f88a` (`IG-TRACE-02`)

Observed from `reliability-events.jsonl` (`183` tool calls, `0` failed tool exceptions logged), `inner-gravity-observations/` (`33` lifecycle receipts), and `transcript.jsonl` (`364` steps, `37` user inputs, `5` model configs: `gemini-4-neon-xhigh/medium`, `claude-opus-5-5-medium`, `gemini-4-hydrogen-xhigh/high`):

```mermaid
flowchart TD
    T0["Turn 0 · SessionStart"] -->|"Succeeded"| OR_SS["operator_router.py: injected IDEAS.md summary"]
    T0 -.->|"FAILED SILENTLY (exit=2 · cwd=.agents)"| CG_FAIL[".agents/hooks.json -> missing .agents/.agents/scripts/crucible_gate.py"]

    OR_SS -->|"Combined with GEMINI.md + 66 skill headers"| REFLX["Model Reflex: Plumbing-First + Silent Over-Planning"]
    CG_FAIL -.->|"Caused Turn-0 workspace blindness until mid-session audit"| REFLX

    REFLX -->|"Corrected by user prompts & Plan Mode (2 enter / 7 exit)"| AUDIT1["66-Skill Empirical Audit (371 transcripts)"]
    AUDIT1 -->|"Revealed: 47/66 (71%) had 0 organic reads in last 50 sessions"| SUB["Killed 3 subagents mid-flight; switched to local RAM Python"]

    SUB -->|"Rebuilt capability circulation in RAM"| BUILD["crucible_index.py (129 items / 26ms) + 10 ChatGPT bindings + 13/13 tests"]
    BUILD -->|"Hit hook_v4.py PROTECTED_FILES boundary"| STAGE["Staged install_pack/ + operator apply_protected_fixes.ps1"]

    STAGE -->|"Operator executed .ps1 -> 15 PASS / 0 FAIL"| FIXED[".agents/hooks.json + AGENTS.md + acceptance.lock.json LIVE"]
    FIXED -->|"Followed by"| GH["GitHub Project #1 + guarani-ux/Crucible-Domain + guarani-ux/antigravity-config"]
```

### What Steered vs. What Failed to Steer in `4188f88a`
1. **Hard tool gates & Plan Mode actually steered execution:** `hook_v4.py` `PROTECTED_FILES` forced clean staged `.ps1` handoffs instead of silent protected-file edits; `plan_mode` (`2` entries, `7` exits) gated every Tier-1/Tier-2 jump.
2. **Passive prose skills mostly failed to fire:** Across `371` historical transcripts, `47/66` (`71%`) skills had `0` organic reads in the last `50` sessions (`domain-expansion` = `0`, `negative-space` = `0`, `diagnosing-bugs` = `0`, `visual-reflex` = `0`). Only hooked (`operator_router.py`) or always-on (`inner-gravity.md`) rules consistently fired.
3. **Broken local hook hid for an unknown duration:** `.agents/hooks.json` exited `2` silently because Antigravity runs hooks from the `hooks.json` directory (`.agents/`), not repo root — proving why closed-loop `cwd`-aware `doctor` checks are mandatory.
4. **Cloud/subagent latency vs. local RAM:** Spawning `3` parallel subagents (`0e65bb9c`, `18039589`, `bc2b584c`) was slower and less deterministic than running 1 local Python script in RAM (`<50ms` index build); all 3 were killed cleanly in favor of local RAM computation.

---

## 3. Hardening, Bottlenecks & Immaturity Matrix (`IG-GAP-01`)

```mermaid
flowchart LR
    classDef hard fill:#1b4332,stroke:#52b788,color:#fff
    classDef partial fill:#5c4d00,stroke:#f4a261,color:#fff
    classDef weak fill:#6b1d1d,stroke:#e63946,color:#fff

    H1["crucible_gate.py + crucible_index.py<br/>(13 pytest tests · 15 PASS doctor)"]:::hard
    H2["inner-gravity observe.py<br/>(33 live JSON receipts)"]:::hard
    H3["operator_router.py<br/>(4 unit tests · dedup verified)"]:::partial

    W1["hook_v4.py<br/>(1,486 lines · 0 UNIT TESTS)"]:::weak
    W2["operator_router.py recall/F1<br/>(0 historical transcript replay score)"]:::weak
    W3["skills.json -> C:/Kageyoni<br/>(OS-specific path + dirty Kageyoni repo)"]:::weak
    W4["Crucible Domain on OneDrive/Drive<br/>(.tmp.drive* lock risk alongside .git)"]:::weak
    W5["SHIFTING_SAND & IG-TRAIN-001<br/>(0 real CPL/Personal deliverables run)"]:::partial

    H1 -.->|"Depends on operator running migrate_to_local_git.ps1"| W4
    H3 -.->|"Needs transcript eval before adding more regexes"| W2
    H3 -.->|"Still disconnected from PreToolUse write lock"| W1
```

### Exact Weakness & Immaturity Ledger (`[OBSERVED]`)

| Component | Maturity | Specific Weakness / Bottleneck | Evidence | Next Concrete Fix |
|---|---|---|---|---|
| `hook_v4.py` | **Enforced, Untested** | **`1,486` lines / `61.8 KB` with `0` unit tests**; any regex or AST regression fails silently or blocks valid work | `test_hook_v4.py` absent in `antigravity-config` | Add focused stdlib unit tests for `PROTECTED_FILES`, `RW-03`, and `stop()` |
| `operator_router.py` | **Partial** | `8` hand-written regexes with **no measured precision/recall** on historical prompts; not bridged to `PreToolUse` write locks | `4` synthetic unit tests only; no transcript replay run | Score against `brain/` prompt corpus (`K-ARCH-02`) before tuning |
| `skills.json` + `hooks.json` | **Fragile Portability** | `skills.json` hardcodes `C:/Kageyoni/.agents/skills`; live `hooks.json` still has `C:/Users/flowe/...` until `bootstrap.ps1 -Force` runs | Observed in `antigravity-config` + `collect_observatory.py` | Bundle/vendor needed skills into `antigravity-config` & apply `hooks.json.portable` |
| `GEMINI.md` sync | **Manual Seam** | Live `~/.gemini/GEMINI.md` sits outside `config/` Git tree; edits there drift unless synced to `GEMINI.global.md` | Outside `config/.git` | Run `bootstrap.ps1 -Force` or symlink `~/.gemini/GEMINI.md` |
| `Crucible Domain` storage | **Split-Brain Risk** | Git repo still lives inside OneDrive + Google Drive (`.tmp.drivedownload`, `.tmp.driveupload`) | `crucible_gate.py doctor` `[WARN]` | Run `migrate_to_local_git.ps1 -Apply` between sessions |
| Real domain deliverables | **Untested in Field** | `Calgary Public Library/` and `Personal Work/` have **`0` deliverables**; `SHIFTING_SAND` and `inner-gravity` `0.1.1` unproven on real work | `session-start` count `0 [EMPTY]` | Complete 1 `GROUND_TRUTH.md` intake + real deliverable (`P-DELIVERABLE`) |
