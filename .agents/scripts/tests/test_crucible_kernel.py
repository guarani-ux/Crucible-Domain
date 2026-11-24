#!/usr/bin/env python3
"""Tests for Crucible Kernel: IncrementalDAG, CapabilityToken, EVOI, CEGIS, and Lyapunov convergence."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HUB_ROOT = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import crucible_kernel as ck  # noqa: E402


def test_incremental_dag_propagates_dirty_closure() -> None:
    dag = ck.IncrementalDAG(HUB_ROOT)
    downstream = dag.dirty_closure(["scripts/verify_all.ps1"])
    assert "Personal Work/CS_Loop_Weakness_Audit.md" in downstream

    py_downstream = dag.dirty_closure([".agents/scripts/ram_ml_engine.py"])
    assert ".agents/scripts/tests/test_ram_ml_engine.py" in py_downstream


def test_negative_capability_token_rejects_stale_and_missing(tmp_path: Path) -> None:
    asset = tmp_path / "cut_v1.mp4"
    asset.write_bytes(b"version-1-bytes")
    v1_hash = ck.sha256_file(asset)

    ok_local, _ = ck.authorize_effect(ck.EffectTier.LOCAL_MUTATE, asset, None)
    assert ok_local is True

    ok_missing, msg_missing = ck.authorize_effect(ck.EffectTier.EXTERNAL_RELEASE, asset, None)
    assert ok_missing is False
    assert "DENIED" in msg_missing

    tok = ck.CapabilityToken(scope="G06", target_sha256=v1_hash, issuer="operator", granted=True)
    ok_v1, _ = ck.authorize_effect(ck.EffectTier.EXTERNAL_RELEASE, asset, tok)
    assert ok_v1 is True

    # CHG-01: mutating asset to v2 invalidates v1 capability token
    asset.write_bytes(b"version-2-trimmed-bytes")
    ok_stale, msg_stale = ck.authorize_effect(ck.EffectTier.EXTERNAL_RELEASE, asset, tok)
    assert ok_stale is False
    assert "stale CapabilityToken" in msg_stale


def test_evoi_routes_unknowns_and_lyapunov_halts_oscillation() -> None:
    evoi = ck.evaluate_evoi(
        [
            ck.Unknown("font_variant", flips_outcome=False),
            ck.Unknown("socket_latency", flips_outcome=True, local_probe_cost=0.5),
            ck.Unknown("g06_release", flips_outcome=True, requires_authority=True),
        ]
    )
    assert evoi["resolve_autonomously"] == ["font_variant"]
    assert len(evoi["run_local_probe"]) == 1
    assert len(evoi["escalate_to_operator"]) == 1

    assert ck.step_lyapunov_potential(3, 2) == "CONVERGING"
    assert ck.step_lyapunov_potential(1, 0) == "VERIFIED_DONE"
    assert ck.step_lyapunov_potential(2, 2) == "HALT_OSCILLATION"


def test_run_kernel_cegis_stale_witness_and_cli_rejection(tmp_path: Path) -> None:
    (tmp_path / "Personal Work").mkdir()
    dep = tmp_path / "src.txt"
    dep.write_text("changed-content", encoding="utf-8")
    (tmp_path / "Personal Work" / "doc.md").write_text(
        "---\ndepends_on:\n  - src.txt\ndepends_on_sha256:\n  src.txt: " + ("0" * 64) + "\n---\n# Doc\n",
        encoding="utf-8",
    )
    res = ck.run_kernel(tmp_path, outcome="Verify stale witness", changed_files=["src.txt"])
    assert res["status"] == "AUTONOMOUS_REPAIR"
    assert res["potential_v"] == 1
    assert res["counterexamples"][0]["kind"] == "stale_sha256"

    # Negative CLI rejection: kernel exits non-zero when stale SHA-256 counterexample exists
    bad_proc = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "crucible_gate.py"), "--root", str(tmp_path), "kernel", "--json"],
        cwd=HUB_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert bad_proc.returncode != 0

    # Positive CLI JSON roundtrip on live hub
    proc = subprocess.run(
        [sys.executable, ".agents/scripts/crucible_gate.py", "kernel", "--json", "Verify hub invariants"],
        cwd=HUB_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["status"] == "VERIFIED_DONE"
    assert data["potential_v"] == 0
