---
name: story-lane
description: Invoke the Story-Lane MCP spoke for deterministic saved-transcript clip selection, timestamp boundary validation (0 <= start < end), and traceable clip manifest extraction (K-STORY-01, K-MCP-01). Holds on fresh speech transcription and editorial cut approval.
---

# Story-Lane MCP Spoke (`K-STORY-01`, `K-MCP-01`)

1. **`storylane_recognize(request)`** — Classify the task into `saved_transcript_select`, `clip_boundary_validate`, `traceable_extract`, or `hold_out_of_scope` (abstains on fresh speech transcription and editorial cut approval).
2. **`storylane_prepare(mode, transcript_path, clips?, editorial_authority?)`** — Verify retained transcript exists, validate timestamp intervals, and enforce K-STORY-01/K-MCP-01 holds.
3. **`storylane_deliver(mode, transcript_path, query_terms?, clips?, output_dir?)`** — Execute deterministic clip selection/boundary math and optionally emit an isolated `storylane_clip_manifest.json`.
