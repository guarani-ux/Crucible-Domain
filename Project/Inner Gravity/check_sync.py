#!/usr/bin/env python3
"""Thorough sync, plugin-archive, and root-install checker for Crucible Domain."""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

DRIVE_ROOT_ID = "1jpG-7DjOa2xtiYPbBhL07qmCRSVrK1fU"
CRUCIBLE_ROOT = Path(__file__).resolve().parents[2]


def check_sync_locks(root: Path) -> list[str]:
    """Return active Drive for Desktop temp sync folders if present."""
    return [name for name in (".tmp.drivedownload", ".tmp.driveupload") if (root / name).exists()]


def check_root_installs(root: Path) -> dict[str, bool]:
    """Check whether core workspace governance/install files exist at root."""
    return {
        "IDEAS.md": (root / "IDEAS.md").is_file(),
        "AGENTS.md": (root / "AGENTS.md").is_file(),
        ".agents/acceptance.lock.json": (root / ".agents" / "acceptance.lock.json").is_file(),
    }


def check_plugin_zips(root: Path) -> list[dict[str, object]]:
    """Find plugin .zip archives in Crucible Domain and verify if extracted to .agents/plugins/."""
    results: list[dict[str, object]] = []
    plugins_dir = root / ".agents" / "plugins"
    for zp in sorted(root.rglob("*.zip")):
        plugin_name = None
        try:
            with zipfile.ZipFile(zp, "r") as zf:
                for member in zf.namelist():
                    if member.endswith("plugin.json"):
                        parts = Path(member).parts
                        plugin_name = parts[0] if len(parts) > 1 else zp.stem
                        break
        except (OSError, zipfile.BadZipFile) as exc:
            results.append({"zip": str(zp.relative_to(root)), "error": str(exc)})
            continue

        if plugin_name:
            extracted_manifest = plugins_dir / plugin_name / "plugin.json"
            results.append({
                "zip": str(zp.relative_to(root)),
                "plugin": plugin_name,
                "extracted": extracted_manifest.is_file(),
            })
    return results


def check_drive_top_level(root: Path) -> dict[str, object]:
    """Compare top-level entries on Google Drive against local Crucible Domain."""
    gdrive_bin = shutil.which("gdrive")
    if not gdrive_bin:
        return {"error": "gdrive CLI not found on PATH"}
    proc = subprocess.run(
        [gdrive_bin, "readonly", "ls", DRIVE_ROOT_ID],
        capture_output=True,
        text=True,
        timeout=15,
    )
    if proc.returncode != 0:
        return {"error": proc.stderr.strip() or f"gdrive exited {proc.returncode}"}

    drive_names: set[str] = set()
    for line in proc.stdout.splitlines()[2:]:
        parts = line.split()
        if len(parts) >= 2:
            # Name sits between ID (col 0) and Type (folder / text/markdown / etc.)
            # Reconstruct by stripping ID and trailing Type/Size columns
            tokens = line.split("  ")
            cleaned = [t.strip() for t in tokens if t.strip()]
            if len(cleaned) >= 2:
                drive_names.add(cleaned[1])

    local_names = {p.name for p in root.iterdir() if p.name not in (".tmp.drivedownload", ".tmp.driveupload")}
    return {
        "drive_only": sorted(drive_names - local_names),
        "local_only": sorted(local_names - drive_names),
    }


def main() -> int:
    report = {
        "crucible_root": str(CRUCIBLE_ROOT),
        "sync_locks": check_sync_locks(CRUCIBLE_ROOT),
        "root_installs": check_root_installs(CRUCIBLE_ROOT),
        "plugin_zips": check_plugin_zips(CRUCIBLE_ROOT),
        "drive_top_level_diff": check_drive_top_level(CRUCIBLE_ROOT),
    }
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
