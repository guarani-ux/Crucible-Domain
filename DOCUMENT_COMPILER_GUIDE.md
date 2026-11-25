# Crucible Document Compiler & Verification Guide

> **Works Everywhere:** Antigravity (`agy`), Claude Code (`claude`), OpenAI Codex CLI (`codex`), ChatGPT / Claude.ai / Gemini Web UI (`--mode prompt` + `--from-json`), any custom VM/terminal AI (`CRUCIBLE_AI_CMD`), or air-gapped offline (`--mode offline`).

Crucible Domain compiles **8 institutional & production document types** through a **Bidirectional Sensemaking Graph Compiler** before rendering a single line of Markdown:

```text
Upstream Sensemaking Graph (JSON)
  ├── Reality & Custody (verified domain facts, official 2027-2030 mandates, owned holds)
  ├── Belief-Delta Matrix (>= 3 stakeholder roles: skepticism -> target -> trigger)
  ├── Creative Modality & Intention-to-Outcome Contract (non-formulaic voice/visual strategy)
  └── Form-Native Causal Spine (beats, decision request, signals/hypotheses, shots, schedule)
        │
        ▼  [Deterministic Gate 1: Graph + Flow + 6-Role Board + 3 Root Axes]
Clean 2-Zone Markdown (Stakeholder Body + Isolated Internal Custody & Sources)
        │
        ▼  [Independent Gate 2: Adversarial Judgment Panel (SIGN_OFF >= 0.85)]
Upstream Self-Healing Re-Compile (feeds objections back into the Graph, never surface patches)
```

---

## 1. Quick Start by AI Runtime (Use Any Tool or VM)

| Runtime / Environment | Command | How It Works |
| :--- | :--- | :--- |
| **Antigravity (`agy`)** | `python .agents/scripts/crucible_gate.py bench compile youtube 180 --mode agy_live` | Uses `agy` CLI + Gate 2 adversarial panel + upstream self-healing retry. |
| **Claude Code (`claude`)** | `python .agents/scripts/crucible_gate.py bench compile youtube 180 --mode claude_live` | Invokes `claude -p "<prompt>"` locally and runs full Gate 1 + Gate 2. |
| **OpenAI Codex CLI (`codex`)** | `python .agents/scripts/crucible_gate.py bench compile youtube 180 --mode codex_live` | Invokes `codex exec "<prompt>"` locally and runs full Gate 1 + Gate 2. |
| **Any VM / Terminal / Ollama / Custom CLI** | `CRUCIBLE_AI_CMD="my-ai-cli --stdin" python .agents/scripts/crucible_gate.py bench compile youtube 180 --mode custom_cli` | Pipes the upstream prompt to `stdin` of `CRUCIBLE_AI_CMD` and reads JSON from `stdout`. |
| **ChatGPT / Claude.ai / Gemini Web UI (Zero CLI)** | **Step 1:** `python .agents/scripts/crucible_gate.py bench compile youtube 180 --mode prompt`<br>**Step 2:** Paste prompt into ChatGPT/Web UI, save JSON response to `graph.json`<br>**Step 3:** `python .agents/scripts/crucible_gate.py bench compile youtube 180 --from-json graph.json` | Zero local API keys or CLI required. Prints the exact governed prompt, then validates & compiles your pasted JSON into clean 2-zone Markdown. |
| **Offline / Air-Gapped Baseline** | `python .agents/scripts/crucible_gate.py bench compile youtube 180 --mode offline` | Zero LLM calls. Runs deterministic canonical graph through Gate 1. |

> **Tip:** Add `--json` to any command for full machine-readable output (including the compiled `markdown` field, `graph_validation`, `axes`, and `gate2` report). Add `--no-judge` to skip Gate 2 during fast local iteration.

---

## 2. All 8 Document Types & Copy-Paste Use Cases

Pass `--form <form_id>` to target any of the 8 supported forms:

| Document Type (`--form`) | Best Use Case | Example Command |
| :--- | :--- | :--- |
| **`av_script`** | YouTube 3m mini-doc, 5m deep-dive, 30s IG Reel, 45s LinkedIn cut, 60s FB walkthrough, 15s cutdown | `python .agents/scripts/crucible_gate.py bench compile youtube 180 --form av_script --mode agy_live` |
| **`production_brief`** | Greenlighting a shoot or campaign with Decision Request & Opportunity Cost in top 25% | `python .agents/scripts/crucible_gate.py bench compile youtube 180 --form production_brief --mode claude_live` |
| **`leadership_report`** | CEO / Executive brief with Counterargument Steelman, Resource Commitment & Owned Holds | `python .agents/scripts/crucible_gate.py bench compile youtube 180 --form leadership_report --mode codex_live` |
| **`research_note`** | Evidence-first memo (Observed Signals before Hypotheses, Transfer Limits, Next Falsification Test) | `python .agents/scripts/crucible_gate.py bench compile youtube 180 --form research_note --mode prompt` |
| **`treatment`** | Creative pitch with Premise/Logline in top 35%, Visual/Sound Approach & Availability Holds | `python .agents/scripts/crucible_gate.py bench compile youtube 180 --form treatment --mode offline` |
| **`call_sheet`** | Cold-receiver shoot schedule with Call Times, Location, Crew/Cast Roles & Lab Safety | `python .agents/scripts/crucible_gate.py bench compile youtube 180 --form call_sheet --mode offline` |
| **`shot_list`** | Camera coverage plan with standard framing codes (`WS`, `MS`, `MCU`, `CU`, `ECU`, `OTS`, `B-Roll`) | `python .agents/scripts/crucible_gate.py bench compile youtube 180 --form shot_list --mode offline` |
| **`content_calendar`** | Multi-platform rollout (YouTube, Instagram, LinkedIn, Facebook) with native hooks & CTAs | `python .agents/scripts/crucible_gate.py bench compile youtube 180 --form content_calendar --mode offline` |

---

## 3. End-to-End Workflows & Verification Commands

- **8-Stage Project Pipeline** (runs all 8 forms sequentially with cross-document parity & hold carryover):
  ```sh
  python .agents/scripts/crucible_gate.py bench pipeline --mode offline
  ```
- **Platform & Runtime Matrix Sweep** (tests multiple platforms/lengths in isolated subprocesses):
  ```sh
  pwsh -File scripts/run_workflow_matrix.ps1
  ```
- **Inspect A/B Outcome Ratchet & Promoted Lessons**:
  ```sh
  python .agents/scripts/crucible_gate.py bench inspect
  ```
- **Run Full Unit Test Suite (Zero LLM)**:
  ```sh
  pytest .agents/scripts/tests/test_root_axis_engine.py .agents/scripts/tests/test_doc_flow_engine.py .agents/scripts/tests/test_workload_bench.py -q
  ```

---

## 4. Where the Upstream Rules Live (Edit Here, Never Patch Downstream)

- **Craft Protocols (all 8 forms + platform physics):** [.agents/bench/craft_protocols.yaml](.agents/bench/craft_protocols.yaml)
- **Verified Domain Facts & Forbidden Myths:** [.agents/bench/domain_facts.yaml](.agents/bench/domain_facts.yaml)
- **Organization Charter & Mandates:** [.agents/bench/org_charter.yaml](.agents/bench/org_charter.yaml)
- **Gate 2 Adversarial Rubrics:** [.agents/bench/judgment_rubrics.yaml](.agents/bench/judgment_rubrics.yaml)
- **Compiler Engine:** [.agents/scripts/crucible/sensemaking_compiler.py](.agents/scripts/crucible/sensemaking_compiler.py)
