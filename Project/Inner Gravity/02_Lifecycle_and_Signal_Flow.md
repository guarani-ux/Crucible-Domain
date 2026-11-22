# 02 — Reference Process Model & Execution Trace (`IG-PROC` & `IG-TRACE`)

**WOS Graph Types:**
- `Reference process model` (*How do we do this kind of work? Who acts, which skills and tools they use, what they produce, and who receives it.*)
- `Execution and provenance trace` (*What actually happened? The actor, operation, exact input and output versions, evidence, and receiving decision.*)

**Related Records:** `P-INNER-GRAVITY`, `P-WOS`, `K-WOS-03`, `K-ARCH-01` (cognitive-os failed prerequisite on resume), `K-ARCH-02`, `K-ARCH-03` (Kageyoni operation-bound receipt)

---

## 1. Reference Process Model: Turn & Hook Lifecycle (`IG-PROC-01`)

```mermaid
flowchart TD
    operator["Operator · Levi"] -->|"Submits prompt in Crucible Domain to"| host["Antigravity Host Runtime"]
    host -->|"Pipes workspacePaths & lastUserInput to"| router["PreInvocation Hook · operator_router.py"]
    router -->|"Matches 6 regex rules & returns injectSteps to"| host
    host -->|"Delivers prompt + GEMINI.md + Skill/MCP Index to"| coordinator["Coordinator Agent · Gemini 4"]

    coordinator -->|"Selects native tool, plugin CLI, or subagent via"| pre["PreToolUse Gate · hook_v4.py pre"]
    pre -->|"Evaluates RW-01..RW-11, protected paths, shell risk"| decision{"Gate Decision"}
    decision -->|"deny or force_ask"| blocked["Blocked / Operator Confirmation Required"]
    decision -->|"allow"| exec["Tool Execution in Workspace or Sandbox"]

    exec -->|"Returns stdout / file receipt to"| post["PostToolUse Logger · hook_v4.py post"]
    post -->|"Appends audited event to"| elog["Brain · reliability-events.jsonl"]

    coordinator -->|"Emits final response (NO_TOOL_CALL) to"| stop["Stop Gate · hook_v4.py stop"]
    stop -->|"Verifies FM-BASE-01, FM-H13, RW-10 & acceptance.lock.json"| qual{"Qualification Passed?"}
    qual -->|"No (up to 3 attempts)"| retry["decision: continue · Force agent to fix/verify"]
    qual -->|"Yes (allow)"| receiver["Operator · Receives verified output & file links"]
```

---

## 2. Signal Routing & Enforcement Matrix (`IG-PROC-02`)

Solid edges (`-->`) show **hard mechanical gates** enforced by `hook_v4.py`. Dashed edges (`-.->`) show **advisory prompt nudges** injected by `operator_router.py` (`K-GRAPH-01`).

```mermaid
flowchart LR
    subgraph SOFT["Advisory Signal Nudges · operator_router.py (PreInvocation)"]
        SR1["wait_what ('wait what', 'talk normal')"]
        SR2["ego_anchor ('hogyoku', 'power level', '10x')"]
        SR3["av_craft ('av script', 'paper edit', 'story spine')"]
        SR4["cl_craft ('cover letter', 'jd decode')"]
        SR5["forensic ('forensic audit', 'dead code')"]
        SR6["acceleration ('what if we', 'new system', 'new folder')"]
    end

    subgraph HARD["Mechanical Enforcement Gates · hook_v4.py (PreToolUse & Stop)"]
        HG1["RW-04 / RW-06 · Protected Config & Brain Files"]
        HG2["RW-03 · PowerShell / Shell File-Write Bypass Block"]
        HG3["RW-01 / RW-02 / RW-08 / RW-11 · Python AST Integrity"]
        HG4["FM-BASE-01 & FM-H13 · Test Hash & Root Hygiene Baselines"]
        HG5["RW-10 & qualification() · Post-Edit Verification & acceptance.lock.json"]
    end

    SR1 -.->|"Advises plain-English 3-sentence re-pitch"| TURN["Agent Turn Execution"]
    SR2 -.->|"Advises recursive-meta-calibration"| TURN
    SR3 -.->|"Advises av-flow Explore -> Exploit"| TURN
    SR4 -.->|"Advises cl-flow JD X-Ray"| TURN
    SR5 -.->|"Advises read-only inspection first"| TURN
    SR6 -.->|"Advises idea-crucible compression"| TURN

    TURN -->|"Checked before every tool call by"| HG1
    TURN -->|"Checked before every shell call by"| HG2
    TURN -->|"Checked before every Python write by"| HG3
    TURN -->|"Checked before turn completion by"| HG4
    TURN -->|"Checked before turn completion by"| HG5
```

---

## 3. Observed Execution & Provenance Trace (`IG-TRACE-01`)

