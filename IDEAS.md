# Crucible Domain — Idea & Slice Ledger (`IDEAS.md`)

> Parsed automatically at `SessionStart` by `C:/Users/flowe/.gemini/config/scripts/operator_router.py` (`parse_ledger_summary`). Keep `Stage 4` at `WIP <= 1`.

## Stage 4: Active (WIP <= 1)
- [P-HOOK-CLEANUP] hook_v4.py cleanup (after Contract Stop Gate is proven): narrow PreToolUse matcher to write/read/shell/MCP tools; remove RW-10 (replaced by contract checks); downgrade RW-03 regexes (Git diff replaces them); key read-thrash on file hash instead of per-chat log; make FM-AUTO-01 count edits not all events; close subagent loophole (overwrite and broad-delete, L969/L1003); fix FM-H06 advice (replace rg reference with Select-String).

```contract
{
  "intent": "Clean up hook_v4.py and its PreToolUse matcher: narrow PreToolUse matcher to write/read/shell/MCP tools; remove RW-10; downgrade RW-03 regexes; key read-thrash on file hash instead of per-chat log; make FM-AUTO-01 count edits not all events; close subagent loophole (overwrite and broad-delete); fix FM-H06 advice (replace rg reference with Select-String).",
  "allowed_paths": [
    "IDEAS.md",
    "C:/Users/flowe/.gemini/config/scripts/hook_v4.py",
    "C:/Users/flowe/.gemini/antigravity/hooks.json"
  ],
  "checks": [
    "python -m py_compile C:/Users/flowe/.gemini/config/scripts/hook_v4.py",
    "python .agents/scripts/crucible_gate.py check"
  ]
}
```

## Stage 3: Hardened
- [P-INNER-GRAVITY] (paused — superseded in part by contract gate) Stage and verify the 7-graph WOS harness map and installation pack (`install_pack/`) for `Crucible Domain` before promoting `AGENTS.md`, `IDEAS.md`, and `.agents/acceptance.lock.json` to the workspace root.
- [P-WOS] Exercise the first end-to-end Work Operating System workflow plan with explicit receiving checks (`K-WOS-01..03`) and verified environment access.

## Stage 2: Challenged
- [P-INNER-GRAVITY] Bridge `operator_router.py` `PreInvocation` signals (`mode-forensic`, `idea-crucible`) into deterministic `hook_v4.py` write locks (`PreToolUse`).
- [P-KNOWLEDGE-SIDECAR] Review recorded qualification before wiring `sidecar` as an automated retrieval layer for `Crucible Domain` (`K-ARCH-02`).
- [P-GOVERNANCE] Lock vs. version (approved decision, deferred): keep only the enforcement layer locked (hooks, hook scripts, the contract) and move prose skills in ~/.gemini/config/skills under local Git instead of the hook lock.
- [P-RULE-CONSOLIDATION] Rule-layer consolidation: one owner per job (tiers, contract, 3-strike, honesty); shrink GEMINI.md; make Beneath/Challenging conditional; delete recursive-meta-calibration Module 4 and "inject counter-intuitive truth" clause; split Push Right (intent confirmed at start, execution checkpoints at end); fix stale paths (idea-crucible WSL ledger/old homes, zero-trust "GEMINI.md §4-6"); delete council personas and false chaining-blocked claim; scope "mandatory for ALL" skills (visual-reflex, negative-space, recursive-meta-calibration).
- [P-PERF] Disable data-agent-kit-plugin (dak-telemetry starts node on every tool call) when not doing GCP work.
- [P-DELIVERABLE] First real deliverable: CPL or Personal Work, starting from a GROUND_TRUTH.md intake (requires Levi's input on workflow, audience, and purpose first).

## Stage 1: Raw Sparks
- [P-INNER-GRAVITY] Reconcile `skills.json` (19 unloaded entries in `C:/Kageyoni/.agents/skills`) and `mcp_config.json` (`vertex-ai-search`, `google-cloud-firestore`) against live session loaders.

## Shipped
- [P-CONTRACT-GATE] Built and proved the local Contract Stop Gate (`verify` and `stop`) in `.agents/scripts/crucible_gate.py` with red-capable temp-repo tests in `.agents/scripts/tests/test_crucible_gate.py` (2026-11-22).
- [P-INNER-GRAVITY] Completed initial 4-subagent Frontier Harness audit and upgraded `Project/Inner Gravity/01..04` + `README.md` to the `Work Operating System` 7-graph standard (2026-11-15).
