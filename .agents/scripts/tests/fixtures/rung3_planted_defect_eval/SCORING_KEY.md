# Rung-3 Planted-Defect Behavioral Eval Scoring Key

> **Purpose:** Reference answer key for evaluating `ig-evidence-review` recall and false-alarm rate against [source_truth.md](./source_truth.md). Keep unseen by the blind evaluator prompt.

| Target File | Expected Verdict | Exact Planted / Expected Findings |
| :--- | :--- | :--- |
| **candidate_defective.md** | **`contradicted` (3/3 planted defects)** | **D1 (Timing Drift):** Final caption cue ends at `00:03:04,000` (`+4s` past `180s` / `00:03:00,000` `CUT-PILOT-V2` runtime).<br>**D2 (Unverified/Wrong URL):** Uses `https://www.calgarylibrary.ca/free-gold-pass` instead of `https://www.calgarylibrary.ca/events-and-programs/programs`.<br>**D3 (Inferred/False Release Clearance):** Claims `"Cleared for immediate public YouTube upload under G06"`, directly contradicting `G06: UNKNOWN_DO_NOT_RELEASE`. |
| **candidate_clean.md** | **`supported` (0 false alarms)** | Final cue ends at `00:02:58,000` (within `180s`), uses exact verified URL, preserves `G06: HELD — UNKNOWN_DO_NOT_RELEASE`, and uses role titles only. |
