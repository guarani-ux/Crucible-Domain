"""Tests for CD-W19 + CD-W07 pure-Python in-RAM AST call-edge scanner."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
HUB_ROOT = SCRIPTS_DIR.parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from crucible.ast_scanner import scan_repo_edges


def test_missing_repo_root_raises_file_not_found(tmp_path: Path) -> None:
    missing = tmp_path / "does_not_exist"
    with pytest.raises(FileNotFoundError, match="does not exist"):
        scan_repo_edges(missing)


def test_call_edge_precision_excludes_unrelated_object_methods(tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text(
        "def helper(value: int) -> int:\n"
        "    return value + 1\n",
        encoding="utf-8",
    )
    (tmp_path / "b.py").write_text(
        "from a import helper\n"
        "import a as mod\n\n"
        "class Widget:\n"
        "    def helper(self) -> int:\n"
        "        return 42\n\n"
        "def caller() -> int:\n"
        "    obj = Widget()\n"
        "    first = helper(1)\n"
        "    second = mod.helper(2)\n"
        "    third = obj.helper()\n"
        "    return first + second + third\n",
        encoding="utf-8",
    )

    result = scan_repo_edges(tmp_path)
    assert result["unit_count"] >= 4
    edge_pairs = [
        (e["source_unit"], e["target_unit"], e["call_kind"])
        for e in result["edges"]
    ]
    assert ("b.caller", "a.helper", "direct_import") in edge_pairs
    assert ("b.caller", "a.helper", "module_attr") in edge_pairs
    assert len(result["edges"]) == 2
    assert all(e["line"] != 12 for e in result["edges"])


def test_relocated_repo_inside_archive_parent_still_scans(tmp_path: Path) -> None:
    relocated_root = tmp_path / "Archive" / "sample_repo"
    relocated_root.mkdir(parents=True)
    (relocated_root / "lib.py").write_text(
        "def compute() -> int:\n"
        "    return 7\n",
        encoding="utf-8",
    )
    (relocated_root / "app.py").write_text(
        "from lib import compute\n\n"
        "def main() -> int:\n"
        "    return compute()\n",
        encoding="utf-8",
    )
    internal_archive = relocated_root / "Archive"
    internal_archive.mkdir()
    (internal_archive / "ignored.py").write_text(
        "from lib import compute\n\n"
        "def stale_call() -> int:\n"
        "    return compute()\n",
        encoding="utf-8",
    )

    result = scan_repo_edges(relocated_root)
    scanned_files = {u["file"] for u in result["units"]}
    assert "lib.py" in scanned_files
    assert "app.py" in scanned_files
    assert "Archive/ignored.py" not in scanned_files
    assert result["edge_count"] == 1
    assert result["edges"][0]["source_file"] == "app.py"
    assert result["edges"][0]["target_unit"] == "lib.compute"


def test_live_hub_scan_with_import_root() -> None:
    result = scan_repo_edges(HUB_ROOT, import_root=".agents/scripts")
    assert result["repo_root"] == str(HUB_ROOT)
    assert result["import_root"] == ".agents/scripts"
    assert result["unit_count"] > 50
    assert result["edge_count"] > 10
    assert result["elapsed_ms"] >= 0.0
    assert all(e["source_module"] != e["target_module"] for e in result["edges"])
