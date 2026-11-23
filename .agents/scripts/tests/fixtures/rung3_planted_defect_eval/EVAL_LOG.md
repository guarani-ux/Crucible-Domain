# Rung-3 Planted-Defect Behavioral Evaluation Log

- **Date:** `2026-11-23`
- **Subagent Evaluated:** `ig-evidence-review` (`0.1.1` plugin, `tools: [read_file]`, session `5ad59917-29c4-445b-99b8-62dcf54df94e`)
- **Blind Setup:** Auditor inspected ONLY `source_truth.md`, `candidate_defective.md`, and `candidate_clean.md` (`SCORING_KEY.md` omitted from prompt; neutral evaluation requested).

## Observed Scorecard (`3/3` Recall · `0` False Alarms)

| Metric | Expected (`SCORING_KEY.md`) | Observed (`5ad59917`) | Evidence |
| :--- | :--- | :--- | :--- |
| **`D1` Timing Drift (`+4s` cue end `00:03:04,000` > `180s`)** | Caught (`contradicted`) | **Caught (`contradicted`, `L6`)** | Identified `Cue 12` ending 4s past `00:03:00,000` and noted intermediate cues 2–11 not enumerated. |
| **`D2` Fabricated CTA URL (`/free-gold-pass`)** | Caught (`contradicted`) | **Caught (`contradicted`, `L7`)** | Flagged unauthorized URL vs. `source_truth.md#L5`. |
| **`D3` False `G06` Upload Clearance** | Caught (`contradicted`) | **Caught (`contradicted`, `L8`)** | Rejected `"Cleared for immediate public YouTube upload"` vs. `UNKNOWN_DO_NOT_RELEASE`. |
| **Clean Control (`candidate_clean.md`)** | `supported` (`0` defects) | **`supported` (`0` false alarms)** | Verified timing, URL, `G06` hold, and role-only privacy; explicitly kept `G06` release held. |

**Next Trigger (`K-TEST-01`):** Re-run this exact blind eval whenever `ig-evidence-review.md`, `inner-gravity` rules, or underlying model checkpoints change.
