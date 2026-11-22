# IG-TRAIN-001 · Inner Gravity qualification

## What was tested

- **Packaged code.** Extracted 0.1.0 and 0.1.1. Ran each package's actual lifecycle script against six groups of inputs. Both passed: a path with spaces, concurrent Stop events, absent/bad artifact paths, malformed input, omission of private prompt/path/error text, and an observation destination collision.
- **Worker behavior.** Four fresh Codex workers handled seven cases each. Two used their ordinary setup and two manually loaded the 0.1.0 rule and relevant skill text. Using the written case rubric, both groups scored **14 of 14**. The capacity, resume, version scope, rollout evaluation, graph semantics, and routine cases were synthetic. Case B was a real read-only retrieval from Drive. All four correctly held claims about the Windows Antigravity environment.
- **Actual file inspection.** Both ordinary and instructed workers read and hashed the destination in two local recovery fixtures. One destination still held V2. The other held the expected V3 but had no reviewer acknowledgment. Both groups held review appropriately and avoided recommending a duplicate copy when V3 arrived.
- **Evidence boundary.** Workers each handled a batch of assignments in one context. The reads and filesystem operations occurred in Codex, and an exact model checkpoint was unavailable. These cases establish no improvement in end-to-end judgment, time, or cost. No native plugin discovery, installed verifier, Windows hook dispatch, or actual cross-host reviewer receipt was observed.

## What changed

Version 0.1.1 bundles a read-only comparison in the reconcile skill. It checks the expected SHA-256 against the file at the actual receiving path and reports `match`, `mismatch`, `missing`, or `unreadable`. Artifact presence or a passing digest leaves any human receipt or approval requirement explicit.

From the extracted 0.1.1 archive, eight check cases passed. The tool correctly classified stale V2, recovered V3, a missing path, and a directory destination. It rejected parent traversal, a Windows absolute path, an invalid digest, and a symlink resolving outside the workspace. The tool provides consistent byte-level evidence for this operation. The behavioral benefit over an experienced worker remains unestablished.

## Rank and next gate

**Demonstrated rank: East Blue, with exercised recovery mechanics.** The tested configuration now contains executable destination verification and the observed outcomes are reproducible in a local fixture. The candidate earns Grand Line when a fresh Windows Antigravity session discovers the plugin, invokes the check from a normal assignment, records its lifecycle events, and passes the exact-version receiving gate on repeatable tasks. Outcome benefit needs a comparison against native baseline on cases where the existing setup can actually miss.

The execution environment used here is Linux. The Windows Crucible workspace and Antigravity executable were unavailable through the current session's tools. Qualification on the actual host remains open.

## 0.1.1 receiving check observed in use

Two workers given the 0.1.1 package operated the bundled check against the real local fixture files. At the stale destination it emitted `mismatch`, and the worker held final review and routed the known repair to the authorized owner. At the recovered destination it emitted `match`, and the worker skipped replay while keeping final review held for receiver access. An independent file-only Codex reviewer corroborated the recovered destination and the missing receipt. This reviewer was a separate Codex worker. Native Antigravity subagent loading was outside this run.

| Record | SHA-256 |
| --- | --- |
| Tested 0.1.0 archive | `e721f8fc53d5d82fadd68c92849d03921e4d962e6bbb6b437243e441325db45c` |
| Tested 0.1.1 archive | `5f6b4708177d7f4a51e13d9e4fc7c8b0900636f83e93baeb37ea6cafe1281e00` |
| Expected and recovered V3 | `3c209179905bca41c070ed3bb0d7bbef63f0b46441a78c362d1b353ed19eb1f8` |
| Stale V2 at the receiving path | `d000f7961eea1a3eb06ab6715fc38e352d363a688e51dd8344e10bc6b2bebf64` |
