---
name: crucible-observatory
description: Invoke the Crucible Observatory MCP spoke for offline prior-art forging (forge), GitHub repository diff/scan (melt-diff, melt-scan), outcome ledger risk checks, and capability map exports.
---

# Crucible Observatory MCP Spoke

Use this 3-tool MCP spoke (`observatory_recognize`, `observatory_prepare`, `observatory_deliver`) whenever you need offline research, prior-art synthesis, repo-sieve analysis, or outcome-ledger risk scoring without bloating the fast `<50ms` Crucible Domain kernel.

## Universal 3-Tool Workflow
1. **`observatory_recognize`**: Classify the request into `forge`, `melt-diff`, `melt-scan`, `ledger`, `export-map`, or `observatory`.
2. **`observatory_prepare`**: Validate `crucible_root`, offline `--from-json` fixtures (capped at 2 MiB), and required arguments.
3. **`observatory_deliver`**: Execute the operation and return structured JSON.
