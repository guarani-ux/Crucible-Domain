# Stage 5 · Crucible Domain System Field Report (Empirical Test Run)

> **Test Objective:** Run an actual Calgary Public Library deliverable (`5-Series YouTube Pitch, Cross-Platform Repurposing & Writers' Room Modulation Process`) end-to-end through Crucible Domain *without* Levi intervening mid-flight—using only Crucible's own routing, ground truth, playbooks, hooks, and subagents—to expose what Crucible Domain truly is under load, what broke, and what to simplify next.
> **Session Anchor:** `67d3d4da-fc5e-4ccb-9737-8a8ce9bd1ddd` (`HEAD` at start: `3bbc49c`, zero modifications outside `Calgary Public Library/youtube-series-pitch/`).

---

## 1. Executive Verdict

**Did the system deliver without Levi babysitting it?** **Yes—once autonomous Push-Right execution engaged, the system produced an audited, pitch-ready 5-series package (`GROUND_TRUTH.md` -> `01` Quarry -> `02` Modulation Board -> `03` 5-Series Pitch -> `04` Independent Audit & Patch) with zero coworker names, zero internal Asana link leaks, and explicit holds on unverified facts.**

**What this test proved Crucible Domain *truly* is:**
Stripped of 10+ historical experiments and meta-docs, Crucible Domain only needed **four working engines** to turn a messy real-world ask into a clean deliverable:
1. **Local Context & Custody Anchors** (`cpl_handoff_portable.yaml`, `institutional-evidence.md`, `Work_Operating_System_Media_Roles...md`) — prevented generic AI advice by pinning real mandates, past misses, and authority fences.
2. **26 ms RAM Capability Routing** (`crucible_gate.py route`) — immediately surfaced `MW-03`, `CH-02`, `CH-03`, `MK-04`, and `idea-crucible` without scanning 98,000+ words of Markdown.
3. **High-Craft Domain Methods** (`av-craft` + core `MW`/`CH`/`MK`/`MP`/`CD` procedures) — forced visual-first thinking, `Because -> But -> Therefore` spines, and capture-once platform discipline.
4. **Adversarial Separation of Duties** (`ig-evidence-review` subagent) — caught real hallucinations, role conflations, and episode-engine collapses that the primary writer model missed even with all rules loaded.

**Everything else on disk—roughly 85–90% of the repo's prose and archived scaffolding—played zero active role.**

---

## 2. Capability Utilization Ledger (`[OBSERVED]`)

Out of **`129` indexed capabilities** reported by `crucible_gate.py doctor` (`procedures=55, roles=12, knowledge=9, projects=10, exhibits=10, skills=28`), below is what actually fired during a full creative/strategic deliverable:

| Layer | Total on Disk | Actually Used in Run | Untouched Mass & Interpretation |
| :--- | :--- | :--- | :--- |
| **Gate & Router Scripts** | `crucible_gate.py`, `crucible_index.py`, `collect_observatory.py`, `check_sync.py`, `observe.py` | `crucible_gate.py` (`route`, `pre-tool`, `check`, `doctor`) | `collect_observatory.py` and `check_sync.py` serve harness introspection only—not domain production. |
| **Media Procedures (`MW/MP/MK/CD/CH/OP`)** | `55` procedures across `6` manuals | **Drafting (~12):** `MW-03`, `MW-05`, `CH-01`, `CH-02`, `CH-03`, `CH-04`, `CH-05`, `CH-06`, `CH-08`, `CH-09`, `MK-01`, `MK-03`, `MK-04`.<br>**Audit (~10 more verified by reviewer):** `MW-02`, `MK-02`, `MK-06`, `MK-08`, `CD-01`, `CH-07`, `MP-02`, `MP-04`, `MP-05`, `MP-10`. | **~33 procedures (~60%) untouched** (`OP-01..08`, call sheets, live broadcast flows, paid media `MK-10`, graphic/motion production `CD-05..08`). Good as an on-demand reference library **only if hidden behind `route`**—dead weight when browsed manually. |
| **Role Graphs (`COM-D..CNT-S`)** | `12` individual role files + `3` overview docs | `Skills and Workflows/README.md` + `Media_Work_Routing.md` + `Work_Operating_System_Media_Roles...md` (checked by auditor to catch role-code drift) | **12/12 standalone role files untouched.** Summary tables in `Skills and Workflows/README.md` and `Work_Operating_System_Media_Roles...md` covered every role question faster. |
| **Global & Plugin Skills** | `28` indexed skills (`skill_frontmatter=8019B`) | `mode-reframe`, `negative-space`, `recursive-meta-calibration`, `av-craft`, `ig-discover-method`, **`ig-evidence-review`** | **~22 skills unused** (expected—different domains like `cl-craft`, `diagnosing-bugs`, `canva-*`, `gcalendar`, etc.). |
| **Knowledge & Archaeology** | `Knowledge_Register.md` (`9` entries) + `10` exhibits (`A01`–`A10`) | Principles internalized via `cpl_handoff_portable.yaml` (`CHG-01`, `K-WOS-01..03`, `K-ARCH-03`) | **10/10 Archaeology exhibits (`A01`–`A10`) unread during delivery.** They belong strictly in cold archive/reference, not near live project entry points. |
| **Project / Harness Scaffolding** | `Project/Inner Gravity/` (`14+` files, `install_pack/`, `overnight_mvp/`) + `MA-SPRINT-01` | **Only 1 file mattered for CPL work:** `Project/Inner Gravity/overnight_mvp/cpl_handoff_portable.yaml` | `System_Blueprint_v2*`, `01..05` architecture files, `install_pack/` zips, `overnight_mvp/hours/*`, and `MA-SPRINT-01` are harness/planning fossils relative to real delivery. |

