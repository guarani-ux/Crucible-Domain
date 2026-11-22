# Crucible × CPL: Reconciled Handoff, Pilot & Calendar Maps (`v1.1`)

> **2026-11-22 · Editable Mermaid source · Planning reference, not an approved workflow or dispatch.**  
> Companion YAML: [cpl_handoff_portable.yaml](./cpl_handoff_portable.yaml) · Convergence Spec: [01_convergence_architecture.yaml](./01_convergence_architecture.yaml)  
> Dotted arrows (`-.->`) show evidence or optional inputs; solid arrows (`-->`) show proposed sequence, prerequisite, or transfer. Zero coworker names or internal Asana links appear here. No Asana changes.

---

## 1. Priority Sequence, Content Calendar Feed & What Not to Build

```mermaid
flowchart TD
    Goal["Goal: good work moves without repeated explanation or hidden repair"]
    Audit["SRC-FRAME: team audit of 213 videos and existing Framework"]
    Pitches["SRC-OCT / SRC-NOV: editorial direction, PITCH-NQ & PITCH-YCD"]
    Research["Platform Demographics + Lean Craft + Targeted Peer Research"]
    C["PILOT-ELC: test a real next decision on Where Community Begins"]
    Proof{"Receiver used exact material to make or record the decision?"}
    NoProof["Record partial or held; fix only the handoff that failed"]
    Cal["4-Track Evergreen Content & Release Calendar\n(Generated directly from live Task-as-a-System packets)"]
    B["FRAMEWORK-B: evidence-led Phase Two contribution + Content Calendar"]
    Repeat["Repeat on a materially different real assignment when authorized"]
    Park["Park 30d: new repo, blanket cleanup, all 55 playbooks, abstract frameworks"]

    Goal -->|"Directs first live slice"| C
    Audit -.->|"Supplies 213-video baseline"| C
    Research -.->|"Grounds platform & craft choices in"| Cal
    Pitches -.->|"Feeds evergreen series slots into"| Cal
    C -->|"Feeds live gate state into"| Cal
    C --> Proof
    Proof -->|"Missing proof or receiving failure"| NoProof
    NoProof -->|"Recheck once blocker clears"| C
    Proof -->|"Observed receiving use"| B
    Cal -->|"Supplies live cadence & expiry view to"| B
    Proof -->|"Carry same acceptance check"| Repeat
    Goal -.->|"Not prerequisites"| Park
```

---

## 2. Strategy, Work & Strength of Evidence

```mermaid
flowchart LR
    Old["2023-26: Everyone Belongs at the Library"] --> Dev["Next plan underway by June 2025; outline Nov 2025"]
    Dev --> Launch["Oct 27, 2026: public launch; transition until 2027"]
    Launch --> New["2027-30: Collections, Experiences, Expertise, Spaces, Technology"]

    Page["CASE-PAGE: credited sound mix; Freedom to Read & classroom use"]
    Pow["CASE-POW: research, filming, 3 verticals & YouTube; educator use"]
    Read["CASE-READ: Family Reading Pick; Production & Digital handoff"]
    DITL["CASE-DITL: Indigenous Services story; careers-page reuse"]
    Framework["SRC-FRAME: inventory delivered; Phase Two adoption unknown"]
    LaunchRole["CASE-LAUNCH: brainstorm exists; export/release owned by others"]
    ELC["PILOT-ELC: transition concept & proposed live handoff, not release"]
    Proposals["SRC-OCT / SRC-NOV: Grow, Books & Reading, Community (proposed lenses)"]

    Old -.->|"Intellectual freedom / learning"| Page
    Old -.->|"Belonging & learning"| Pow
    New -.->|"Reading & Collections"| Read
    New -.->|"Expertise, Spaces & reconciliation"| DITL
    Dev -.->|"Explicit alignment in team plan"| Framework
    Launch -.->|"Institutional work != sole ownership"| LaunchRole
    Launch -.->|"Work in transition"| ELC
    New -.->|"Translated into proposed lenses"| Proposals
```

---

## 3. Who Sets & Clears Each Observed Gate (`G01`–`G06`)

