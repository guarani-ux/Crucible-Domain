# Inner Gravity 0.1.1

Workspace plugin for Google Antigravity. It brings forward useful methods when a decision is still open, separates evidence from claims of readiness, reconciles interrupted work, and turns observed misses into testable improvements. The three skills are readable outside Antigravity. Each receiving host supplies and verifies its own tool access and authority.

## Load in Crucible Domain

1. Extract the archive. The directory `inner-gravity` must directly contain `plugin.json`, `rules/`, `skills/`, `agents/`, and `hooks.json`.
2. On the workstation, check that `python --version` runs Python 3.8 or newer. Run `agy plugin validate --strict "<extracted-path>/inner-gravity"` if supported by the installed CLI.
3. Place the extracted `inner-gravity` directory in the desktop Crucible Domain workspace at `.agents/plugins/inner-gravity`. If that destination already exists, review the diff before replacing any files. Use the App or IDE for workspace-local discovery. In a fresh session, check that the rule, verifier, skills, and hook group are visible and that an ordinary request can invoke the right skill. Remove or disable this plugin to roll back.
4. Run the cases in `evaluation/ASSIGNMENTS.md` before and after enabling the plugin, using the same source versions, host, model, and permissions. Give workers only their assignment and inputs. An independent reviewer uses `evaluation/REVIEW.md`.

[Plugin format and validation](https://antigravity.google/docs/build-plugins/) · [Workspace plugin discovery](https://antigravity.google/docs/plugins) · [Hook contracts](https://antigravity.google/docs/hooks)

## Verify a receiving copy

Use the supplied read-only comparison when the controlling handoff gives a receiving path and SHA-256. From the plugin root:

    python skills/ig-reconcile/scripts/check_artifact.py "<workspace>" "<relative-receiving-file>" "<expected-sha256>"

The result records byte match, mismatch, missing file, or unreadable destination. A match verifies the observed bytes at that path. The recipient's ability to open the exact artifact and authorization for its next use have their own evidence.

## What runs

| Component | Behavior |
| --- | --- |
| `rules/inner-gravity.md` | Lightweight routing at workspace scope. Routine work stays direct. Consequential work gets an applicable method or verification pass. |
| `skills/ig-discover-method/` | Search current evidence and adjacent professional practice. Apply a method when it changes the decision. |
| `skills/ig-reconcile/` | Recover the controlling revision and reconcile an uncertain effect before replay. Leave a receipt another host can evaluate. |
| `skills/ig-improve/` | Turn a demonstrated result into a candidate change, regression case, review, and rollback. |
| `agents/ig-evidence-review.md` | Independent evidence reviewer with file-reading tools, shell execution off, and MCP inheritance disabled. |
| `hooks.json` and `scripts/observe.py` | Record SessionStart and Stop as separate JSON events in the host-provided artifact directory. Capture lifecycle metadata only. Event delivery and termination establish observations. Completion requires separate evidence. |

The plugin is a workspace addition. Existing Antigravity authority, native permissions, and operator-managed controls govern execution. Keep host traces local. Share only authorized evidence and receipts. The synced workspace carries handoffs and immutable run receipts. A designated project owner reconciles shared current pointers.
