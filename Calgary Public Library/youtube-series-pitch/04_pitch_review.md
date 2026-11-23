# Stage 4 · Independent Adversarial Critique & Revision Log (`04_pitch_review.md`)

> **Reviewer:** `ig-evidence-review` subagent (`Independent Pitch Evidence Reviewer`, session `dd3cb411-0a7d-4a41-8b96-a87278995780`, read-only sandbox)
> **Runtime Tool-Drift Check (`DRIFT-TOOL`):** Even though `.agents/plugins/inner-gravity/agents/ig-evidence-review.md` declares `tools: [view_file, grep_search, find_by_name]` instead of `read_file`, the host runtime **did** map working `read_file` access (`step_index: 1` of `dd3cb411` transcript). The subagent read every draft file, all 5 controlling sources, `AGENTS.md`, `Media_Work_Routing.md`, `media-production.md`, and `Work_Operating_System_Media_Roles_and_Calgary_Public_Library_Practice.md` verbatim. **No fallback subagent was needed.**
> **Scope Note:** All fixes below were applied directly to [03_five_series_pitch.md](./03_five_series_pitch.md) per execution plan scope; residual upstream sync items in `GROUND_TRUTH.md`, `01_quarry_and_audience.md`, and `02_modulation_board.md` are logged honestly in Section 3 below.

---

## 1. Initial Audit Verdict (Pre-Patch Draft)

| Audit Question | Pre-Patch Verdict | Key Evidence Cited by Reviewer |
| :--- | :--- | :--- |
| **1. Brochure Smell & Modulation Diversity** | **`contradicted`** *(architecture distinct in `02_modulation_board.md`, but specific episodes & fit copy collapsed or used brochure jargon)* | `S2` Ep 3 mirrored `S4` + brochure orientation; `S3` Ep 2 lacked a physical snag/finish; `S2`/`S5` fit copy used internal marketing/stewardship phrases and omitted `2027–2030` + sponsor external-use scope (`MK-02`); `S1` promised `"borrow today"` without hold/availability qualifiers (`CD-01`). |
| **2. Episode-3 Exhaustion & Capacity** | **`contradicted`** *(with `unresolved` inventory/bandwidth holds)* | `S5` Ep 1 packed multi-site logistics + PII QC into a half-day shoot with zero edit budget and mis-cited `CH-03` instead of `MP-10`; `S3` Ep 1 lacked a non-consent fallback; all series under-accounted loaded effort (`CH-02`); `S2` faced single-operator overload (`MP-04`); `S4` lacked a named `CH-05` currency owner; `213`-video substitution check (`MW-03`) was unstated; unverified assets (`21-branch`, `automated sorter`, `Libby`, studio gear, `synthetic demo account`) lacked explicit holds. |
| **3. Lazy Repurposing & Destination Gaps** | **`contradicted`** | Bundled Dial 4 rows (`YT Shorts / IG Reels`, `Web & Newsletter Embed`, `Facebook / LinkedIn / Web`); proposed video embed inside email (`CH-09`); mis-cited `CH-09` for seasonal social pushes; conflated `connect/family-reading-pick` seasonal campaign with evergreen RA; untagged missing URLs; `01_quarry` omitted Seattle in peer table, omitted reproducible `MK-03` query/date fields, and extrapolated TPL/VPL retention + 213-video archive behavior without inspection (`K-ARCH-03`). |
| **4. Custody, Authority & Privacy** | **`contradicted`** *(privacy/mandates **`supported`**; authority & gate labels **`contradicted`**)* | **Zero coworker names, zero internal Asana URLs, and accurate 2027–2030 mandates vs. internal lenses all passed.** However, `03_five_series_pitch.md#L253` falsely labeled the `G01`–`G06` table `[VERIFIED LOCAL]`; `G05` was redefined as Calendar/Destination Check instead of `receiving_handoff`; `MKT-M` was mislabeled Digital Marketing (`MKT-S`); `G01` omitted `MKT-D`/`CNT-D`; `G04` blurred Service Owner `CD-01` fact confirmation with Communications clearance; `#L75` cited `"Collections review"` as a department; and `CPL` abbreviation appeared instead of `"Calgary Public Library"`. |

---

## 2. Revisions Applied Directly to `03_five_series_pitch.md`

Every valid concrete defect raised against `03_five_series_pitch.md` was fixed in place:

1. **Brochure Smell, Engine Collapses & Fit Copy Fixed:**
   - Rewrote **`S2` Ep 3** (*Rescue Mission With a Tech Mentor*) around a live physical-photo digitization/file-rescue completion rather than a `S4`-style UI orientation (`HOLD-04` hardware/capacity gate attached).
   - Rewrote **`S3` Ep 2** (*The Five-Minute Prop Fix*) around an authentic pre-opening Storytime prop snag -> tape fix -> upright stand so it carries a real tactile `Because -> But -> Therefore` arc without patron privacy friction.
   - Rewrote all 5 `MK-02` Strategic Fit sentences to explicitly cite **`2027–2030`**, label themselves `[PROPOSED INTERNAL RATIONALE — Confirm with sponsor before external use]`, and replace institutional jargon with observable patron benefits.
   - Qualified `S1` promise (`"look up to check live availability or place a hold"`), expanded `"CPL"` to `"Calgary Public Library"` throughout, and replaced ungrounded `"$150"` and `"Shorts-to-Long bridge views"` claims.
