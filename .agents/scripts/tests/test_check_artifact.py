#!/usr/bin/env python3
"""Windows/portable boundary tests for Inner Gravity 0.1.1 check_artifact.py."""

from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path

CHECK_DIR = (
    Path(__file__).resolve().parents[3]
    / ".agents"
    / "plugins"
    / "inner-gravity"
    / "skills"
    / "ig-reconcile"
    / "scripts"
)
if str(CHECK_DIR) not in sys.path:
    sys.path.insert(0, str(CHECK_DIR))

import check_artifact  # noqa: E402


class TestCheckArtifact(unittest.TestCase):
    """Fails if check_artifact silently misclassifies hashes, directories, or unsafe paths."""

    def test_match_mismatch_missing_and_directory(self) -> None:
        """Verify match, mismatch, missing, and unreadable directory states on disk."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            target = ws / "artifacts" / "cut.json"
            target.parent.mkdir(parents=True)
            original = b'{"cut": "v1"}\n'
            target.write_bytes(original)
            digest_v1 = hashlib.sha256(original).hexdigest()

            res_match = check_artifact.compare(ws, "artifacts/cut.json", digest_v1)
            self.assertEqual(res_match["state"], "match")
            self.assertEqual(res_match["observed_sha256"], digest_v1)

            target.write_bytes(b'{"cut": "v2"}\n')
            res_mismatch = check_artifact.compare(ws, "artifacts/cut.json", digest_v1)
            self.assertEqual(res_mismatch["state"], "mismatch")
            self.assertNotEqual(res_mismatch["observed_sha256"], digest_v1)

            res_missing = check_artifact.compare(ws, "artifacts/absent.json", digest_v1)
            self.assertEqual(res_missing["state"], "missing")
            self.assertIsNone(res_missing["observed_sha256"])

            res_dir = check_artifact.compare(ws, "artifacts", digest_v1)
            self.assertEqual(res_dir["state"], "unreadable")

    def test_rejects_invalid_digest_traversal_and_drive_paths(self) -> None:
        """Fail closed on malformed hashes, parent traversal, and Windows absolute drive paths."""
        with tempfile.TemporaryDirectory() as tmp:
            ws = Path(tmp)
            valid_hash = "0" * 64
            with self.assertRaises(ValueError):
                check_artifact.compare(ws, "cut.json", "not-a-hash")
            with self.assertRaises(ValueError):
                check_artifact.compare(ws, "../outside.txt", valid_hash)
            with self.assertRaises(ValueError):
                check_artifact.compare(ws, "D:\\nonexistent\\target.txt", valid_hash)


if __name__ == "__main__":
    unittest.main()
