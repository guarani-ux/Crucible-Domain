# Pilot A · Episode 1 Release & Handoff Package (`V2` Current Draft — `CH-03` / `CH-04` / `CH-06` / `CH-09`)

> **Controlling Custody & `CHG-01` Ledger:** [04_chg01_trim_reconciliation.md](./04_chg01_trim_reconciliation.md) · **Supersedes:** [03_release_package_v1.md](./03_release_package_v1.md) (`STALE`)
> **Simulation Status:** Pre-capture `V2` operator packet reflecting `-4s` Beat 2 trim (`278s`). Physical video capture and real `[PICK 1..3]` book confirmations remain held on **`HOLD-04`**.
> **Release Authorization (`G06`):** **`UNKNOWN — DO NOT RELEASE`**. No upload, unlisted send, email send, or visibility change is authorized without explicit `G06` sign-off (`HOLD-01..05`).

---

## 1. Controlling `V2` SHA-256 Artifact Inventory (`MP-11` / `check_artifact.py` Verified)

| Artifact Path (Relative to `pilot-a-the-next-question-ep01/`) | Role | Controlling Basis | Exact SHA-256 Digest (`V2` Set) | Gate State |
| :--- | :--- | :--- | :--- | :--- |
| `artifacts/cut_v2_manifest.json` | Flagship `16:9` cut manifest (`278s`) | `TNQ-EP01-V2` | `6fee4e4c02b39852528ec9643753783e644b03b9aba33dfe17641523e3ca59fd` | `PENDING_V2_RECHECK` (`G03`, `G06` HELD) |
| `artifacts/captions_v2.srt` | Script-matched `17`-cue subtitle sidecar | `TNQ-EP01-V2` | `57a027af5c212899eca9f039b344b161f31123d66f49f5eaf13c69ca0047dcd0` | `PENDING_V2_RECHECK` (`G03`, `G06` HELD) |
| `artifacts/short_cutdown_v2.md` | `9:16` Shorts / Reels cutdown spec (`44s`) | `TNQ-EP01-V2` | `b4f08ff4af6fe485174013496c91f52dd52db76c943c364b0101d06753c84f8b` | `PENDING_V2_RECHECK` (`G03`, `G06` HELD) |
| `artifacts/web_copy_v1.md` | `calgarylibrary.ca` companion web copy | Facts & list URL | `ef68952e588d6c9aa623af7a7c3868e09b387859591fdcdc73f700fb22f27b4f` | `VALID` (Unaffected by `-4s` trim; `HOLD-04` pending) |

---

## 2. YouTube Studio Offline Operator Brief (`CH-03` — `V2` Timing)

- **Channel & Account Check (`CH-03` Step 2):** Delegated human publisher (`[ASSIGN NAMED OPERATOR]`) confirms active Studio channel sign-in and upload/visibility authority (`HOLD-02` / `HOLD-03`).
- **Staged Video File:** `TNQ-EP01-V2` (`artifacts/cut_v2_manifest.json` — `16:9`, `278s`, `[PENDING CAPTURE — HOLD-04]`)
- **Matching Subtitle Sidecar:** `artifacts/captions_v2.srt` (`57a027af...`)
- **Title (Draft):** `One Storm, Under 220 Pages | The Next Question (Calgary Public Library)`
- **Description (Draft):**
  > Stuck in a reading slump—or snowed in and tired of 600-page trilogies? Three diagnostic questions narrow the shelf down to three fast picks under 220 pages.
  > Check live catalogue availability or place a hold: `[VERIFY BIBLIOCOMMONS LIST URL — HOLD-04]`
  > Drop your own 1-line reading constraint in the comments (*"I liked X, I'm sick of Y, give me Z"*)—the next episode starts with a viewer comment.
  >
  > Chapters (`V2` adjusted `-4s` from Beat 3 onward):
  > 0:00 The Doorstopper Problem
  > 0:42 The Rejected Pick
  > 1:34 Question 1: Fast Momentum
  > 2:31 Question 2: Tight Stakes in One Room
  > 3:26 Question 3: Nonfiction Curveball
  > 4:11 Drop Your Next Question
- **Thumbnail:** `SETUP-D` `16:9` still (`[PENDING CAPTURE — HOLD-04]`)
- **Playlist & Audience Setting:** Playlist `[VERIFY SERIES PLAYLIST — HOLD-03]`; Audience / policy classification (`not made for kids` vs. age scope) left to designated owner (`CH-03`).
- **Staging & Release Visibility:** **`UNKNOWN_DO_NOT_RELEASE`** (even `Private` staging requires permission to upload to the platform per `CH-03` Step 3).

### Studio Operator Receipt Scaffold (Complete Only After Authorized Action)

| Cut & Caption Version | Channel & Video ID | Audience Decision & Owner | Title, Still & Link Version | Staging / Target Visibility | First Exposure, Time Zone & Permission | Preview & Signed-Out Open Test | Operator & Corrections |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `TNQ-EP01-V2` / `captions_v2.srt` (`57a027af...`) | `[PENDING G06]` | `[OWNER TO CONFIRM]` | `web_copy_v1` (`ef68952e...`) / `[URL HOLD-04]` | `HELD` | `[TBD America/Edmonton]` | `[UNOBSERVED]` | `[ASSIGN NAMED OPERATOR]` |

---