2. **Capacity, Loaded Effort, Fallbacks & Asset Holds Hardened:**
   - Added mandatory **`213`-video archive overlap check (`MW-03`/`CH-01`)** to the Executive Pre-Read before greenlighting Ep 1.
   - Added realistic **loaded effort ceilings (`CH-02`)** across all 5 series (`S1` 10–13h, `S2` 15–20h, `S3` 11–15h, `S4` 14–18h per 2-ep batch, `S5` 16–22h).
   - Scoped **`S5` Ep 1** strictly to **one single location** (Central sorter room, `[VERIFY AUTOMATED SORTER EXISTENCE & ACCESS — HOLD-04]`), fixed QC citation to **`MP-10`**, and added City/contractor clearance to **`S5` Ep 3**.
   - Added **`S3` Ep 1 non-consent fallback** (hands-only pre-consented staff/adult demo) and scaled rig footprint to a lean 2-camera setup.
   - Added **`S2` concurrent-operator guardrail (`MP-04`)** and pre-pilot gear/capacity inventory check (`HOLD-04`).
   - Named **`Content Manager (CNT-M) / Content Specialist (CNT-S) + Service Owner`** as the explicit 6-month `CH-05` currency owner for **`S4`**, plus explicit `[HOLD-04]` tags on synthetic demo accounts and staff voice/camera consent (`MP-05`).
3. **Unbundled Platform Rows & Destination Discipline:**
   - Split **all 5 Dial 4 tables** into 8 distinct rows (`YouTube Long`, `YouTube Shorts`, `Instagram Reels`, `Instagram Carousel`, `Facebook`, `LinkedIn`, `calgarylibrary.ca Web`, `Newsletter`) with explicit **`EXPLICIT SKIP`** rules and no missing/ambiguous cells.
   - Fixed Newsletter (`CH-09`) to use companion thumbnail + verified links (zero email video embeds), fixed `S4` seasonal social citation from `CH-09` to `CH-06`/`MK-06`, replaced seasonal `family-reading-pick` conflation in `S1` Ep 2 with `[VERIFY EVERGREEN YOUTH RA / CATALOGUE ROUTE — HOLD-04]`, and tagged every unverified URL/route explicitly (`HOLD-03`/`HOLD-04`/`HOLD-05`).
4. **Authority & Custody Corrected:**
   - Relabeled Section 3 header & gate table **`[PROPOSED WORKING MODEL]`** (removing the false `[VERIFIED LOCAL]` claim).
   - Restored **`G05`** to true `receiving_handoff`, separated `MKT-D`/`MKT-M`/`MKT-S`/`CNT-D`/`CNT-M`/`CNT-S` accurately, added `MKT-D`/`CNT-D` alignment at `G01`, separated Service Owner `CD-01` fact read-back from Communications `G04` institutional clearance, and replaced `"Collections review"` with `"Service/Collections Specialist + CNT-M + MKT-S"`.
   - Scoped 213-video audit claims in the Executive Pre-Read strictly to `cpl_handoff_portable.yaml#L117-118`, marking the shift hypothesis explicitly as `[UNVERIFIED — CHECK HOLD-02]`.

---

## 3. Residual Upstream Items Logged (Outside `03_five_series_pitch.md`)

Because execution scope kept revisions targeted to `03_five_series_pitch.md`, note these upstream items in the companion Stage 0–2 working notes before reusing them as standalone inputs:
1. **[01_quarry_and_audience.md](./01_quarry_and_audience.md):** Still contains pre-patch peer table issues (`Seattle` listed in intro without a row; missing `MK-03` reproducible search queries/dates; extrapolated TPL/VPL retention and 213-video opening hypotheses; `MK-04` chain phrased with `return`; and `Educators vs. Stop Motion` misattributed to `institutional-evidence.md` instead of `audience-and-campaigns.md#L27`).
2. **[02_modulation_board.md](./02_modulation_board.md):** Dial 4 cells in Section 2 & Mermaid placement of `G01`–`G06` after Stage 4 are compact summaries superseded by the unbundled tables and early `G01`/`G02` gate sequencing in `03_five_series_pitch.md`.
3. **[GROUND_TRUTH.md](./GROUND_TRUTH.md):** References `SHIFTING_SAND` and `av-craft` (which live in `.agents/scripts/crucible_gate.py` and `~/.gemini/config/skills/av-craft/SKILL.md`, outside the 5 Media Agency sources audited by `ig-evidence-review`) and attributes the Stop Motion mismatch to `institutional-evidence.md` instead of `audience-and-campaigns.md#L27`.
