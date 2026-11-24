---
name: writers-room
description: >-
  Invoke The Writer's Room MCP spoke from Crucible Domain to recognize document forms,
  prepare bound commissions with form-pinned non-evidentiary craft, run mechanical
  anchor/shape checks, and commit verified revisions with independent subagent review.
---

# Writer's Room MCP Coupling (`Crucible Domain -> The Writer's Room`)

## Coupling Rules (`READOUT.md` Invariants)
1. **Selection != Craft:** Never wire Crucible lexical `route` directly to generation. Call `writersroom_recognize` first; Writer's Room selects the form and pulls at most one pinned procedure (`MW-01`, `MW-02`, `MW-04`), abstaining (`null`) on unmapped forms like `call_sheet`.
2. **Authority != Craft:** Crucible craft excerpts enter strictly as `role: "method"`, `use: "craft"`. They can never support `fact`, `asset`, or `permission` claims. Fresh or resumed timed cuts require project-bound approval (`direction` with `project_id`) or hold at preflight.
3. **Placement != Lookup:** Locating a craft step does not prove it landed in the right passage. After `writersroom_deliver(action="review_packet")`, send the returned `verification_packet` to an **independent read-only `ig-evidence-review` subagent** (distinct `reviewer_id != author_id`) before calling `writersroom_deliver(action="submit")`.

## 4-Step Producer Loop
1. **Recognize:** Call `writersroom_recognize` with the raw brief, domain `GROUND_TRUTH.md` sources, and optional `client` (`calgary-public-library`).
2. **Prepare:** Call `writersroom_prepare` (`work_dir`, structured `commission`, `guided=True`). If `status == "held"`, stop and surface the returned `holds` without calling a writer.
3. **Author + Check + Independent Review:** Draft `result` JSON, run `writersroom_deliver(action="review_packet")` to catch mechanical/anchor defects, then pass `verification_packet` to `ig-evidence-review`.
4. **Submit:** Call `writersroom_deliver(action="submit")` with `result`, `verification_reply`, and distinct `reviewer_id` / `author_id` to commit and export `.md` / `.docx`.
