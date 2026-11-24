# Universal MCP Spoke Template (`K-MCP-01`)

> **Purpose:** 1-page blueprint for spinning up any new deterministic domain spoke (e.g., `Story-Lane`, CPL Marketing/Comms, Live-Ops) as a sibling directory (`../crucible-spokes/<spoke>/`) and plugging it into `Crucible Domain` cleanly without bloating the `<50ms` Hub kernel.

---

## 1. The 3-Tool Universal MCP Contract

Every spoke exposes a zero-dependency stdlib stdio JSON-RPC 2.0 MCP server (`python -m <pkg> mcp`) implementing exactly three tools:

| Tool | Responsibility | Returns |
| :--- | :--- | :--- |
| **`<spoke>_recognize`** | Classify the incoming brief/request into a deterministic domain mode or deliverable form, and report any form-pinned Crucible craft mapping (or `null` to abstain). | `{mode/recognition, pinned_craft}` |
| **`<spoke>_prepare`** | Validate inputs, paths, offline fixtures, byte/rate caps, and project-bound authority floor. Hold at preflight if required authority is missing. | `{status: "prepared" \| "held" \| "blocked", ...}` |
| **`<spoke>_deliver`** | Execute the deterministic domain mechanic (verification packet, revision commit, scan, prior-art brief, or export) and return structured JSON/Markdown. | `{status, receipt/report, delivery}` |

---

## 2. The 3-File Hub Plugin Drop-In

Register the spoke inside `.agents/plugins/<spoke>/` with three lightweight files (using portable relative paths per `CD-W19` — zero hardcoded host drive letters):

1. **`plugin.json`**
   ```json
   {
     "name": "<spoke>",
     "version": "0.1.0",
     "description": "<One-line deterministic spoke capability>",
     "mcp_config": "mcp_config.json",
     "skills": ["skills/<spoke>"]
   }
   ```
2. **`mcp_config.json`**
   ```json
   {
     "mcpServers": {
       "<spoke>": {
         "command": "python",
         "args": ["-m", "<pkg>", "mcp"],
         "cwd": "../crucible-spokes/<spoke>",
         "env": {
           "CRUCIBLE_DOMAIN_ROOT": "../../crucible-domain",
           "CRUCIBLE_ALLOWED_ROOTS": "../../crucible-domain;."
         }
       }
     }
   }
   ```
3. **`skills/<spoke>/SKILL.md`** — Concise (`<= 30` lines) trigger description + 3-tool usage contract.

---

## 3. Non-Negotiable Boundary Invariants (`K-MCP-01`)
- **Single Control Plane:** `Crucible Domain` frames assignments, resolves local ground truth, and judges recipient fit. Spokes never spawn a competing orchestration loop.
- **Selection != Craft:** Spokes recognize forms first and attach at most one form-pinned Crucible procedure (`role: "method"`, `use: "craft"`), abstaining when unmapped.
- **Authority != Craft:** Craft guidance never grants project facts, asset clearance, or cut approval.
- **Capability-Scoped Filesystem Sandbox:** When `CRUCIBLE_ALLOWED_ROOTS` (`os.pathsep`/`;`-delimited directory roots) is set, spokes must resolve all read/write paths and reject any input file or `output_dir` outside those roots before probing or mutating disk.
- **Two-Sided Proof:** Every spoke must pass both its own independent unit + stdio MCP roundtrip tests and one live Hub -> Spoke recomposition call.
