"""Compare an expected SHA-256 with a file at the receiving path."""
import argparse
import hashlib
import json
from pathlib import Path, PureWindowsPath
import re


def compare(workspace, relative_name, expected_hash):
    relative = Path(relative_name)
    windows_path = PureWindowsPath(relative_name)
    if (relative.is_absolute() or windows_path.drive or windows_path.root
            or ".." in relative.parts or ".." in windows_path.parts):
        raise ValueError("Use a file path relative to the workspace.")
    if not re.fullmatch(r"[0-9a-fA-F]{64}", expected_hash):
        raise ValueError("Expected SHA-256 must be 64 hexadecimal digits.")
    root = workspace.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("Workspace must be a directory.")
    target = (root / relative).resolve()
    try:
        target.relative_to(root)
    except ValueError as cause:
        raise ValueError("The receiving path resolves outside the workspace.") from cause

    actual_hash = None
    try:
        if not target.is_file():
            state = "unreadable" if target.exists() else "missing"
        else:
            digest = hashlib.sha256()
            with target.open("rb") as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(chunk)
            actual_hash = digest.hexdigest()
            state = "match" if actual_hash == expected_hash.lower() else "mismatch"
    except OSError:
        state = "unreadable"
    return {
        "path": relative_name,
        "expected_sha256": expected_hash.lower(),
        "observed_sha256": actual_hash,
        "state": state,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("workspace", type=Path)
    parser.add_argument("artifact", help="Receiving file path relative to workspace")
    parser.add_argument("expected_sha256", help="Hash from the controlling handoff")
    arguments = parser.parse_args()
    try:
        result = compare(arguments.workspace, arguments.artifact, arguments.expected_sha256)
    except (OSError, RuntimeError, ValueError) as failure:
        parser.error(str(failure))
    print(json.dumps(result))


if __name__ == "__main__":
    main()
