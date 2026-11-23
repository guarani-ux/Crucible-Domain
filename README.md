# Crucible Domain

Crucible Domain is the starting point for finding what we are working on, what we have already tried, and what we can carry forward. It connects projects, GitHub repositories, conversations, skills, graphs, and evidence so people and agents can resume work without reconstructing its history from scratch.

## Start here

- **What exists and what is underway?** Open the [Project Register](Project/Project_Register.md) *([Drive](https://drive.google.com/file/d/1hejOpxES0oMfwcZHxAgxb7cvvnUcLm3i/view?usp=drivesdk))*. It distinguishes reviewed projects, conversation leads, and repositories that still need inspection.
- **What did we learn or get wrong?** Open the [Knowledge Register](Knowledge/Knowledge_Register.md) *([Drive](https://drive.google.com/file/d/1XwzOf6ifYPTq0NDlnU9luciRQMPkjxH-/view?usp=drivesdk))*. It links findings, failures, and tested practices to evidence and shows when they apply.
- **How do we prove changes work instead of writing "made-to-pass" tests?** Open [Testing Philosophy](Knowledge/Testing_Philosophy.md) (`K-TEST-01` — 4 Evidence Rungs, 3 Test Laws, Red-First & Rung-3 planted-defect evals).
- **What can we recover from past builds?** Open [Repository Archaeology](Knowledge/Repository%20Archaeology/00-Exhibit_Index.md) *([Drive](https://drive.google.com/file/d/1864tO3qjxuC0Adv0I9s2JHQaQw_eiSDs/view?usp=drivesdk))* for ten historical system exhibits, their graph sets, and a cross-system synthesis. Treat proposed reuse as a lead until a receiving project exercises it.
- **Which media procedure or role applies?** Open [Media Agency skills and workflows](Knowledge/Media%20Agency/Skills%20and%20Workflows/README.md) (55 numbered procedures) or [Media work routing](Knowledge/Media%20Agency/Media_Work_Routing.md).
- **How does this connect?** Keep a project graph with its project. Use [Graphs](Graphs) *([Drive](https://drive.google.com/drive/folders/1h02pFvfRZbjk796qQp9-7O7_kvZiA_kL))* for views spanning projects or domains. Link the same project and knowledge IDs across views.
- **Where does the current work live?** Follow the register to the controlling artifact. Use [Calgary Public Library](Calgary%20Public%20Library) *([Drive](https://drive.google.com/drive/folders/1MfKl4RU-9fPmyKPmwMk_8zoxd8OD9qbw))* for authorized Library project material, [Personal Work](Personal%20Work) *([Drive](https://drive.google.com/drive/folders/125LCIJs0LtkvL9-Aitqa9BC32moPTY71))* for personal work, and [Project](Project) *([Drive](https://drive.google.com/drive/folders/1OjT4JloI0IaYmzgnQDgJQ_7lDOtRC6eE))* for shared systems such as the [Work Operating System](Project/Work%20Operating%20System/README.md) *([Drive](https://drive.google.com/drive/folders/1Wa4YCSoXhpfuv01dfgVysKEg-g_bP6ZT))* and [Inner Gravity](Project/Inner%20Gravity/README.md).
- **Route a capability or check workspace health in local RAM:** Run `python ".agents/scripts/crucible_gate.py" route "<task or ID>"` or `python ".agents/scripts/crucible_gate.py" doctor`.

## Rule for representing work

This rule applies to Media Agency and every Crucible project. Represent work so that a person, an LLM, or a program can find the right knowledge, understand the relationships, and act within scope. At the normal entry point, make it easy to find the purpose, what to open or do next, the expected result, and who checks it.

| Use | When it helps | What to capture |
| --- | --- | --- |
| **Markdown** | A person or model needs instructions, domain knowledge, examples or judgment. | Use stable headings and task-level entry points. Put the trigger, inputs, expected result and receiving check first. Explain decisions, exceptions, and examples where they change execution. |
| **Editable graphs** | Relationships change the next action, such as dependencies, division of responsibility, branches, handoffs, version effects or feedback. | Use Mermaid by default. Link graph nodes to the records they represent. Label edges by meaning, such as requires, informs, produces, approves, supersedes or verifies. Mark whether a path is proposed, observed or unverified. |
| **Structured data** | A tool needs to retrieve, join, validate, dispatch, replay or verify records consistently. | Use the project's existing schema or interface. YAML or JSON suits small validated records. CSV suits flat tabular exchange. An existing database or API may be the controlling source for live state. Choose the format for the operation and validate it with the actual consumer. |

Combine these formats where each does useful work. A prose procedure can explain a branch while a graph shows its effect on a handoff. A structured record can carry the exact IDs and status for a worker to retrieve. Keep one controlling record per fact or decision and link views to it. Generate views from shared records where the project supports it.

### Define the units of work

| Unit | Minimum useful definition |
| --- | --- |
| **Role and responsibility** | Purpose, scope, recurring responsibilities, decisions this role owns or recommends, who contributes, who receives its work, and the capabilities it requires. Name the actual decision owner on each project. |
| **Skill or technique** | Trigger, prerequisites and source inputs, steps, domain judgment, tool operations and alternatives, exact output, example or template where useful, and an observable check. Make the procedure itself reachable from the role or task. |
| **Workflow** | Trigger, outcome, stages and owners, linked skills, hard prerequisites and independent work, branches and holds, exact handoffs, and who verifies the result. |
| **Task or assignment** | One scoped result, current inputs and versions, linked role and procedure, owner, due date when relevant, required tools and permissions, recipient, and the evidence that makes it complete. |
| **Agent or runtime** | What the worker can actually reach and do in that environment, under which permission, and what was tested. A role assignment requires a separate check of tool access and authority. |
| **Output or evidence** | Exact version, intended recipient and use, source or decision basis, access and receiving check, and what was actually observed. Link revisions and identify affected consumers. |

### Keep internal records and receiving outputs fit for use

Use internal graphs, Markdown and structured records to guide the work. Deliver in the form the recipient can use. For example, a Media Agency assignment can use a dependency graph, an A/V writing procedure and a structured revision record. The producer receives the editable **Section | Audio | Video** script and the specific decision it needs. A project reviewer may need a one-page brief, a crew may need a call sheet, and a downstream tool may need validated data. Preserve the connection to the exact output and approval scope.

**Check before relying on a new or changed route.** Start from the ordinary project entry point. Follow it to the relevant role, executable procedure and inputs, then check that the intended worker can produce the specified output for its receiver. For a consequential branch, vary one relevant condition and check what can proceed, what waits and who decides. Record what was checked and where access, authority or execution remains unverified.

## How material enters and improves the hub

1. **Discover.** Look across GitHub, Drive, Library, conversations, and other authorized sources. Record what was checked, where access stops, and where to continue. A name match starts a lead. A repository is a source artifact. A top-level project has its own purpose, scope, and decision history.
2. **Reconcile.** Find the canonical source and check whether the material already represents a registered project, component, or lesson. Preserve aliases and source links. Treat repository presence, project activity, and verified results as separate claims.
3. **Extract.** Record a project when it has a distinct purpose or commitment. Preserve knowledge when it helps someone make a better decision, avoid a repeat failure, recover a tested method, or understand meaningful progress. Include the source and conditions that give the claim its meaning.
4. **Connect.** Link the project, its relevant lessons, original sources, and graph views using stable IDs. Keep code in GitHub and restricted source material in its authorized system. Use approved summaries or reference links in the hub. Keep Asana read-only.
5. **Reuse and revise.** Start an assignment by checking for relevant prior work. When a method is applied, record what happened and what it changes. Update status when evidence changes and preserve the superseded record or its source.

Anyone working with authorized access can use this process. The first intake is a dated starting point. Its coverage table records which sources were reviewed and which still need inspection.
