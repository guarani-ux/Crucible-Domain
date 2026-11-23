# Pilot A · Episode 1 `CHG-01` Trim Reconciliation (`V1 -> V2` via `0.1.1` `check_artifact.py`)

> **Controlling Current Release Pack:** [03_release_package_v2.md](./03_release_package_v2.md) (`V2` draft) · **Superseded `v1` Pack:** [03_release_package_v1.md](./03_release_package_v1.md) (`STALE`)
> **Simulation Scope Note:** `cut_v1_manifest.json` (`282s`) and `cut_v2_manifest.json` (`278s`) are **pre-shoot synthetic `CHG-01` custody rehearsal manifests** modeling a `-4s` Beat 2 trim prior to physical capture (actual `.mp4` master path remains `[PENDING CAPTURE — HOLD-04]`).
> **Verification Tool Executed Live on Windows:** `.agents/plugins/inner-gravity/skills/ig-reconcile/scripts/check_artifact.py` (`inner-gravity` `0.1.1`).
> **Authority Invariant (`K-WOS-02` / `K-ARCH-03`):** Byte-level SHA-256 `match` proves **file custody ONLY**. `G03` playback/caption timing QC (`MP-10`), `G05` receiver open check, and `G06` release authorization (**`UNKNOWN_DO_NOT_RELEASE`**) remain **`HELD`** until human sign-off. `v1` preview status NEVER transfers to `v2`.

---

## 1. Initial `check_artifact.py` Probes (Detecting Trim Drift vs. Unaffected Copy)

```json
{"path": "artifacts/cut_v2_manifest.json", "expected_sha256": "4cc22bc6fdd793e07d40d75dd2497aabaac2842788a32e64e47b5969282d3f02", "observed_sha256": "6fee4e4c02b39852528ec9643753783e644b03b9aba33dfe17641523e3ca59fd", "state": "mismatch"}
{"path": "artifacts/web_copy_v1.md", "expected_sha256": "ef68952e588d6c9aa623af7a7c3868e09b387859591fdcdc73f700fb22f27b4f", "observed_sha256": "ef68952e588d6c9aa623af7a7c3868e09b387859591fdcdc73f700fb22f27b4f", "state": "match"}
```

- **Effect:** `mismatch` automatically blocked `v2` acceptance/release under `v1` records and flagged **only** timing-coupled assets (`captions_v1.srt`, `short_cutdown_v1.md`) for refresh—leaving `web_copy_v1.md` untouched (`match`, zero wasted rework).

---

## 2. Artifact Disposition Matrix (`STALE` vs. `VALID` vs. `REFRESHED_PENDING_G03_G06`)

| Artifact Path | Controlling SHA-256 | Disposition After `-4s` Trim | Reason & Next Permitted Action |
| :--- | :--- | :--- | :--- |
| `artifacts/cut_v1_manifest.json` | `4cc22bc6fdd793e07d40d75dd2497aabaac2842788a32e64e47b5969282d3f02` | **`STALE` (Superseded)** | Replaced by `TNQ-EP01-V2`; retain for provenance only (`v1` circulated to: **none**). |
| `artifacts/captions_v1.srt` | `a814eb908d5298a941e8cbbcda94207123ab67fae0d4ec332e8323d5f9788266` | **`STALE` (Superseded)** | Cues 4–8 drift `+4s` against `TNQ-EP01-V2`. Replaced by `captions_v2.srt`. |
| `artifacts/short_cutdown_v1.md` | `6e827d74e05ee8cb9d008beebd992b6656fa3eae9090328f762c4e70b9739c69` | **`STALE` (Superseded)** | Beat 3 cue bound to `v1` timing (also carried a `36s` vs `44s` arithmetic typo). Replaced by `short_cutdown_v2.md`. |
| **`artifacts/web_copy_v1.md`** | `ef68952e588d6c9aa623af7a7c3868e09b387859591fdcdc73f700fb22f27b4f` | **`VALID` (Unchanged)** | Zero cut timecodes; unaffected by Beat 2 trim (`[HOLD-04]` RA titles & URL still apply independently). |
| **`artifacts/cut_v2_manifest.json`** | `6fee4e4c02b39852528ec9643753783e644b03b9aba33dfe17641523e3ca59fd` | **`REFRESHED_PENDING_G03_G06`** | Controlling `V2` cut manifest (`278s`). **Blocked** on physical capture (`HOLD-04`), fresh `MP-10` playback QC (`G03`), and `G06` release authorization (`UNKNOWN_DO_NOT_RELEASE`). |
| **`artifacts/captions_v2.srt`** | `57a027af5c212899eca9f039b344b161f31123d66f49f5eaf13c69ca0047dcd0` | **`REFRESHED_PENDING_G03_G06`** | Full 17-cue script-matched `.srt` aligned to `TNQ-EP01-V2` (`00:01:32,000`..`00:04:36,000`). Requires `MP-10` playback check with real `V2` cut (`G03`). |
| **`artifacts/short_cutdown_v2.md`** | `b4f08ff4af6fe485174013496c91f52dd52db76c943c364b0101d06753c84f8b` | **`REFRESHED_PENDING_G03_G06`** | Re-bound to `TNQ-EP01-V2` SHA-256 (`36s + 8s = 44s` exact runtime; Beat 3 segment shifted `-4s` to `00:01:34–00:01:42`). Requires `G03` crop/caption QC + `G06`. |

