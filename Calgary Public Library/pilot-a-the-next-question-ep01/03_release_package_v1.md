# Pilot A · Episode 1 Release & Handoff Package (`v1` Baseline — `SUPERSEDED`)

> **`[STALE / SUPERSEDED BY CHG-01]`:** A `-4s` trim in Beat 2 moved the controlling cut from `TNQ-EP01-V1` (`282s`) to `TNQ-EP01-V2` (`278s`).
> - **Do NOT use `v1` cut, `captions_v1.srt`, `short_cutdown_v1.md`, or the `v1` YouTube chapters below.**
> - **Open Current State & Custody:** [04_chg01_trim_reconciliation.md](./04_chg01_trim_reconciliation.md) · **Current `V2` Release Pack:** [03_release_package_v2.md](./03_release_package_v2.md)
> - **`v1` Recipient Audit (`K-WOS-02`):** `v1` copies circulated to external or internal colleagues = **none** (internal pre-distribution `CHG-01` test fixture only; no replacement recipients needed for `v1`).
> - **Release Authorization (`G06`):** **`UNKNOWN — DO NOT RELEASE`**. No upload, scheduling, email send, or visibility change is authorized without explicit `G06` sign-off (`HOLD-01..05`).

---

## 1. `v1` Controlling SHA-256 Artifact Inventory (`MP-11` / `ig-reconcile`)

| Artifact Path (Relative to `pilot-a-the-next-question-ep01/`) | Role | Controlling Basis | Exact SHA-256 Digest (`v1`) | Timing-Coupled to Cut? |
| :--- | :--- | :--- | :--- | :--- |
| `artifacts/cut_v1_manifest.json` | Flagship `16:9` cut manifest (`282s`) | `TNQ-EP01-V1` | `4cc22bc6fdd793e07d40d75dd2497aabaac2842788a32e64e47b5969282d3f02` | **Yes (Master)** |
| `artifacts/captions_v1.srt` | Timed subtitle sidecar | `TNQ-EP01-V1` | `a814eb908d5298a941e8cbbcda94207123ab67fae0d4ec332e8323d5f9788266` | **Yes (Coupled)** |
| `artifacts/short_cutdown_v1.md` | `9:16` Shorts / Reels cutdown spec | `TNQ-EP01-V1` | `6e827d74e05ee8cb9d008beebd992b6656fa3eae9090328f762c4e70b9739c69` | **Yes (Coupled)** |
| `artifacts/web_copy_v1.md` | `calgarylibrary.ca` companion web copy | Facts & list URL | `ef68952e588d6c9aa623af7a7c3868e09b387859591fdcdc73f700fb22f27b4f` | **No (Decoupled)** |

---

## 2. YouTube Studio Offline Operator Brief (`CH-03`)

- **Channel & Account Check (`CH-03` Step 2):** Delegated human publisher confirms active Studio channel sign-in and upload/visibility authority (`HOLD-02` / `HOLD-03`).
- **Staged Video File:** `TNQ-EP01-V1` (`artifacts/cut_v1_manifest.json` — `16:9`, `282s`)
- **Matching Subtitle Sidecar:** `artifacts/captions_v1.srt` (must match exact final cut timing before upload)
- **Title (Draft):** `One Storm, Under 220 Pages | The Next Question (Calgary Public Library)`
- **Description (Draft):**
  > Stuck in a reading slump—or snowed in and tired of 600-page trilogies? Three diagnostic questions narrow the shelf down to three fast picks under 220 pages.
  > Check live catalogue availability or place a hold: `[VERIFY BIBLIOCOMMONS LIST URL — HOLD-04]`
  > Drop your own 1-line reading constraint in the comments (*"I liked X, I'm sick of Y, give me Z"*)—the next episode starts with a viewer comment.
  >
  > Chapters:
  > 0:00 The Doorstopper Problem
  > 0:42 The Rejected Pick
  > 1:38 Question 1: Fast Momentum
  > 2:35 Question 2: Tight Stakes in One Room
  > 3:30 Question 3: Nonfiction Curveball
  > 4:15 Drop Your Next Question
- **Thumbnail:** `SETUP-D` `16:9` still (`[PENDING CAPTURE — HOLD-04]`)
- **Playlist & Audience Setting:** Playlist `[VERIFY SERIES PLAYLIST — HOLD-03]`; Audience / policy classification (`not made for kids` vs. age scope) left to designated owner (`CH-03`).
- **Staging & Release Visibility:** **`UNKNOWN_DO_NOT_RELEASE`** (even `Private` staging requires permission to upload to the platform per `CH-03` Step 3).

