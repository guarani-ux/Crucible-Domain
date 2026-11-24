# Calgary Public Library — Media Production Workflow Model (`WORKFLOW_MODEL.md`)

> **Custody & Authority Status:** Anonymized structural workflow model distilled from an 18-month read-only (`GET`-only) Asana structural analysis (`131` tasks across `19` projects, `2025-06-02` to `2026-11-23`; `65` completed, `66` active/open). Zero coworker names, zero internal Asana URLs, and zero raw restricted task text are stored here (`Asana: read-only`).
> **Companion Ground Truth:** [GROUND_TRUTH.md](./GROUND_TRUTH.md) · **Generic Craft & Systems Benchmark:** [../Personal Work/CRAFT_AND_SYSTEMS_BENCHMARK.md](../Personal%20Work/CRAFT_AND_SYSTEMS_BENCHMARK.md)

---

## 1. Operational Reality (What the 18-Month Snapshot Shows)

- **Execution Posture:** Media Production (`[ME]`) is the direct assignee on **`100 / 131` (`76%`)** of observed tasks, collaborating across `14` recurring institutional partners (Marketing, Communications, Digital/Content, Design, Events, and Subject Matter Experts).
- **Four-Stage Backbone (Campaign Projects):** Flagship Asana boards share a consistent 4-stage `Stage` custom field: **`Refine -> Development -> Review -> Approval`**, organized across **`Marketing`**, **`Communication`**, and **`Production`** sections.
- **Not One Monolithic Pipeline:** Real work runs on **four distinct workflow speeds**, ranging from `15–20 minute` audio updates to `13-subtask` multi-review flagship YouTube productions. Applying heavyweight 10-step film bureaucracy to fast-turnaround or templated event work creates unnecessary friction.

---

## 2. The Four Real Workflows (End-to-End vs. Scaled-Down)

### Track A — Standardized Live Event & Replay (`OSE` Pattern)
*Observed across 9 Online School Event projects (`Produce Show` + `Edit Video`).*
- **Scale:** Scaled-down, repeatable 2-card template (zero concepting, zero script, zero Leadership review).
- **Card 1 (`Produce Show`, 3–4 subtasks):**
  1. Pre-show team chat/meeting (if needed)
  2. Print show flow and prep brief on iPad/Padlet
  3. Produce and set up live event
  4. Process invoice (if needed)
- **Card 2 (`Edit Video`, 3 subtasks):**
  1. Edit event recording and send YouTube deliverable to Digital/Channel owner
  2. Video content review
  3. Upload recording to shared storage (`EVO`)
- **Primary Failure Risk:** Unconfirmed completion on handoff subtasks (e.g., `Upload recording to EVO` or `Video content review` left unchecked while the main card sits open).

### Track B — Full End-to-End Flagship Campaign Video
*Observed across flagship YouTube & annual projects (`ELC`, `Day in the Life`, `Year in Review`, `LitCon`).*
- **Scale:** Full 4-phase lifecycle (`8–13` subtasks per delivery card; highest comment/rework density, up to `20` comments on a single delivery card).
- **Phase 1 — Pre-Production (`Refine -> Development`):**
  1. Pre-production kickoff / SME brainstorm
  2. Concept drafted -> Production review -> Marketing review -> Concept edits -> Concept approval
  3. Develop A/V script -> Internal/SME reviews -> Edits -> Final script approval
  4. Logistics (`Flow first then Call Sheet` — book location, book talent/host, assemble B-roll)
- **Phase 2 — First Cut & Rework Loop (`Development -> Review`):**
  5. Complete first cut -> Production review -> First round edits
  6. *Escalation branch (when cut/coverage misses):* `Create re-edit plan document -> Review re-edit plan -> Capture additional footage -> Complete second round edits`
- **Phase 3 — Timelock, Captions & Graphics (`Review -> Approval`):**
  7. Leadership review complete
  8. **Timelock gate (`CHG-01`):** `Send timelocked video for captions` -> Produce subtitle/graphic doc -> Complete captions & graphic text -> Final video and caption edit
  9. Complete final approval
- **Phase 4 — Channel Rollout:**
  10. YouTube thumbnail + description + publish + share + backup files (+ optional social cutdowns).

### Track C — Fast-Turnaround Micro-Edit / Audio Update
*Observed in PA announcement updates, support-call audio changes, and photo requests (`4–6` subtasks).*
- **Scale:** Compressed single-pass sprint (target `15–20` minutes of hands-on production once script is cleared).
- **Sequence:** `Receive/Review script -> Record audio (or edit clip) -> Production/SME review -> Final edit -> Final review`.
- **Primary Failure Risk:** Scope creep or late script tweaks arriving after recording is already booked.

### Track D — Intake Triage, Audits & Advisory Gatekeeping
*Observed in `Project Intake`, `Media Content Framework`, and `Production Specialist review and recommendations`.*
- **Intake Triage:** Classifies incoming asks by `Department`, `Priority`, `Request Type`, `Location`, and `Level of Support` (`Full Support` vs. `Service Request - Marketing` vs. `Service Request - Communications`).
- **Governance & Pushback:** Evaluates whether existing decks/recordings should become standalone YouTube videos (rejecting weak repurposing pitches with specific evidence of missing practical advice or unverified claims), and enforces content-audit metadata (e.g., license expiry, removal/replacement timelines).

---

## 3. Mapping Real Asana Gates to `G01`–`G06` & `CHG-01`

| Proposed Gate (`GROUND_TRUTH.md`) | Observed Asana Equivalent | Where Bottlenecks Actually Happen |
| --- | --- | --- |
| **`G01` Scope** | `Project Intake` (`Level of Support`, `Request Type`) + `Refine` stage | Unclear repurpose asks (`"not sure where to start"`) or pitches lacking patron takeaway. |
| **`G02` Ready for Production** | `Concept Approval` + `Final script approval` + `Flow first then Call Sheet` | Missing graphic/animation handoffs (thumbnails vs. flat graphics vs. hex codes split across owners). |
| **`G03` Production Review (`MP-10`)** | `Production review` -> `Complete first round of edits` | Rough cuts hitting review without verified audio/graphics passes or missing B-roll triggering a full **Re-Edit Plan + Reshoot** loop. |
| **`G04` Stakeholder Review** | `SME Review` + `Marketing Review Concept` + `Leadership review complete` | Feedback arriving out of sequence or conflicting across Marketing, Comms, and SMEs. |
| **`G05` Receiving Handoff (`CH-04`)** | `Send timelocked video for captions` / `Send YT to [Channel Owner]` / `Upload recording to EVO` | **Literally `CHG-01`:** captions/graphics depend on timelock; unconfirmed receipt leaves EVO/YouTube/website rollout status unclear. |
| **`G06` Release Authorization** | `Complete final approval` / `YIR Final Version Approval and Sign off` | Unclear whether website embed/rollout is included alongside YouTube publish. |
