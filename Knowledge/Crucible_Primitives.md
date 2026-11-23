# Crucible Atomic Primitive Registry

> Canonical machine-validated source: [Crucible_Primitives.json](Crucible_Primitives.json)

This registry distills the reusable mechanisms across `A01`–`A10`, the live Crucible harness, the 9 surviving high-signal repositories (`10-shadows`, `ten-shadows-control`, `espada`, `Outer-Sanctum`, `Hidden-Booder-Village`, `the-writers-room`, `Story-House`, `Video-House`, `mercury`), and selective CPL skill extractions (`mugen`) into **13 irreducible primitives** across **6 families**.

## Primitive Families & Live Status

| ID | Primitive | Family | Status | Primary Sources |
| --- | --- | --- | --- | --- |
| `PRIM-01` | Ground-Truth Intake Gate | `intake-grounding` | `WIRED_HERE` | `crucible_gate.py`, `mode-reframe`, `the-writers-room`, `Story-House` |
| `PRIM-02` | Scoped Commission & DAG Dependency Contract | `intake-grounding` | `EXTERNAL_PROVEN` | `the-writers-room` (`contracts.py`), `A02`, `A10`, `IDEAS.md` |
| `PRIM-03` | Canon vs. Inference Epistemic Stratification | `state-provenance` | `EXTERNAL_PROVEN` | `A01`, `K-ARCH-01`, `Hidden-Booder-Village` (`ReMe.py`) |
| `PRIM-04` | Append-Once Operation Identity & Prerequisite Resume | `state-provenance` | `EXTERNAL_PROVEN` | `A01`, `A09`, `K-ARCH-01` |
| `PRIM-05` | Dual-Hash Media & Artifact Custody Receipt | `state-provenance` | `EXTERNAL_PROVEN` | `Video-House` (`card_custody.py`, `checksum_verifier.py`), `A07`, `K-STORY-01` |
| `PRIM-06` | In-RAM Capability Routing & Selective Abstention | `routing-retrieval` | `WIRED_HERE` | `crucible_index.py`, `A05`, `A06`, `sidecar@3c1f52b`, `K-ARCH-02`, `K-SIDECAR-01` |
| `PRIM-07` | Deterministic Repo Sieve (No-Clone Ore Triage) | `routing-retrieval` | `WIRED_HERE` | `crucible_index.py`, `crucible_gate.py` (`melt-diff`, `melt-scan`) |
| `PRIM-08` | AST Code Property Graph & Reachability Audit | `verification-gating` | `EXTERNAL_PROVEN` | `espada` (`cpg.py`, `check_reachable.py`), `10-shadows` |
| `PRIM-09` | Mechanical Test Quality & Deceptive-Fix Gate | `verification-gating` | `WIRED_HERE` | `test_quality_gate.py`, `hook_v4.py`, `espada` (`deceptive.py`, `differential.py`) |
| `PRIM-10` | Schema-Bound A/V Script & Structural Deconstructor | `media-editorial-craft` | `EXTERNAL_PROVEN` | `Story-House` (`av_script.py`), `Video-House` (`av_script_builder.py`, `deconstructor.py`), `Outer-Sanctum`, `A07` |
| `PRIM-11` | Multi-Perspective Synthesis & Claim-Bound Objection | `handoff-receiving` | `EXTERNAL_PROVEN` | `A01`, `A08`, `A10`, `Outer-Sanctum` (`evidence-gate`), `ten-shadows-control@ce2915f` |
| `PRIM-12` | Exact-Version Receiving Check & 7-Graph View | `handoff-receiving` | `WIRED_HERE` | `K-WOS-01..03`, `K-GRAPH-01`, `K-ARCH-03`, `the-writers-room`, `mercury` |
| `PRIM-13` | Brand-Locked Institutional Artifact & Stakeholder Risk Audit | `handoff-receiving` | `PROTOTYPE` | `mugen@7d57ee0` (`cpl_call_sheet_generator`, `cpl_document_builder`, `cpl_executive_artifact_compiler`, `cpl_stakeholder_diplomat`), `crucible_gate.py` |

## How Composition Works
1. **Route a primitive directly:** `python ".agents/scripts/crucible_gate.py" route PRIM-02`
2. **Validate registry integrity:** `python ".agents/scripts/crucible_gate.py" doctor`
3. **Rule of reduction:** A new repository is only melted into `Crucible_Primitives.json` if it contributes a *new* irreducible primitive or upgrades an existing primitive from `PROTOTYPE` / `EXTERNAL_PROVEN` to `WIRED_HERE`.
