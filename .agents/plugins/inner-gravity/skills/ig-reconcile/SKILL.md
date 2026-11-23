---
name: ig-reconcile
description: Recover the controlling version and next permitted action when resuming work, changing hosts, or encountering conflicting synced records or uncertain effects.
---

1. Read the current handoff and resolve its exact controlling input and revision at the source. Inspect the actual receiving environment for claims about local files, permissions, or runtime. Use the synced folder as a record exchange.
2. Compare versions and scope. If they conflict, preserve both candidates and identify what can resolve the conflict. A newest timestamp or successful sync alone cannot settle authority.
3. For an operation already attempted, check its effect through an authoritative readback before replay. For a file with an expected hash, run [check_artifact.py](scripts/check_artifact.py) with the workspace, relative receiving path, and hash from the controlling record. Preserve its result as evidence of the observed bytes. A match leaves any receiver-access requirement open until checked. Keep dependents held while the effect or prerequisite is unresolved. Continue independent authorized work. Record the last verified completion and the next permitted action.
4. Return a receipt with operation and attempt IDs, host, controlling inputs and versions, outcome and exact evidence, next action and owner. For a consequential handoff, record receiver access and receipt separately. Use a new uniquely named record when publishing is in scope. A designated owner updates shared current pointers after checking the starting revision.
