# Universal Production Blueprint (v2) — Visual Architecture & Plain-Language Guide

> **Purpose:** Supplementary Mermaid diagrams and plain-language component reference paired with the **Canva System Architecture Deck** so any speaker, producer, strategist, or collaborator — with zero software or testing background — can see how the entire system works, how its parts connect, and how to validate it before writing new code.
>
> **Canva Deck Link:** [The Universal Production Blueprint (Canva Deck)](https://canva.link/adetkcchtplz5zf) (`design_id`: `DAHbn2Fm68s`)  
> **LLM Instruction Spec (YAML):** [system_blueprint_v2.yaml](./system_blueprint_v2.yaml)  
> **Home:** `Crucible Domain / Project / Inner Gravity`  
> **Status:** Pre-build visual validation artifact (`Mode 4` — no kernel code written until this map is validated).

---

## 1. The Core Problem in Plain English

Every team that mixes human creativity with AI hits the same wall:
- **Move too fast without guardrails:** Rough drafts, AI suggestions, and last-minute edits leak straight into live work — causing wrong versions, missing captions, unverified facts, or broken public links.
- **Add too many approvals:** Every brainstorm and draft stalls waiting for sign-off — creativity dies, and the leader turns into a full-time traffic cop.

**The solution is not choosing between speed and safety.** It is separating **where you explore** from **what touches the real world**, with one narrow, reliable check-in door between them.

---

## 2. Diagram 1 — The Two-Room Architecture (How Speed and Safety Coexist)

```mermaid
flowchart LR
    subgraph ROOM1["ROOM 1 · THE CREATIVE SANDBOX (Full Speed · Zero Risk)"]
        direction TB
        EXPLORE["Explore, Branch & Remix Freely\n(Humans + AI + Reusable Craft Playbooks)"]
        DRAFT["Rough Placeholders Allowed\n(Missing footage or unconfirmed facts stay clearly marked\nso creative work never stalls)"]
        EXPLORE --- DRAFT
    end

    subgraph DOOR["THE VERIFICATION DOOR (4 Simple Checks)"]
        direction TB
        C1["1. Version Match\nBuilt on the latest approved cut & facts?"]
        C2["2. Fact vs. Placeholder Check\nAre all required facts confirmed?"]
        C3["3. Independent Second Pair of Eyes\nDid someone who didn't draft it check for blind spots?"]
        C4["4. Exact Human Permission\nDid the right owner approve THIS version for THIS use?"]
        C1 --> C2 --> C3 --> C4
    end

    subgraph ROOM2["ROOM 2 · THE REAL WORLD (Trusted Live Releases)"]
        direction TB
        LIVE["Published Work & Live Operations\n(YouTube, Social Feeds, Public Web Pages, Live Events)"]
        LEARN["Real Audience Feedback\n(What worked, what caused friction, what to improve next)"]
        LIVE --> LEARN
    end

    ROOM1 -->|"Ready-to-check package"| C1
    DOOR -->|"If something is missing or outdated:\nHold ONLY the affected piece and route it back"| ROOM1
    C4 -->|"Approved handoff / publish"| LIVE
    LEARN -->|"Feeds verified lessons into the next cycle"| ROOM1
```

**Why this works for non-technical teams:**
- Inside **Room 1 (The Creative Sandbox)**, you and AI can generate 5 competing concepts, remix scripts, and test angles at 100 mph — because nothing in Room 1 can accidentally publish, overwrite a live page, or email a partner.
- Nothing enters **Room 2 (The Real World)** just because an AI or a checklist says "Done." It has to pass the **4 checks at the Verification Door**.

---

## 3. Diagram 2 — One Blueprint, Multiple Gears (How Any Domain Plugs In)

The underlying engine never changes. Instead of building a brand-new system for every kind of work, you swap the **Domain Gear** (the specific playbooks, checks, and human decision-makers for that field):

```mermaid
flowchart TB
    subgraph CORE["THE UNIVERSAL BLUEPRINT (Never Changes)"]
        M["1. Shared Memory\n(One trusted library of current facts, versions & past lessons)"]
        R["2. Smart Router\n(Assigns the right lead based on what is blocking progress)"]
        D["3. Verification Door\n(Version Match · Fact Check · Second Eyes · Exact Permission)"]
        L["4. Learning Loop\n(Turns real-world misses into sharper playbooks)"]
        M --> R --> D --> L --> M
    end

    GEAR["Swap the Domain Gear\n(No need to rebuild the system)"]
    CORE ===|"Powers"| GEAR

    GEAR --> G1["Gear 1 · Video Production\n(Brief -> Script -> Shoot -> Edit -> Captions -> Release)"]
    GEAR --> G2["Gear 2 · Marketing & Social Campaigns\n(Audience -> Channel Variants -> Launch Order -> Results)"]
    GEAR --> G3["Gear 3 · Live & Hybrid Events\n(Run of Show -> Rehearsal -> Backup Plan -> Separate Replay)"]
    GEAR --> G4["Gear 4 · Software & Executive Strategy\n(Specs -> Builds / Option Briefs -> Reviews -> Decisions)"]
```

---

## 4. Diagram 3 — Real-World Walkthrough: What Happens When One Piece Changes?

Imagine a **Video + Social Campaign** is almost ready to launch, and a producer trims **4 seconds** from the master video cut:

```mermaid
flowchart TD
    CUT["Master Video Cut Updated (V2 -> V3)"] -->|"Automatically flags coupled pieces"| CAP["Captions File\n(NEEDS REFRESH — timing shifted)"]
    CUT -->|"Automatically flags coupled pieces"| SOC["Social Cutdowns\n(NEEDS REFRESH — clip lengths shifted)"]
    CUT -.->|"Does NOT touch unrelated pieces"| WEB["Approved Website Copy\n(STAYS READY — no rework wasted)"]

    CAP -->|"Refreshed & checked"| GATE{"Verification Door\nAll required pieces on V3\n+ Human Public Approval?"}
    SOC -->|"Refreshed & checked"| GATE
    WEB -->|"Already valid"| GATE

    GATE -->|"No (e.g., only approved for internal preview)"| HOLD["Hold Public Launch Only\n(Independent prep keeps moving)"]
    GATE -->|"Yes (V3 verified + Public Release approved)"| PUB["Authorized Public Launch\n(YouTube, Social, Web)"]
```

**The studio payoff:**
- You never redo unaffected work (the approved website copy stays green).
- You never accidentally publish old captions on a new cut.
- A partner clicking an **internal preview link** can never be mistaken for **permission to publish to the public**.

---

## 5. Plain-Language Component Map (For Speakers & Collaborators)

| Plain-Language Name | What It Actually Does | What Breaks Without It | Existing Home in Crucible Domain |
| :--- | :--- | :--- | :--- |
| **Shared Memory** | Keeps one trusted home for current facts, exact versions, and lessons from past projects (including what *didn't* help). | Teams argue over which file is "final" and repeat last month's mistakes. | `README.md`, `Project_Register.md`, `Knowledge_Register.md`, `Repository Archaeology/` |
| **Smart Router** | Looks at a new request and puts the right lead in charge — Marketing leads when the audience/destination is unclear; Production leads when crew/edit capacity is the bottleneck. | Projects start shooting videos when the real problem was a broken webpage. | `Project/Work Operating System/`, `Knowledge/Media Agency/Media_Work_Routing.md` |
| **Creative Sandbox** | Safe workspace where humans and AI brainstorm, branch, remix, and draft freely with zero risk of touching live public channels. | Either people move too slowly out of fear, or rough drafts leak into public channels. | Isolated workspaces / draft folders / speculative sessions |
| **Reusable Craft Playbooks** | 55 ready-to-use step-by-step procedures (briefs, A/V scripts, call sheets, social variants, live run-of-show, caption checks) that can be mixed and matched on demand. | Every new project starts from a blank page and forgets key steps. | `Knowledge/Media Agency/Skills and Workflows/` + `A01`–`A08` cognitive methods |
| **Verification Door** | The 4-step checkpoint before anything goes live: Version Match, Fact vs. Placeholder Check, Independent Second Eyes, and Exact Human Permission. | Old versions, unconfirmed claims, or missing prerequisites slip quietly into public releases. | `.agents/plugins/inner-gravity/` (`check_artifact.py`, `ig-evidence-review`, `hook_v4.py`) |
| **Human Keys (Authority)** | Keeps real-world commitments — camera capture, talent consent, budget, policy calls, and hitting "Publish" — strictly in human hands. | AI oversteps authority or treats a draft review as permission to launch. | Scoped human approval rules across `WOS` and `Media Agency` |
| **Learning Loop** | Captures what actually happened after release (did the audience understand it? did the handoff work?) and upgrades only the playbook steps that measurably improve results. | The system gets bloated with rules that sound smart but don't actually help. | `ig-improve`, `Media_Agency_Verification_Record.md` |

---

## 6. Canva Deck Slide-by-Slide Speaker Guide

1. **Slide 1 — The Universal Production Blueprint:** Introduce the goal — moving at full creative speed with AI while keeping real-world releases trustworthy.
2. **Slide 2 — The Core Problem (Speed vs. Trust):** Contrast the two broken extremes (chaos vs. approval paralysis) that every creative and institutional team knows firsthand.
3. **Slide 3 — The Breakthrough (Two Separate Rooms):** Walk through **Room 1 (Creative Sandbox)**, **The Verification Door**, and **Room 2 (Real World)**.
4. **Slide 4 — Inside the Verification Door (4 Checks):** Explain Version Match, Fact vs. Placeholder, Independent Second Eyes, and Exact Human Permission in plain everyday terms.
5. **Slide 5 — One Blueprint, Multiple Gears:** Show how the exact same system powers Video Production, Marketing & Social Campaigns, Live Events, and Software/Strategy simply by swapping the Domain Gear.
6. **Slide 6 — How the Components Connect:** Trace the closed loop from Shared Memory -> Smart Router -> Reusable Playbooks -> Verification Door -> Human Keys -> Real Feedback.
7. **Slide 7 — Real-World Example (When One Piece Changes):** Walk through the 4-second video trim scenario to show selective refresh without panic or wasted rework.
8. **Slide 8 — Validation Gate (Before We Build Anything Else):** Explain the 3-step viability test — align on this visual map, consolidate to one clean source of truth, and run **one real project** end-to-end.
