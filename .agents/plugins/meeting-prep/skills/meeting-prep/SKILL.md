---
name: meeting-prep
description: Prepare for any meeting (including unfamiliar domains) using the meeting-prep MCP spoke to produce a <=350-word Live Room Cockpit, Cold-Start Shield, and verified Pre-Read Appendix.
---

# Meeting Prep MCP Spoke (`K-MCP-01`)

1. **`meetingprep_recognize(request, source_paths?, attendees?, unfamiliar_domain?)`** — Classify the meeting regime (`decision`, `pitch`, `alignment`, `review`, `discovery`, `check_in`) and select `quick_prep` vs. `full_prep` (abstains on sending external invites, Asana writes, or binding approvals).
2. **`meetingprep_prepare(...)`** — Verify local sources inside `CRUCIBLE_ALLOWED_ROOTS` (SHA-256 + text), set `source_grounded` vs. `zero_doc_cold_start` epistemic mode, and generate a rehearsal plan for `full_prep`.
3. **`meetingprep_deliver(packet, sheet, traces?, output_dir?, filename?)`** — Enforce the `<= 350`-word Page 1 Live Room Cockpit, verbatim quote-span fact custody, and Causal Objection DAG rehearsal validity, then render Page 1 + Page 2 Markdown (ready for `gdocs`/`gdrive` upload on human approval).
