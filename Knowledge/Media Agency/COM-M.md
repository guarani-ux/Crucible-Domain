# COM-M — Communications Manager

Use this role to turn a confirmed message direction or inbound issue into coordinated work. Set priority, owners, versions, review windows, launch order and escalation paths. Agents can triage, draft workbacks and reconcile read-only evidence for the accountable manager.

**Carry out the assignment.** Open the relevant procedure and make the named artifact. [Communications and design practice](https://drive.google.com/file/d/1o3U1Yv1q7qrmFK1BjQnIykB13oictIe_/view?usp=drivesdk) (CD-01–04/08) · [Project and portfolio operations](https://drive.google.com/file/d/119wQhEWZhZfUynSX2IxUv_PJOcZsRbdF/view?usp=drivesdk) (OP-05/07) · [Writing practice](https://drive.google.com/file/d/1CmHfJsHBIZ70s9HDPwDVVq8l1WW86fup/view?usp=drivesdk) (MW-07).

## Capability graph

```mermaid
flowchart TB
    service["Service-owner routes and escalation policy"] -->|"Locate facts and decision scope for"| triage["Issue and priority triage"]
    needs["Staff, media, partner and public dependencies"] -->|"Shape recipient and timing choices in"| workback["Message workback and review routing"]
    method["Intake triage and cross-team sequencing"] -->|"Turn case constraints into"| workback
    monitor["Authorized media and web monitoring"] -->|"Provides questions and change cues to"| triage
    triage -->|"Assigns urgency and required owners in"| workback
    office["Microsoft Office or authorized task view"] -->|"Records assignments and versions in"| workback
    workback -->|"Produces"| package["Scoped assignments and receiving checks"]
```

Know how to distinguish a true service or release dependency from a preferred review, and forecast critical review time separately from active effort. Use a source and version register to connect one factual change to staff notes, event pages, newsletter copy, social assets and recipient copies.

## Execution graph

```mermaid
flowchart TB
    intake["Request, deadline or monitoring signal"] -->|"Routes through"| impact{"Facts, audiences or release at risk?"}
    impact -->|"Routine or contained"| assign["Name owner, version, task and reviewer"]
    impact -->|"Material or disputed"| escalate["Send issue brief to COM-D or scope authority"]
    escalate -->|"Returns decision or affected hold to"| assign
    assign -->|"Sends source-linked drafting scope to"| draft["COM-S and relevant production or content owners"]
    draft -->|"Returns exact versions and checks to"| reconcile{"Required reviews and versions aligned?"}
    reconcile -->|"Held version or changed fact"| update["Record affected recipients, rechecks and parallel work"]
    update -->|"Reassigns affected work without blocking independent paths"| assign
    reconcile -->|"Clear for the documented use"| handoff["Human release owner or internal receiver verifies package"]
```

For a time-sensitive announcement, establish earliest external use and the staff notice dependency independently. If a date changes after a provisional copy was issued, list who received which version, how they can access the replacement, and which uses need a final. Keep final-required use held until an authorized final copy is delivered and receipt is confirmed.

## Learning loop

```mermaid
flowchart TB
    cue["Repeated late review or duplicate copy changes"] -->|"Separate active and waiting time in"| diagnose["Identify which handoff caused rework"]
    traces["Exact version history and receipt"] -->|"Shows affected recipients and cause in"| diagnose
    diagnose -->|"If early owner routing is the gap, change"| route["Triage template or review sequence"]
    route -->|"Repeat on a comparable campaign"| test["Check owner turnaround and correction count"]
    test -->|"Qualifies the workflow change for"| diagnose
```

## Agent assignment

| Field | Run instruction |
| --- | --- |
| Trigger | Multiple people, channels or deadlines need message coordination, or a service-change signal needs assignment and prioritization. |
| Minimum inputs | Current direction or open question, deadline for each affected use, exact drafts, audience and channel, source and review owners, capacity and known holds. |
| Permitted actions | Read authorized tasks, drafts and source records. Keep Asana read-only. Draft the workback, owner map, receiving checks and escalation note for the accountable manager. |
| Stop or route | Conflicting facts go to their service owner. Material audience, authority or reputation conflicts go to COM-D or the designated authority. Preserve independent approved work within scope, including template prep and sourcing. |
| Return and acceptance | Return one controlling queue view with task, owner, deadline, dependency, exact version, receiver and check. For a changed version include prior notes, recipient copies and scoped holds. A human reviewer can locate the package and tell who acts next and on what. |

## Evidence

- [Prince George Public Library's manager description](https://www.pgpl.ca/sites/default/files/postings/Manager%20of%20Communications%20and%20Engagement%20Job%20Description.pdf) establishes a comparator for managing official communications, engagement, media liaison and staff workflow, with Office, Adobe and web/social tools listed.
- The [Calgary Public Library Media Centre](https://www.calgarylibrary.ca/about-the-library/media-centre) gives a public media route. The [June 2025 Board packet](https://www.calgarylibrary.ca/assets/2025-06-25-Board-Meeting-Materials-Web.pdf) supplies historical civic engagement context for audience, public education and campaign coordination.
- Workback, approval and receipt handling are proposed for the Work Operating System. Confirm actual team ownership, visible tools and action permissions for each run.