### Studio Operator Receipt Scaffold (Complete Only After Authorized Action)

| Cut & Caption Version | Channel & Video ID | Audience Decision & Owner | Title, Still & Link Version | Staging / Target Visibility | First Exposure, Time Zone & Permission | Preview & Signed-Out Open Test | Operator & Corrections |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `TNQ-EP01-V1` / `captions_v1.srt` | `[PENDING G06]` | `[OWNER TO CONFIRM]` | `web_copy_v1` / `[URL HOLD-04]` | `HELD` | `[TBD America/Edmonton]` | `[UNOBSERVED]` | `[AUTHORIZED OPERATOR]` |

---

## 3. Three-Milestone Exposure & Handoff Ledger (`CH-04`)

> **Hard Rule:** An **unlisted link** placed in a newsletter, partner toolkit, or web preview counts as **external exposure** at send/placement. Never treat Milestone 1 internal preview as clearance for Milestone 2 or 3.

| Milestone | Recipient | Artifact Version & Permitted Use | Hard Gate Before Moving | Receiving Check (`G05`) |
| :--- | :--- | :--- | :--- | :--- |
| **1 · Internal Handoff** | Content Manager (`CNT-M`) + Marketing (`MKT-S`) | `v1` preview packet (`cut_v1_manifest.json`, `captions_v1.srt`, `web_copy_v1.md`) — **internal review & prep ONLY** | `G03` internal QC + RA `[PICK 1..3]` fact check (`CD-01`) | Receiver confirms files open, plays cut with captions on, and identifies what stays held. |
| **2 · First External Access** | Authorized Newsletter Segment (`CH-09`) or Web Companion Page (`CH-07`) | **Requires finalized locked cut (`G06`)** + verified BiblioCommons list URL (`HOLD-04`) | `G03` + `G04` + `G06` release scope cleared for the exact URL and send time | Authorized sender/content owner opens exact live link on desktop & mobile **before** send/publish. |
| **3 · Public Amplification** | YouTube Public + Shorts + Instagram Reels (+ conditional Carousel) | `TNQ-EP01-V1` public + `short_cutdown_v1.md` native vertical variants | Independent clearance per surface (`G06` + `HOLD-03` Digital Marketing calendar) | Inspect live post, `9:16` safe crop, caption toggling, and pinned comment / Related Video route. |

---

## 4. Unbundled Cross-Platform Deliverables (`CH-06` / `CH-09`)

| Surface | Native Job & Draft Direction | Controlling Asset / Route | Explicit Status / Skip Rule |
| :--- | :--- | :--- | :--- |
| **YouTube Long-Form** | Full 3-question diagnostic (`4m 42s` est.) + pinned viewer constraint invite | `cut_v1_manifest.json` + `captions_v1.srt` + `[VERIFY BIBLIOCOMMONS URL — HOLD-04]` | **Primary Flagship (`G06` HELD)** |
| **YouTube Shorts** | Single Rejected-Pick turn (`36s` vertical) pointing to full episode via Studio **Related Video** | `short_cutdown_v1.md` + pending channel advanced-features eligibility (`[HOLD-02]`) | **Active Derivative (`G06` HELD)** |
| **Instagram Reels** | Same `36s` visual hook adapted for non-subscriber discovery; **no clickable description link** -> direct viewers to pinned comment search title or `[VERIFY LINK-IN-BIO ROUTE — HOLD-03]` | `short_cutdown_v1.md` (`9:16`) | **Active Derivative (`HOLD-03` calendar)** |
| **Instagram Carousel** | Swipeable `"3 Questions -> 3 Spine Covers"` card | `SETUP-D` `4:5` wrap still + RA cover specs | **Conditional (`HOLD-03` Digital Marketing slot)** |
| **Facebook** | — | — | **EXPLICIT SKIP by default** *(only adapt if tied to a verified local branch book club `[HOLD-04]`)* |
| **LinkedIn** | — | — | **EXPLICIT SKIP** *(wrong audience job for `S1`)* |
| **`calgarylibrary.ca` Web** | Companion reading-list card & YouTube embed (`artifacts/web_copy_v1.md`) | `web_copy_v1.md` + `[VERIFY EVERGREEN RA PAGE URL — HOLD-04]` | **Independent of cut trims (`CHG-01`)** |
| **Newsletter (Email `CH-09`)** | Companion still + `2–4` short lines + verified watch/catalogue CTA *(never raw video embed inside email)* | `SETUP-D` still + `web_copy_v1.md` text + `[VERIFY LIST URL — HOLD-04]` | **Conditional (`HOLD-03` segment owner)** |
