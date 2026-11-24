"""K-TEST-01 + 100-case randomized ACID rollback tests for in-RAM TransactionBuffer."""

from __future__ import annotations

import hashlib
import json
import random
import os
import sys
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from crucible.tx_patch import TransactionBuffer, TransactionValidationError


def test_tx_buffer_atomic_commit_json_transform_and_delete(tmp_path: Path) -> None:
    cfg = tmp_path / "config.json"
    cfg.write_text(json.dumps({"version": 1}) + "\n", encoding="utf-8")
    obsolete = tmp_path / "old.txt"
    obsolete.write_text("remove me\n", encoding="utf-8")

    tx = TransactionBuffer(tmp_path)
    tx.stage_write("mod.py", "def add(a: int, b: int) -> int:\n    return a + b\n")
    tx.stage_json_transform("config.json", lambda d: {**d, "version": 2})
    tx.stage_delete("old.txt")

    assert tx.validate() == []
    receipt = tx.commit()

    assert receipt["status"] == "committed"
    assert receipt["file_count"] == 3
    assert (tmp_path / "mod.py").is_file()
    assert json.loads(cfg.read_text(encoding="utf-8"))["version"] == 2
    assert not obsolete.exists()


def test_tx_buffer_rejects_invalid_syntax_json_tq_and_escape(tmp_path: Path) -> None:
    good = tmp_path / "good.py"
    good.write_text("x = 1\n", encoding="utf-8")

    # 1. Invalid Python syntax aborts entire batch -> good.py untouched on disk
    tx = TransactionBuffer(tmp_path)
    tx.stage_write("good.py", "x = 2\n")
    tx.stage_write("broken.py", "def oops(:\n")
    with pytest.raises(TransactionValidationError):
        tx.commit()
    assert good.read_text(encoding="utf-8") == "x = 1\n"
    assert not (tmp_path / "broken.py").exists()

    # 2. Invalid JSON aborts commit
    tx2 = TransactionBuffer(tmp_path)
    tx2.stage_write("bad.json", "{not valid json")
    with pytest.raises(TransactionValidationError):
        tx2.commit()
    assert not (tmp_path / "bad.json").exists()

    # 3. TQ-01 tautological test file blocked in RAM before disk
    tx3 = TransactionBuffer(tmp_path)
    tx3.stage_write("test_bad_sample.py", "def test_noop():\n    assert True\n")
    with pytest.raises(TransactionValidationError) as exc_info:
        tx3.commit()
    assert any("TQ-01" in err for err in exc_info.value.errors)
    assert not (tmp_path / "test_bad_sample.py").exists()

    # 4. Path escape outside transaction root denied
    tx4 = TransactionBuffer(tmp_path)
    with pytest.raises(ValueError):
        tx4.stage_write("../escape.py", "x = 1\n")


def test_fuzz_tx_buffer_100_cases_all_or_nothing_atomicity(tmp_path: Path) -> None:
    rng = random.Random(20261123)
    committed = 0
    aborted = 0

    for i in range(100):
        case_dir = tmp_path / f"case_{i}"
        case_dir.mkdir()
        seed_file = case_dir / "base.json"
        seed_bytes = json.dumps({"case": i, "ok": True}).encode("utf-8")
        seed_file.write_bytes(seed_bytes)

        tx = TransactionBuffer(case_dir)
        tx.stage_write("base.json", json.dumps({"case": i, "ok": False}))
        tx.stage_write("helper.py", f"VAL = {i}\n")

        inject_fault = (i % 2 == 1)
        if inject_fault:
            if rng.random() < 0.5:
                tx.stage_write("fault.py", "if True print('bad')\n")
            else:
                tx.stage_write("fault.json", "[1, 2, ")
            with pytest.raises(TransactionValidationError):
                tx.commit()
            # Zero-mutation guarantee on disk
            assert seed_file.read_bytes() == seed_bytes
            assert not (case_dir / "helper.py").exists()
            aborted += 1
        else:
            receipt = tx.commit()
            assert receipt["status"] == "committed"
            expected_sha = hashlib.sha256(f"VAL = {i}\n".encode("utf-8")).hexdigest()
            helper_entry = next(f for f in receipt["files"] if f["path"] == "helper.py")
            assert helper_entry["after_sha256"] == expected_sha
            committed += 1

    assert committed == 50
    assert aborted == 50


def test_commit_rolls_back_prior_files_on_mid_commit_failure(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    f1 = tmp_path / "a.txt"
    f2 = tmp_path / "b.txt"
    f1.write_text("orig-a", encoding="utf-8")
    f2.write_text("orig-b", encoding="utf-8")

    tx = TransactionBuffer(tmp_path)
    tx.stage_write("a.txt", "new-a")
    tx.stage_write("b.txt", "new-b")

    real_replace = os.replace
    calls = {"n": 0}

    def flaky_replace(src: str, dst: Path) -> None:
        calls["n"] += 1
        if calls["n"] == 2:
            raise OSError("simulated Windows lock on second file")
        real_replace(src, dst)

    monkeypatch.setattr(os, "replace", flaky_replace)
    with pytest.raises(OSError, match="simulated Windows lock"):
        tx.commit()

    assert f1.read_text(encoding="utf-8") == "orig-a"
    assert f2.read_text(encoding="utf-8") == "orig-b"