---

## 3. Controlling `V2` Release-Set Custody Verification (`check_artifact.py` Post-Revision)

All four controlling files in the active `V2` release set verified `match` on Windows after selective refresh and audit patching:

```json
{"path": "artifacts/cut_v2_manifest.json", "expected_sha256": "6fee4e4c02b39852528ec9643753783e644b03b9aba33dfe17641523e3ca59fd", "observed_sha256": "6fee4e4c02b39852528ec9643753783e644b03b9aba33dfe17641523e3ca59fd", "state": "match"}
{"path": "artifacts/captions_v2.srt", "expected_sha256": "57a027af5c212899eca9f039b344b161f31123d66f49f5eaf13c69ca0047dcd0", "observed_sha256": "57a027af5c212899eca9f039b344b161f31123d66f49f5eaf13c69ca0047dcd0", "state": "match"}
{"path": "artifacts/short_cutdown_v2.md", "expected_sha256": "b4f08ff4af6fe485174013496c91f52dd52db76c943c364b0101d06753c84f8b", "observed_sha256": "b4f08ff4af6fe485174013496c91f52dd52db76c943c364b0101d06753c84f8b", "state": "match"}
{"path": "artifacts/web_copy_v1.md", "expected_sha256": "ef68952e588d6c9aa623af7a7c3868e09b387859591fdcdc73f700fb22f27b4f", "observed_sha256": "ef68952e588d6c9aa623af7a7c3868e09b387859591fdcdc73f700fb22f27b4f", "state": "match"}
```

---

## 4. Hold Reference Legend & Named Delegate Slots (`G05`)

> Defined locally so a receiving colleague never needs to hunt outside this folder (`GROUND_TRUTH.md` + [../youtube-series-pitch/GROUND_TRUTH.md](../youtube-series-pitch/GROUND_TRUTH.md)):

| Hold ID | Open Condition / Missing Input | Owner to Confirm |
| :--- | :--- | :--- |
| **`HOLD-01`** | Pitch meeting date, formal greenlight owner, and Phase 2 Media Content Framework integration | Media Production lead (`PROD-D`/`PROD-M`) + Communications & Engagement sponsor |
| **`HOLD-02`** | 2026 YouTube Analytics baseline & Studio advanced-features status (Shorts `Related Video` eligibility) | Channel Stewards / Digital Marketing & Analytics |
| **`HOLD-03`** | Digital Marketing 2027 editorial calendar slots, IG link-in-bio destination, playlist name, and newsletter segment owner | Digital Marketing lead / coordinator (`MKT-M`/`MKT-S`) |
| **`HOLD-04`** | Branch room booking, RA Specialist consent (`MP-05`), `[PICK 1..3]` book titles, and exact BiblioCommons / `calgarylibrary.ca` URLs | Media Production lead + Service/RA Owner + Content Owner (`CD-01`) |
| **`HOLD-05`** | Licensed music tracking (if any track added at fine cut) and CMS embed workflow on `calgarylibrary.ca` | Media Production + Content/Web Owners (`CNT-M`/`CNT-S`) |

### Next Permitted Receiver & Operator Actions (Assign Named Delegates Before `G05`)
1. **Media Production (`PROD-M` / `PROD-S` — `[ASSIGN NAMED DELEGATE]`):** Complete `HOLD-04` clearances (`02_capture_plan_and_call_sheet.md`), capture footage, then execute `MP-10` playback & caption QC on real `TNQ-EP01-V2` + `captions_v2.srt` + `short_cutdown_v2.md` (`G03`).
2. **Content & Digital Marketing Receivers (`CNT-M` / `MKT-S` — `[ASSIGN NAMED RECEIVING DELEGATE]`):** Can prep `web_copy_v1.md`, verify exact BiblioCommons/`calgarylibrary.ca` URLs (`HOLD-04`), and stage [03_release_package_v2.md](./03_release_package_v2.md) copy immediately; **hold** all external YouTube/Newsletter/Social exposure until `G03` (`V2`) and `G06` release authorization are recorded.
3. **Human Release Owner (`G06` — `[ASSIGN NAMED AUTHORIZER]`):** Remains `UNKNOWN_DO_NOT_RELEASE`; no upload, unlisted send, or scheduled publication is authorized by this custody check.