---

## 3. Observed Friction, Failures & Drift (`[OBSERVED]`)

Running a real task exposed **six concrete system defects** that static audits missed:

1. **Failure 1 — Turn-0 Over-Asking ("Babysitting Loop"):**
   - *What happened:* When Levi named the YouTube 5-series deliverable, the assistant paused to ask **4 intake questions** before writing `GROUND_TRUTH.md`—even though **~80% of the factual context** (`2027–2030` mandates, `213`-video audit, `PITCH-NQ`/`PITCH-YCD`, read-only Asana, no coworker names, crew constraints) was already sitting on disk.
   - *Root Cause:* `SHIFTING_SAND` in `crucible_gate.py` says *"Establish ground truth (workflow, audience, purpose) before proposing deliverables"*, which biases the LLM toward interviewing the user rather than **synthesizing local ground truth first, tagging reversible `[PROPOSED DEFAULT]` / `[UNKNOWN]` holds, and executing autonomously**.
2. **Failure 2 — Real Domain Ground Truth Buried in an Abandoned Harness Subfolder:**
   - *What happened:* The cleanest, most up-to-date Calgary Public Library ground truth (`cpl_handoff_portable.yaml`) was buried inside `Project/Inner Gravity/overnight_mvp/`—an unexecuted 6-hour overnight MVP spec—while `Calgary Public Library/` itself sat at `0 [EMPTY]`.
   - *Consequence:* Without manually inspecting `Project/Inner Gravity/overnight_mvp/`, an ordinary run starting in `Calgary Public Library/` would miss the `213`-video audit, `PITCH-NQ`/`PITCH-YCD`, and the `2027–2030` vs. internal-lens distinction.
3. **Failure 3 — `DRIFT-TOOL` Hypothesis Disproved Live; `ig-evidence-review` Proven Essential:**
   - *What happened:* `cpl_handoff_portable.yaml#L74-76` claimed `ig-evidence-review` suffered tool drift (`view_file` vs. `read_file`). In live testing (`dd3cb411-0a7d-4a41-8b96-a87278995780`), the Antigravity host transparently mapped `read_file` access (`step_index: 1` of transcript) and the subagent audited every draft and controlling source verbatim.
   - *Why it matters:* Meanwhile, **even with `av-craft`, `recursive-meta-calibration`, and `Media Agency` rules loaded, the primary writer model STILL introduced 4 classes of defects** in its first draft: (a) let `S2` Ep 3 and `S3` Ep 2 slip toward orientation/montage, (b) bundled platform rows (`YT Shorts / IG Reels`, `Web & Newsletter`) and suggested email embeds, (c) mislabeled the `[PROPOSED WORKING MODEL]` `G01`–`G06` table as `[VERIFIED LOCAL]` and shifted `G05`/`MKT-M` definitions, and (d) added unverified polish (`$150`, `"borrow today"`, `"Shorts-to-Long bridge views"`). **Only the separate read-only `ig-evidence-review` pass caught and fixed these.**
