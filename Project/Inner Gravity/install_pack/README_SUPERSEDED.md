# `install_pack/` Status — Legacy Nov 15/22 Staging Superseded at Repo Root

> **Summary:** The original November 15/22 governance staging artifacts in this folder are **SUPERSEDED — live at repo root** (or live in global `~/.gemini/config`). Do **not** re-apply the legacy files over current root governance. For the current modular package lockfile upgrade, use the **optional v2 operator update** ([`acceptance.lock.json.v2`](./acceptance.lock.json.v2) + [`apply_v2_lock.ps1`](./apply_v2_lock.ps1)).

## 1. Legacy Staging Files (SUPERSEDED — Live at Repo Root)

| Legacy Staged File | Status | Live Canonical Location |
| --- | --- | --- |
| `AGENTS.md.ready` | **SUPERSEDED — live at repo root** | [`AGENTS.md`](../../../AGENTS.md) (`RW-04` protected) |
| `IDEAS.md` | **SUPERSEDED — live at repo root** | [`IDEAS.md`](../../../IDEAS.md) |
| `acceptance.lock.json.ready` | **SUPERSEDED — live at repo root** | [`.agents/acceptance.lock.json`](../../../.agents/acceptance.lock.json) (`RW-04` protected) |
| `crucible_hooks.json.fixed` | **SUPERSEDED — live at repo root** | [`.agents/hooks.json`](../../../.agents/hooks.json) (`RW-04` protected) |
| `hooks.json.normalized` | **SUPERSEDED — live in host config** | `~/.gemini/config/hooks.json` (managed via `antigravity-config`; `RW-04` protected) |
| `apply_protected_fixes.ps1` | **SUPERSEDED (Nov 22 historical installer)** | Kept for audit history; replaced for lockfile updates by [`apply_v2_lock.ps1`](./apply_v2_lock.ps1) |

## 2. Current Optional Operator Update (`acceptance.lock.json` v2)

Because `.agents/acceptance.lock.json` is protected by `hook_v4.py` (`RW-04` / `PROTECTED_FILES`), agents cannot edit it directly. This optional v2 update extends the live lockfile with `Graphs/` entry docs, `Knowledge/Crucible_Primitives.json`, `test_quality_gate.py`, and the modular `.agents/scripts/crucible/*.py` package:

- [`acceptance.lock.json.v2`](./acceptance.lock.json.v2) — staged v2 lockfile manifest.
- [`apply_v2_lock.ps1`](./apply_v2_lock.ps1) — idempotent PowerShell installer that validates `acceptance.lock.json.v2` via Python `json.load`, copies it to `.agents/acceptance.lock.json`, and runs `python ".agents/scripts/crucible_gate.py" doctor`.

Run from PowerShell at any time (optional, idempotent):
```powershell
pwsh -File "Project/Inner Gravity/install_pack/apply_v2_lock.ps1"
```

## 3. Retained Migration Utilities & Plugin Archives

- [`migrate_to_local_git.ps1`](./migrate_to_local_git.ps1) / [`sync_to_drive_mirror.ps1`](./sync_to_drive_mirror.ps1) — storage migration/mirroring helpers (`[P-STORAGE]` already live at `C:\crucible-domain`).
- `Inner_Gravity_Antigravity_Plugin_0.1.0.zip`, `Inner_Gravity_Antigravity_Plugin_0.1.1.zip`, `Inner_Gravity_Training_001.zip` — retained historical archives (`.agents/plugins/inner-gravity/` is live).