## 3. Three-Milestone Exposure & Handoff Ledger (`CH-04`)

> **Hard Rule:** An **unlisted link** placed in a newsletter, partner toolkit, or web preview counts as **external exposure** at send/placement. Never treat Milestone 1 internal preview as clearance for Milestone 2 or 3.

| Milestone | Recipient (`[ASSIGN NAMED DELEGATES]`) | Artifact Version & Permitted Use | Hard Gate Before Moving | Receiving Check (`G05`) |
| :--- | :--- | :--- | :--- | :--- |
| **1 · Internal Handoff** | Content Manager (`CNT-M`) + Marketing (`MKT-S`) | `V2` custody set (`cut_v2_manifest.json`, `captions_v2.srt`, `short_cutdown_v2.md`, `web_copy_v1.md`) — **internal review & prep ONLY** | `HOLD-04` capture + `G03` (`MP-10` `V2` playback/caption QC) + RA `[PICK 1..3]` confirmation (`CD-01`) | Receiver confirms `V2` files open cleanly, plays cut with captions on, and identifies held items. |
| **2 · First External Access** | Authorized Newsletter Segment (`CH-09`) or Web Companion Page (`CH-07`) | **Requires finalized locked `V2` (`G06`)** + verified BiblioCommons list URL (`HOLD-04`) | `G03` + `G04` + `G06` release scope cleared for exact URL and send time | Authorized sender/content owner opens exact live link on desktop & mobile **before** send/publish. |
| **3 · Public Amplification** | YouTube Public + Shorts + IG Reels (+ conditional Carousel) | `TNQ-EP01-V2` public + `short_cutdown_v2.md` native vertical variants | Independent clearance per surface (`G06` + `HOLD-03` Digital Marketing calendar) | Inspect live post, `9:16` safe crop, caption toggling, and pinned comment / Related Video route. |

---

## 4. Unbundled Cross-Platform Copy & Draft Specifications (`CH-06` / `CH-09`)

| Surface | Draft Copy, Alt Text & Native Job | Controlling Asset / Route | Explicit Status / Skip Rule |
| :--- | :--- | :--- | :--- |
| **YouTube Long-Form** | Title/Description above (`4m 38s` `V2`, chapters `0:00–4:11`); pinned comment: *"Drop a 1-line reading constraint (`I liked X, I'm sick of Y, give me Z`)—we may pull yours onto the table for Episode 2."* | `cut_v2_manifest.json` + `captions_v2.srt` + `[VERIFY BIBLIOCOMMONS URL — HOLD-04]` | **Primary Flagship (`G06` HELD)** |
| **YouTube Shorts** | **44s Vertical (`short_cutdown_v2.md`):** On-screen line `"If you want fast, skip the setup."` Caption/Title draft: *"Stuck in a reading slump? Three questions under 220 pages #calgarylibrary"* + Studio **Related Video** -> `TNQ-EP01-V2` (`HOLD-02` feature check). | `short_cutdown_v2.md` (`b4f08ff4...`) | **Active Derivative (`G06` HELD)** |
| **Instagram Reels** | **44s Vertical (`short_cutdown_v2.md`):** Draft caption: *"Tired of 600-page algorithm picks? Tell us what kind of weekend read you want in the comments—or check our full reading picks via `[VERIFY LINK-IN-BIO ROUTE — HOLD-03]`."* *(No clickable description URL.)* Alt text: *"Calgary Public Library Readers' Advisory specialist at a wooden table sliding three slim paperbacks into view."* | `short_cutdown_v2.md` (`9:16`) | **Active Derivative (`HOLD-03` calendar)** |
| **Instagram Carousel** | **4-Slide Draft:** Slide 1 (`SETUP-D` `4:5` still): *"One Storm. Under 220 Pages."* · Slides 2–4: `[PICK 1..3 TITLE & 1-LINE HOOK — CONFIRM HOLD-04]`. Alt text template: *"Cover and single-sentence description of `[PICK TITLE]` selected by Calgary Public Library Readers' Advisory."* | `SETUP-D` `4:5` wrap still + RA cover specs | **Conditional (`HOLD-03` Digital Marketing slot)** |
| **Facebook** | — | — | **EXPLICIT SKIP by default** *(only adapt if tied to a verified local branch book club `[HOLD-04]`)* |
| **LinkedIn** | — | — | **EXPLICIT SKIP** *(wrong audience job for `S1`)* |
| **`calgarylibrary.ca` Web** | Companion reading-list card & YouTube embed (`artifacts/web_copy_v1.md`, `ef68952e...`) | `web_copy_v1.md` + `[VERIFY EVERGREEN RA PAGE URL — HOLD-04]` | **Independent of cut trims (`CHG-01`)** |
| **Newsletter (Email `CH-09`)** | **Subject (Draft):** `Three fast reads under 220 pages (for a snowy weekend)` · **Preheader (Draft):** `Plus drop your reading constraint for our next YouTube diagnostic.` · **Body/CTA:** `SETUP-D` still + 2-line setup + `"Check live availability or place a hold"` linking to `[VERIFY BIBLIOCOMMONS / VIDEO URL — HOLD-04]`. *(Never embed raw video player inside email; sender checks preview before send.)* | `SETUP-D` still + `web_copy_v1.md` copy | **Conditional (`HOLD-03` segment owner)** |