4. **Failure 4 — Contract Stop Gate (`cmd_verify` / `cmd_stop`) Cannot Start Mid-Session:**
   - *What happened:* `_verify_contract()` in `crucible_gate.py:458` rejects any ````contract` block added to `IDEAS.md` during a live session (`contract changed mid-session; Levi must approve and commit it`).
   - *Consequence:* Any deliverable requested dynamically during a conversation cannot use the Contract Stop Gate at all unless pre-committed before the session begins.
5. **Failure 5 — Persistent Repo & Plugin Drift:**
   - `crucible_gate.py doctor` still warns on `[WARN] storage · .tmp.drivedownload,.tmp.driveupload` (live `.git` inside OneDrive/Drive).
   - `.agents/plugins/inner-gravity/plugin.json` is still `0.1.0` while `0.1.1` sits archived in `install_pack/`.
   - `.agents/acceptance.lock.json` lags `install_pack/acceptance.lock.json.ready`.
   - `ig-evidence-review.md` frontmatter still lists `view_file` instead of `read_file` (cosmetic drift now proven harmless by host mapping, still worth aligning).
6. **Failure 6 — Playbook Redundancy (`MW-03`/`CH-02`, `MW-05`/`CH-06`) vs. Real Leverage:**
   - Across `media-writing.md`, `channel-and-content-operations.md`, and `audience-and-campaigns.md`, overlapping guidance (`MW-03` vs. `CH-02`, `MW-05` vs. `CH-06`) increases read tokens (`>40 KB` of Markdown), while the actual high-leverage differentiator in this run was **26 ms RAM `route` + `02_modulation_board.md` (`Context × Experience`) + `ig-evidence-review`**.
7. **Failure 7 — Naive Asana Substring Check & Untracked Gap in `crucible_gate.py check`:**
   - `_staged_contains_asana` (`crucible_gate.py:218`) scans for the raw Asana domain substring rather than actual `https://` task URLs, AND `cmd_check` only scans *staged* files (`git diff --cached`). During verification, our own custody disclaimers naming the blocked domain literally would have falsely tripped `pre-commit` once staged, while `crucible_gate.py check` initially reported `PASS` on untracked files. Disclaimers were reworded to *"zero internal Asana URLs"*; `crucible_gate.py` should match full URLs rather than negative prose mentions.

---

## 4. Ranked `ig-improve` Action Queue (Next Moves for Crucible Domain)

Ordered strictly by empirical leverage revealed by this test:

| Priority | Concrete Change | Why It Simplifies Crucible Domain | Expected Measurable Effect |
| :--- | :--- | :--- | :--- |
| **P1** | **Promote CPL Ground Truth to `Calgary Public Library/GROUND_TRUTH.md` & Update `SHIFTING_SAND` Text** | Moves verified institutional facts out of `Project/Inner Gravity/overnight_mvp/` into the actual working directory, and instructs agents to **infer local ground truth + tag `[PROPOSED DEFAULT]` / `[UNKNOWN]` + run end-to-end** instead of pausing for intake quizzes. | Future CPL sessions start informed in 1 read with zero Turn-0 interrogation friction. |
| **P2** | **Mandate `ig-evidence-review` on All Deliverables & Clean Plugin State (`0.1.1` + `read_file`)** | Formalizes the one gate that caught real model slop/role drift in live use; upgrades `.agents/plugins/inner-gravity` to `0.1.1` (`check_artifact.py`) and aligns `ig-evidence-review.md` `tools: [read_file]`. | Catches fabrication, unbundled platform errors, and authority drift before Levi ever reads a draft. |
| **P3** | **Physical Repo Simplify: Move Live `.git` to `C:\crucible-domain` + Archive Harness Fossils** | Runs `migrate_to_local_git.ps1`, syncs `.agents/acceptance.lock.json`, and moves `overnight_mvp/`, `MA-SPRINT-01`, Nov 15 `install_pack/` zips, `System_Blueprint_v2*`, and empty `Project/Media Agency/` into `Archive/`. | Drops `doctor` to `0 WARN | 0 FAIL`; physically separates **Work (`Calgary Public Library/`, `Personal Work/`)**, **Craft (`Knowledge/`)**, and **Archive**. |
| **P4** | **Compress Media Agency Surface Around `crucible_gate.py route` + Modulation Board** | Keeps the 55-procedure archive queryable via `route`, merges duplicate series/adaptation guidance (`MW-03`+`CH-02`, `MW-05`+`CH-06`), and moves the 12 unused standalone role Markdown files to `Archive/` or `Knowledge/` cold reference. | Cuts context bloat while preserving every proven check (`CD-01`, `CHG-01`, `CH-03/04/05/08/09`, `MP-10`). |
| **P5** | **Right-Size the Stop Gate** | Acknowledge `SHIFTING_SAND` + `pre-tool` + `ig-evidence-review` + `check` already enforce real deliverable custody without requiring pre-committed `IDEAS.md` JSON ````contract` blocks on dynamic work. | Eliminates dead ceremony on spontaneous deliverables. |
