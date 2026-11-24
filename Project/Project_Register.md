# Project Register

First intake · November 15, 2026 · Calgary

Use this register to locate a project, understand its current evidence, and decide whether to continue, revisit, combine, or park it. A **top-level project** is a continuing outcome or commitment with its own scope and decision history. A **repository** is a source artifact that may support a project, implement one component, or preserve an earlier attempt. A **historical system** is a subject of study with lessons and evidence of its own. Treat relationships between these records as explicit and source-backed.

## Top-level projects

| ID | Project or component | Purpose and observed or reported state | Next point to verify | Source |
| --- | --- | --- | --- | --- |
| P-WOS | Work Operating System | Active design and validation. The current handoff calls for a first end-to-end workflow plan. The Drive project has a README and graph catalog. Application code is frozen. | Confirm what Mugen can open and run in their environment and which workflow will be exercised. | [GitHub handoff](https://github.com/guarani-ux/Work-Operating-System/blob/main/HANDOFF.md) · [Drive project](https://drive.google.com/drive/folders/1Wa4YCSoXhpfuv01dfgVysKEg-g_bP6ZT) |
| P-CRUCIBLE | Crucible Domain | Active **Orchestrator-Producer Hub (single control plane)** and flagship personal systems-engineering workstream (`Personal Work/GROUND_TRUTH.md`). Frames assignments, resolves domain `GROUND_TRUTH.md` and approval gates, supplies non-evidentiary craft methods, and drives lightweight MCP spokes (`.agents/plugins/<spoke>/`, starting with `writers-room` at `f27f829` / `ef2d065`, `K-MCP-01`). Modular `.agents/scripts/crucible/` RAM router/forge/sieve/ledger, `K-TEST-01` + `mutation_gate.py`, 43-repo inventory, and `Calgary Public Library/` + `Personal Work/` intakes active (`22 PASS \| 0 WARN \| 0 FAIL`). | Strip heavy `claims[]` / forensic verification tax on exploratory MCP spoke workflows (`K-MCP-01`) before onboarding `Story-Lane`, and run Rung 4 colleague delivery on CPL pitch/pilot. | [Crucible Domain](https://drive.google.com/drive/folders/1jpG-7DjOa2xtiYPbBhL07qmCRSVrK1fU) · [GitHub repo](https://github.com/guarani-ux/Crucible-Domain) |

## Reviewed supporting systems and capabilities

These entries describe systems or components. Their existence here establishes a study or reuse lead. Project boundaries and parent relationships require evidence.

| ID | System or component | Purpose and observed or reported state | Next point to verify | Source |
| --- | --- | --- | --- | --- |
| P-STORY-LANE | Story-Lane | Agent-assisted selection and traceable clip extraction. README reports 18 clips and notes from retained transcripts. The archaeology exhibit adds a [direct CI record](https://github.com/guarani-ux/Story-Lane/actions/runs/42031205858) for one clean human-voice reference on the two tested native platforms. Current work commitment unknown. | Check the latest execution receipt and intended runtime before planning a fresh transcription or reuse. | [GitHub README](https://github.com/guarani-ux/Story-Lane/blob/main/README.md) · [Library execution receipt, located](https://chatgpt.com/library?file_id=libfile_ad5d0875728081919639879e55d40699&account_id=personal) |
| P-CONSTELLATION | Constellation | Portable technique library. README identifies v0.1.0 as assembled and cognitive benefit as unmeasured. Current work commitment unknown. | Recover which techniques have been exercised, under what conditions, and what evidence would change their use. | [GitHub README](https://github.com/guarani-ux/Constellation/blob/main/README.md) |
| P-KNOWLEDGE-SIDECAR | Constellation Knowledge Sidecar | Component associated with Constellation. README describes a v0.2 file-first CLI, one canonical seed, and source-linked records. Nov 23 GitHub `pushed_at` reflects a transient `refs/heads/mercury` branch spun out into `guarani-ux/mercury`; `main` (`3c1f52b`, covered by `A06`) and `domain/*` branches remain unchanged since `2026-11-11` (`domain/software-systems-architecture@5399b6c` adds only a 2026-11-11 verification handoff). | Review the recorded qualification before using it as an automated retrieval layer for Crucible Domain. | [GitHub README](https://github.com/guarani-ux/sidecar/blob/main/README.md) |
| P-KOMOREBI-WORKSPACE | Komorebi Slack workspace | Work coordination workspace referenced in the Work Operating System recap. Historical manual Slack trial and navigation retest recorded there. The separate GitHub repository README did not establish a connection to the current workspace. | Verify current Slack entry, operator access, and relationship to the repository if it matters. | [Workspace entry, reported in the supplied recap](https://app.slack.com/archives/C0CHLMD2U94/p1794613145600319) · [GitHub README](https://github.com/guarani-ux/Komorebi/blob/master/README.md) |

## Leads recovered from conversation history

| ID | Lead | Evidence and unresolved question |
| --- | --- | --- |
| C-COGNITIVE-OS | Cognitive OS | October 22 conversation reports a Python and SQLite prototype with capture and event history. [A matching GitHub repository was located](https://github.com/guarani-ux/cognitive-os). Verify the relationship, current branch, and what was demonstrated. |
| C-CONTROL-CENTRE | Control Center | October 29–30 conversations describe experimental intake and recovery components. Verify their canonical project, current status, and which reported tests apply to the end-to-end workflow. |
| C-CAP | Capability Accessibility CLI | November conversation and file history describe CAP-001 as an experiment about how context, knowledge, tools, and human participation affect results. Recover the current source and runtime evidence before assigning a status. |
| C-KERNEL-DOMAIN | Kernel Domain | Levi described it as both a project and a knowledge source for processes and skills. Recover the current artifact or location and clarify its relationship to Crucible Domain before moving any material. |

## Repository archaeology

The [ten-system exhibit](https://drive.google.com/file/d/1864tO3qjxuC0Adv0I9s2JHQaQw_eiSDs/view?usp=drivesdk) examines selected systems in depth. Its `A01`–`A10` IDs identify exhibit subjects. Selection for study conveys historical or transfer value and leaves live project status to project evidence.

## GitHub discovery

Live owner inventory on `2026-11-23` via `crucible_gate.py melt-diff` and `gh api` returned **43 repositories** under `guarani-ux` (up from 39 at initial intake, adding `the-writers-room`, `mercury`, `Crucible-Domain`, and `antigravity-config`). Read rows as repository observations. Private links retain their original access requirements.

| Repository | Visibility | Default branch | Pushed | Disk | Coverage |
| --- | --- | --- | --- | --- | --- |
| [antigravity-config](https://github.com/guarani-ux/antigravity-config) | private | master | 2026-11-23 | 437KB | Active Hub / Config |
| [Crucible-Domain](https://github.com/guarani-ux/Crucible-Domain) | private | master | 2026-11-23 | 369KB | Active Hub / Config |
| [the-writers-room](https://github.com/guarani-ux/the-writers-room) | private | main | 2026-11-23 | 316KB | Active MCP Spoke (`ef2d065`; `193/193` tests; `PRIM-01`, `PRIM-02`, `PRIM-12`, `K-MCP-01`) |
| [sidecar](https://github.com/guarani-ux/sidecar) | private | main | 2026-11-23 | 122KB | Melted (A06; stale 2026-11-23 update checked) |
| [mercury](https://github.com/guarani-ux/mercury) | private | main | 2026-11-23 | 112KB | Primitive-Extracted (`PRIM-12`) |
| [Work-Operating-System](https://github.com/guarani-ux/Work-Operating-System) | private | main | 2026-11-15 | 123KB | Active Hub / Config |
| [Story-House](https://github.com/guarani-ux/Story-House) | private | main | 2026-11-09 | 1612KB | Primitive-Extracted (`PRIM-01`, `PRIM-10`) |
| [Story-Lane](https://github.com/guarani-ux/Story-Lane) | private | main | 2026-11-09 | 1029KB | Melted (A07) |
| [Hagoromo](https://github.com/guarani-ux/Hagoromo) | private | main | 2026-11-07 | 4724KB | Melted (A08) |
| [mugen](https://github.com/guarani-ux/mugen) | private | main | 2026-11-05 | 5154KB | Selective Skill Check (`PRIM-13` CPL skills) |
| [Storylines](https://github.com/guarani-ux/Storylines) | private | main | 2026-11-04 | 10943KB | Untested Scaffold / Prototype |
| [Kageyoni](https://github.com/guarani-ux/Kageyoni) | private | main | 2026-10-28 | 17326KB | Melted (A02) |
| [genesis](https://github.com/guarani-ux/genesis) | private | main | 2026-10-24 | 36468KB | Skip Stub (0 code / 0 tests; initialized README + asset) |
| [nelson-media](https://github.com/guarani-ux/nelson-media) | public | main | 2026-10-24 | 97KB | Untested Scaffold / Prototype (1 code file, 0 tests) |
| [SAMSARA](https://github.com/guarani-ux/SAMSARA) | private | main | 2026-10-24 | 2369614KB | Melted (A04) |
| [cognitive-os](https://github.com/guarani-ux/cognitive-os) | private | main | 2026-10-23 | 196KB | Melted (A09) |
| [script-builder](https://github.com/guarani-ux/script-builder) | private | main | 2026-10-22 | 51KB | Untested Scaffold / Prototype |
| [Video-House](https://github.com/guarani-ux/Video-House) | private | main | 2026-10-22 | 1323KB | Primitive-Extracted (`PRIM-05`, `PRIM-10`) |
| [video-house-intel](https://github.com/guarani-ux/video-house-intel) | private | main | 2026-10-21 | 32KB | Selective Skill Check |
| [The-Canvas](https://github.com/guarani-ux/The-Canvas) | private | main | 2026-10-08 | 1167KB | Tested Rust CLI (27 code, 22 tests; not primitive-extracted) |
| [Shinobi](https://github.com/guarani-ux/Shinobi) | private | main | 2026-10-06 | 143522KB | Melted (A03) |
| [Constellation](https://github.com/guarani-ux/Constellation) | private | main | 2026-10-03 | 46KB | Melted (A05) |
| [Nelson](https://github.com/guarani-ux/Nelson) | private | main | 2026-09-18 | 1676KB | Melted (A10) |
| [Hidden-Booder-Village](https://github.com/guarani-ux/Hidden-Booder-Village) | private | main | 2026-09-17 | 151293KB | Primitive-Extracted (`PRIM-03`) |
| [10-shadows](https://github.com/guarani-ux/10-shadows) | private | master | 2026-09-17 | 1059KB | Primitive-Extracted (`PRIM-08`) |
| [komorebisans](https://github.com/guarani-ux/komorebisans) | private | main | 2026-09-07 | 581KB | Duplicate of Outer-Sanctum |
| [Outer-Sanctum](https://github.com/guarani-ux/Outer-Sanctum) | private | main | 2026-09-07 | 580KB | Primitive-Extracted (`PRIM-10`, `PRIM-11`) |
| [job-hunter](https://github.com/guarani-ux/job-hunter) | private | main | 2026-08-28 | 93KB | Untested Scaffold / Prototype |
| [ten-shadows-control](https://github.com/guarani-ux/ten-shadows-control) | public | master | 2026-08-28 | 105KB | Primitive-Extracted (`PRIM-11`; `10-shadows` pair) |
| [ichimonji](https://github.com/guarani-ux/ichimonji) | private | main | 2026-08-25 | 954KB | Untested Scaffold / Prototype |
| [espada](https://github.com/guarani-ux/espada) | private | main | 2026-08-01 | 364KB | Primitive-Extracted (`PRIM-08`, `PRIM-09`) |
| [PPW-Prime](https://github.com/guarani-ux/PPW-Prime) | private | main | 2026-04-19 | 64KB | Skip Stub (0 code / 0 tests; README only) |
| [Komorebi](https://github.com/guarani-ux/Komorebi) | private | master | 2026-04-16 | 6784KB | Selective Skill Check |
| [Dangai](https://github.com/guarani-ux/Dangai) | private | main | 2026-04-14 | 0KB | Skip Stub (<=5KB / 0 code) |
| [entonkageyoni](https://github.com/guarani-ux/entonkageyoni) | private | main | 2026-04-12 | 11521KB | Melted (A01) |
| [marketing-production-os](https://github.com/guarani-ux/marketing-production-os) | private | main | 2026-01-09 | 4KB | Skip Stub (<=5KB / 0 code) |
| [mobile-command-v9](https://github.com/guarani-ux/mobile-command-v9) | private | main | 2026-01-08 | 111KB | Untested Scaffold / Prototype |
| [cpl-command-center](https://github.com/guarani-ux/cpl-command-center) | private | main | 2026-01-08 | 2KB | Skip Stub (<=5KB / 0 code) |
| [cpl-mobile-studio0](https://github.com/guarani-ux/cpl-mobile-studio0) | private | main | 2026-01-08 | 31KB | Untested Scaffold / Prototype |
| [cpl-mobile-studio](https://github.com/guarani-ux/cpl-mobile-studio) | private | main | 2026-01-08 | 2KB | Skip Stub (<=5KB / 0 code) |
| [media-production-studio2](https://github.com/guarani-ux/media-production-studio2) | private | main | 2026-01-08 | 1516KB | Untested Scaffold / Prototype |
| [media-production-studio](https://github.com/guarani-ux/media-production-studio) | public | main | 2026-01-07 | 0KB | Skip Stub (<=5KB / 0 code) |
| [Cpl-factory](https://github.com/guarani-ux/Cpl-factory) | private | main | 2026-01-07 | 30KB | Untested Scaffold / Prototype |

## Add or update a project

Record a stable project ID, title, purpose, domain, canonical link or exact source locator, status and its evidence, date checked, and next action or open decision. Link related repositories, conversations, artifacts, and knowledge entries under that ID. Use Active when a current commitment or next action is evidenced. Use status unknown if you only found the artifact, and record a reason when parking, completing, or superseding a project. Update the row when evidence changes and retain the earlier source.

## Coverage for the initial discovery intake

| Source | Checked | Remaining |
| --- | --- | --- |
| GitHub | Full 43-repo triage on `2026-11-23` via `melt-diff`/`melt-scan` and read-only `gh api` (10 melted in `A01`–`A10` with `sidecar` stale check, 3 active hubs, 9 primitive-extracted, 3 selective skill checks, 1 duplicate, 10 untested scaffolds/prototypes, 7 stubs/0-code skips). | Exercise runtime tests before promoting external `EXTERNAL_PROVEN` / `PROTOTYPE` primitives (`PRIM-02..05`, `PRIM-08`, `PRIM-10..11`, `PRIM-13`) or untested prototypes (`The-Canvas`, `Storylines`). |
| ChatGPT conversations | Targeted search for project and practice history. | Trace earlier names, transitions, paused work, and projects without repositories to their best sources. |
| Library | Targeted title search found Story-Lane artifacts. | Review relevant contents and continue title discovery. A file's existence establishes availability through that route, not its claims. |
| Drive and supplied record | Verified current Crucible Domain layout, Work Operating System project files, and read the supplied recap. | Review additional Drive folders and prior artifacts as needed. |
| Employer and Slack records | Used the supplied recap and repository handoff as references for this intake. | Verify individual authorized sources read-only when a specific entry needs it. |

---

## Live Workspace Status Update · November 23, 2026

> Preserves the original November 15 intake table above while recording live workspace implementations and superseded items as of November 23, 2026.

| ID | Project or Deliverable | Observed State & Verified Artifacts | Next Decision / Action | Source |
| :--- | :--- | :--- | :--- | :--- |
| **P-INNER-GRAVITY** | Inner Gravity Harness & Observatory | Active workspace plugin upgraded to **`0.1.1`** (`check_artifact.py` live in `.agents/plugins/inner-gravity/`, `ig-evidence-review` aligned to `read_file`). Whole-system observatory and session `4188f88a` trace active; retired `install_pack/` staging fossils cleared and `.agents/acceptance.lock.json` synced. | Frozen under Harness Freeze until 3 human-reviewed deliverables return real feedback. | [Project/Inner Gravity/README.md](Inner%20Gravity/README.md) · [05_Session_4188f88a_Causal_Trace_and_Gaps.md](Inner%20Gravity/05_Session_4188f88a_Causal_Trace_and_Gaps.md) |
| **P-CRUCIBLE-CIRCULATION** | Local RAM Index, Router & Gates | Active in `C:\crucible-domain` (`.agents/scripts/crucible_gate.py`, `.agents/scripts/crucible/`). `SessionStart`, `PreToolUse` (`SHIFTING_SAND` + Asana URL guard), `check`, `doctor`, and `route` active; retired OneDrive copy, `judgment_gate.py`, and unused Contract Stop Gate removed. | Frozen under Harness Freeze; focus shifts to real-world deliverables. | [README.md](../README.md) · [.agents/scripts/crucible_gate.py](../.agents/scripts/crucible_gate.py) |
| **P-CPL-YOUTUBE** | Calgary Public Library Ground Truth & Pilot A | Canonical institutional baseline promoted to `Calgary Public Library/GROUND_TRUTH.md`. Completed audited 5-series YouTube pitch (`youtube-series-pitch/`) and Pilot A Ep 1 downstream execution + `CHG-01` test (`pilot-a-the-next-question-ep01/`). | Present pitch & confirm `[HOLD-01..05]` clearances (`G01`–`G06`) with CPL decision owners. | [Calgary Public Library/GROUND_TRUTH.md](../Calgary%20Public%20Library/GROUND_TRUTH.md) |
| **P-WRITERS-ROOM-MCP** | Writer's Room MCP Spoke Coupling (`K-MCP-01`) | Live 3-file workspace plugin (`.agents/plugins/writers-room/`) connected to `C:\the-writers-room` (`ef2d065`, `193/193` tests green): form-first recognition + opt-in pinned craft (`MW-01`, `MW-02`, `MW-04`), fresh/resumed cut-authority floor, and `K-MCP-01` single-control-plane / stage-matched verification lessons recorded. | Lighten exploratory MCP authoring path (`treatment`, `production_brief`) so spokes stay deterministic tools rather than competing control planes before cloning pattern to `Story-Lane`. | [.agents/plugins/writers-room/skills/writers-room/SKILL.md](../.agents/plugins/writers-room/skills/writers-room/SKILL.md) · [Knowledge_Register.md](../Knowledge/Knowledge_Register.md) |
| **Archive (Superseded)** | Retired Staging & Sprint Fossils | Moved `overnight_mvp/`, `System_Blueprint_v2*`, Nov 15 `install_pack/` zips/staging, and `MA-SPRINT-01` into `Archive/`. | Keep read-only; do not revive without explicit need. | [Archive/README.md](../Archive/README.md) |
