# CNT-M — Content Management Manager

**Use for** converting editorial direction into a publishable, maintainable set of pages, posts, releases, and assets. Owns queue, sequencing, package consistency, and review routing within assigned scope. An agent can plan, inspect, and prepare the package. Obtain exact human authorization for sends, live publishing, visibility changes, or retirement. Keep Asana read-only.

## Capability graph

```mermaid
flowchart TB
    standards["Editorial, accessibility, and channel standards"] -->|"Set intake and QA checks for"| queue["Publishing queue and calendar"]
    planner["Workback, triage, and dependency planning"] -->|"Sequences work in"| queue
    factowner["Service owner and approved programme facts"] -->|"Control eligibility, dates, and CTA in"| package["Versioned release package"]
    queue -->|"Assigns each item and owner in"| package
    operations["CMS preview, DAM versions, and link/access testing"] -->|"Supply checks on"| package
    package -->|"Supports decision by"| authority["Named release or change approver"]
    package -->|"Carries future handling to"| lifecycle["Refresh, reuse, and retirement owners"]
```

**Know-how.** Coordinate channel packaging from one controlling facts record. In a series keep the episode, shared series copy, YouTube title/description and playlist path, web embed, and social versions independently identifiable. Define their intended recipient use. Track embargoes, access, effective dates, assets and versions, linked destinations, review windows, and expiry. Capture authorization for each affected use. Use actual tool access for queue review, content-management preview, asset version and rights checks, and rollback planning.

## Execution graph

```mermaid
flowchart TB
    request["Approved goal, task, or change request"] -->|"Starts"| plan["Scope variants, owners, deadlines, and dependencies"]
    plan -->|"Assigns preparation to"| gather["Collect CNT-S drafts and exact assets"]
    gather -->|"Reconciles facts, rights, and destinations at"| check{"Ready for the intended use?"}
    check -->|"Gate held"| branch["Name owner and check for held items and independent work"]
    check -->|"Ready for scoped decision"| pack["Return approval-ready release package"]
    branch -->|"Sends cleared tasks to"| gather
    branch -->|"Reports blocked outputs to"| receiver["Named reviewer, publisher, or requester"]
    pack -->|"Requests exact approval from"| receiver
    receiver -->|"When approved and delivered, confirms"| receipt["Recipient access, receipt, and applicable live checks"]
    receipt -->|"Schedules"| revisit["Review, refresh, or retirement"]
```

**Receiving check.** The package distinguishes draft and final uses, links the exact page preview and asset, names each destination, and records what is authorized and what must wait. If a version is replaced, identify affected variants and recipient copies. Retest impacted links, redirects, playback, captions and accessibility, according to the changed object. Verify access and receipt separately once the authorized handoff occurs.

## Learning loop

```mermaid
flowchart TB
    observation["Late rework, broken links, or incorrect versions"] -->|"Is traced to"| cause["Upstream source, handoff, or version dependency"]
    cause -->|"Justifies a scoped trial of"| gate["Intake field, release check, or owner change"]
    gate -->|"Is exercised on"| next["Next suitable release"]
    next -->|"Measures rework and task completion for"| gate
```

**Example.** If multiple releases carry outdated registration dates because each channel copies the previous text, add a controlling date source and effective period to the package. Test on the next release with both a catalogue or registration path and a video description. Compare the number of late corrections and whether the intended person can act.

## Agent assignment

| Field | What to supply or return |
| --- | --- |
| Trigger | A release, series cadence, cross-channel package, lifecycle cleanup, or content change spanning several deliverables. |
| Minimum inputs | Current approved goal, controlling facts and owners, expected channels and dates, asset versions and rights scope, approvals, dependencies, named receiver. |
| Authorized work | Read authorized sources and public destinations, prepare workback and checklist, reconcile variants, use read-only preview or diagnostics when available, stage draft material only as explicitly scoped. |
| Route or hold | Conflicts go to the specific decision owner. Isolate unapproved changes, expired rights, insufficient access or failing destinations. Recipient-required final use waits for authorized final delivery and confirmed receipt. Continue cleared work by owner. |
| Return and accept | Return a package covering status and next action per output, exact version, recipient, gate, evidence and future owner. The named receiver can find the controlling artifact and understand which action they can take next. |

## Evidence

- **Job evidence.** The LCBO Manager, Digital Publishing role covers the queue, lifecycle, escalation, and preproduction/live QA across multiple surfaces. The Edmonton Public Library posting mirror describes web and intranet publishing, retirement, redirects, accessibility, usability, and acceptance testing. [LCBO](https://lcbo.wd3.myworkdayjobs.com/en-US/LCBOCareerSite/job/Manager--Digital-Publishing_JR26-29240) · [Edmonton Public Library employer-text mirror](https://muniserv.ca/jobs/epl-digital-communications-specialist-marketing-and-communications-division-bq797)
- **Calgary Public Library evidence.** LitCon and Family Reading Pick provide public examples of programme and resource destinations. The March 2025 Board packet reports dated performance for a constituent stop-motion video. These sources support separate asset, channel, service, and outcome records. The routing and lifecycle workflow are proposed practice. [LitCon](https://www.calgarylibrary.ca/events-and-programs/events/litcon) · [Family Reading Pick](https://www.calgarylibrary.ca/connect/family-reading-pick) · [March 2025 Board packet](https://www.calgarylibrary.ca/assets/2025-03-19-Board-meeting-materials.pdf)