*Recovered from sampled records — not a formal CPL policy or mandatory serial checklist. Development receipt never grants release permission.*

```mermaid
flowchart TD
    ScopeOwner["Request owner or scope lead"] -->|"At intake or scope change"| G01["G01 Scope: outcome, audience & use stated"]
    Coordinator["Production coordinator + input owners"] -->|"Before dependent work"| G02["G02 Readiness: brief, inputs, access or confirmed booking"]
    ProdReviewer["Named production reviewer"] -->|"On exact cut version"| G03["G03 Production: decision, version & conditions"]
    Stakeholder["Named stakeholder / decision owner"] -->|"When brief/decision requires"| G04["G04 Stakeholder: response, scope & any hold"]
    ReceiverRole["Sender + named receiving colleague"] -->|"Before dependent use"| G05["G05 Handoff: receiver opens & acts on exact version"]
    Authorizer["Explicitly authorized release owner"] -->|"At controlling release decision"| G06["G06 Release: exact asset, destination & conditions"]

    G01 --> G02 --> Make["Maker delivers named artifact + creative/economy options"]
    Make -->|"Where applicable"| G03
    Make -->|"Where applicable; may run in parallel"| G04
    Make -->|"Supplies development packet with honest status"| G05
    G03 --> G06
    G04 --> G06
    G06 -->|"Only when cleared & authorized"| Publish["Channel publisher executes named placement"]
    G06 -->|"Unknown or held"| Hold["No release; independent work continues"]
```

---

## 4. `PILOT-ELC` (*Where Community Begins*): First Live Receiving Test

*Reconciled fix: Participant `C` is the **Authorized local assistant / coordinator** (not blocked on unverified remote runtime routing).*

```mermaid
sequenceDiagram
    participant L as Levi / Scope Owner
    participant C as Authorized Local Assistant / Coordinator
    participant R as Named Receiving Colleague
    participant D as Applicable Reviewer / Decision Owner
    Note over L,D: Proposed PILOT-ELC only. No outreach, booking, or publication authorized by this map.
    L->>C: Ordinary request + authoritative ELC context
    C->>C: ELC-01 / G01-G02: verify governing concept, need, exact receiver & permitted route
    alt Required authority, source, or receiver missing
        C-->>L: Report exact blocker, what closes it, and independent work still open
    else Current records & authority confirmed
        C->>C: ELC-02: assemble one versioned packet (creative/economy options + exact status)
        opt Review required for intended development use
            C->>D: ELC-03 / G03-G04: request scoped decision through normal process
            D-->>C: Record exact decision, conditions, or hold (no inferred clearance)
        end
        C->>R: ELC-04 / G05: share only within existing permitted handoff
        alt Receiver acts without separate reconstruction
            R-->>C: Record actual next decision & artifact version used
            C-->>L: ELC-05: return receiving proof + separated effort/intervention log
        else Receiver needs clarification or cannot act
            R-->>C: Identify missing input or explanation needed
            C-->>L: ELC-05: record partial/held; zero claim of release
        end
    end
```

---

## 5. `CHG-01` Mechanical Check: What a Changed Cut Must and Must Not Stop

```mermaid
flowchart LR
    A["Gate A: verify actual brief, source bytes, access & people"] -->|"Permitted inputs"| V2["CHG-01: CUT-01 v2 trim changes timing"]
    V1["CUT-01 v1: approval bound to v1 & named destination"] -->|"Never transfer to v2"| B{"Gate B: exact version, scope & evidence match?"}
    V2 -->|"Requires v2 approval & receipt"| B
    B -->|"Missing, stale, or out of scope"| Held["Hold v2 dependent acceptance/release; preserve v1 receipt"]
    Held -->|"Recheck timing-dependent assets only"| Rev["Refresh captions & social excerpts affected by timing"]
    Rev -->|"Return verified v2 receipts"| B
    B -->|"Matches & authority present"| OK["Permit only authorized downstream action"]
    V2 -.->|"Does not invalidate unchanged assets"| Still["Cleared still retains valid receipt"]
    Held -.->|"Does not block independent lanes"| Work["Unrelated editorial work continues"]
```
