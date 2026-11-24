---
name: writers-room
description: >-
  Invoke The Writer's Room MCP spoke from Crucible Domain to recognize document forms,
  prepare bound commissions with form-pinned non-evidentiary craft, run mechanical
  anchor/shape checks, and commit verified revisions with independent subagent review.
---

# Writer's Room MCP Spoke (`Crucible Orchestrator-Producer Hub -> The Writer's Room`)

> **Role Boundary (`K-MCP-01`):** `Crucible Domain` is the **Orchestrator-Producer Hub (single control plane)** owning assignment framing, local `GROUND_TRUTH.md` authority, and producer/receiving judgment. `The Writer's Room` acts strictly as a deterministic domain spoke—never as a second competing orchestration loop.

## Coupling Rules (`K-MCP-01` & `READOUT.md` Invariants)
1. **Selection != Craft:** Never wire Crucible lexical `route` directly to generation. Call `writersroom_recognize` first; Writer's Room selects the form and pulls at most one pinned procedure (`MW-01`, `MW-02`, `MW-04`), abstaining (`null`) on unmapped forms like `call_sheet`.
2. **Authority != Craft:** Crucible craft excerpts enter strictly as `role: "method"`, `use: "craft"`. They can never support `fact`, `asset`, or `permission` claims. Fresh or resumed timed cuts require project-bound approval (`direction` with `project_id`) or hold at preflight.
3. **Stage-Matched Verification (No Forensic Art-Direction Churn):** After `writersroom_deliver(action="review_packet")`, run an **independent read-only review** (`reviewer_id != author_id`). Enforce strict claim-by-claim evidentiary checks on locked downstream execution (`timed_av` cuts on existing material, public factual claims). On exploratory upstream forms (`treatment`, `production_brief`), check real source/authority limits and recipient usability—never reject creative art-direction prose for unlogged sensory details (such as sign fonts or lighting mood) or force multi-round CYA disclaimer churn.

## 4-Step Producer Loop
1. **Recognize:** Call `writersroom_recognize` with the raw brief, domain `GROUND_TRUTH.md` sources, and optional `client` (`calgary-public-library`).
2. **Prepare:** Call `writersroom_prepare` (`work_dir`, structured `commission`, `guided=True`). If `status == "held"`, stop and surface the returned `holds` without calling a writer.
3. **Author + Check + Independent Review:** Draft `result` JSON, run `writersroom_deliver(action="review_packet")` to catch mechanical/anchor defects, then pass `verification_packet` to `ig-evidence-review`.
4. **Submit:** Call `writersroom_deliver(action="submit")` with `result`, `verification_reply`, and distinct `reviewer_id` / `author_id` to commit and export `.md` / `.docx`.