This graph records the **actual operations executed** during session `79d6267e-43c7-484f-9c9d-4e6762060706` on November 15, 2026 (`WOS Graph Type 5` + `K-WOS-03` + `K-ARCH-03`).

```mermaid
flowchart TD
    t1["T1 · SessionStart Hook (operator_router.py)"] -->|"Observed: No local IDEAS.md in Crucible Domain"| e1["Injected WSL fallback text pointer"]
    e1 -->|"Followed by"| t2["T2 · Workspace & Drive Inspection (pwsh + gdrive CLI)"]
    t2 -->|"Authenticated OAuth & listed 1jpG-7DjOa2xtiYPbBhL07qmCRSVrK1fU"| e2["Observed: 5 Drive folders; local files synced in during session"]
    e2 -->|"Followed by"| t3["T3 · Config & Hook Custody Read (read_file)"]
    t3 -->|"Inspected hooks.json, hook_v4.py, operator_router.py, mcp_config.json, skills.json"| e3["Observed: 1,374-line hook_v4.py, relative path in hooks.json, 12/31 Kageyoni skills loaded"]
    e3 -->|"Synthesized into"| t4["T4 · Initial Inner Gravity Draft (01..04 + README)"]
    t4 -->|"Audited in parallel by"| t5["T5 · 4 Research Subagents (4cff0cec, ebd3a381, 6dee33d7, ee2d01f3)"]
    t5 -->|"Returned 4 Frontier Benchmark briefs to"| t6["T6 · WOS & Archaeology Alignment Read (P-WOS, K-WOS-01..03, A01..A10)"]
    t6 -->|"Produced upgraded 7-graph suite & staged install kit in"| out["Output · Project/Inner Gravity/ + install_pack/"]
```

---

## 4. Provenance & Failure-Mode Notes (What the Graph Cannot Show)

1. **Why `RW-10` Needs `.agents/acceptance.lock.json` (`K-ARCH-01` & `K-ARCH-03`):**
   - In `hook_v4.py` (lines 1294–1351), `stop(payload)` calls `qualification(payload)`. When `.agents/acceptance.lock.json` is absent (`contract is None`), `hook_v4.py` only checks session-edited Python syntax, SQLite DB integrity, baseline test hashes (`FM-BASE-01`), untracked root scripts (`FM-H13`), and that at least one `run_command` occurred after a code edit (`RW-10`).
   - Installing `install_pack/acceptance.lock.json` to `Crucible Domain/.agents/acceptance.lock.json` binds `stop(payload)` to verify that every core register and `Inner Gravity` artifact exists and is non-empty (`os.path.getsize(full) > 0`).
2. **Failed-Prerequisite Resume Protection (`K-ARCH-01`):**
   - `K-ARCH-01` (from `A09 cognitive-os`) warns that a saved checkpoint can resume past a failed prerequisite. In `hook_v4.py`, `stop(payload)` caps forced continuations at `attempt >= 3` (`executionNum`). If an agent hits 3 consecutive failed tool calls (`recent_tool_errors`) or 3 failed stop checks, the host allows termination so the operator sees the failure rather than looping infinitely—meaning the operator or next session must check `reliability-events.jsonl` before assuming the prior turn succeeded.

---

## 5. Antigravity Host Glossary & Hook I/O Contract (For External Agents)

```mermaid
flowchart LR
    HOST["Antigravity Host"] -->|"1. Reads & injects as <RULE[user_global]>"| GMD["GEMINI.md + AGENTS.md"]
    HOST -->|"2. Pipes JSON on stdin to"| HOOK["Python Hook (operator_router.py / hook_v4.py)"]
    HOOK -->|"3. Returns JSON on stdout to"| HOST
    HOST -->|"4. Lazy-loads on demand"| LAZY["SKILL.md & mcp/<server>/<tool>.json"]
```

- **How `GEMINI.md` & `AGENTS.md` influence the model:** The Antigravity host automatically injects global `GEMINI.md` and `AGENTS.md` into every prompt as `<RULE[user_global]>` system instructions.
- **How `operator_router.py` influences the model (`SessionStart` / `PreInvocation`):** Receives `{"workspacePaths": [...], "lastUserInput": "..."}` on `stdin` and prints `{"injectSteps": [{"systemMessage": {"systemMessage": "..."}}]}` on `stdout`, which the host appends as a `<SYSTEM_MESSAGE>` before the model runs.
- **How `hook_v4.py` gates the model (`PreToolUse` / `PostToolUse` / `Stop`):** Receives tool call / turn-end JSON on `stdin` and prints `{"decision": "allow" | "deny" | "force_ask", "reason": "..."}` (on `PreToolUse`) or `{"decision": "allow" | "continue", "reason": "..."}` (on `Stop`) on `stdout`.

