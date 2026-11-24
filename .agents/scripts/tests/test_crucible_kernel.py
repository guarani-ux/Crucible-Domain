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


def _write_operator_grants(root: Path, grants: list[dict[str, object]]) -> None:
    grants_path = root / ck.OPERATOR_GRANTS_REL_PATH
    grants_path.parent.mkdir(parents=True, exist_ok=True)
    grants_path.write_text(json.dumps({"grants": grants}, indent=2) + "\n", encoding="utf-8")


def test_negative_capability_token_rejects_stale_and_missing(tmp_path: Path) -> None:
    asset = tmp_path / "cut_v1.mp4"
    asset.write_bytes(b"version-1-bytes")
    v1_hash = ck.sha256_file(asset)

    ok_local, _ = ck.authorize_effect(ck.EffectTier.LOCAL_MUTATE, asset, None)
    assert ok_local is True

    ok_missing, msg_missing = ck.authorize_effect(ck.EffectTier.EXTERNAL_RELEASE, asset, None, root=tmp_path)
    assert ok_missing is False
    assert "DENIED" in msg_missing

    # 1. Unbacked in-memory CapabilityToken without .agents/operator_grants.json -> DENIED
    tok_unbacked = ck.CapabilityToken(scope="G06", target_sha256=v1_hash, issuer="operator", granted=True, grant_id="g1")
    ok_unbacked, msg_unbacked = ck.authorize_effect(
        ck.EffectTier.EXTERNAL_RELEASE, asset, tok_unbacked, root=tmp_path
    )
    assert ok_unbacked is False
    assert "missing or invalid .agents/operator_grants.json" in msg_unbacked

    ok_no_root, msg_no_root = ck.authorize_effect(ck.EffectTier.EXTERNAL_RELEASE, asset, tok_unbacked)
    assert ok_no_root is False
    assert "unbacked in-memory CapabilityToken" in msg_no_root

    # 2. Grant in .agents/operator_grants.json with issuer="model" -> DENIED
    _write_operator_grants(
        tmp_path,
        [
            {
                "grant_id": "g-model",
                "effect": "EXTERNAL_RELEASE",
                "scope": "G06",
                "issuer": "model",
                "granted": True,
                "target_sha256": v1_hash,
                "target_path": "cut_v1.mp4",
            },
            {
                "grant_id": "g1",
                "effect": "EXTERNAL_RELEASE",
                "scope": "G06",
                "issuer": "operator",
                "granted": True,
                "target_sha256": v1_hash,
                "target_path": "cut_v1.mp4",
            },
        ],
    )
    tok_model = ck.CapabilityToken(scope="G06", target_sha256=v1_hash, issuer="model", granted=True, grant_id="g-model")
    ok_model, msg_model = ck.authorize_effect(ck.EffectTier.EXTERNAL_RELEASE, asset, tok_model, root=tmp_path)
    assert ok_model is False
    assert "forbidden model/self issuer" in msg_model

    # 3. Valid operator grant in .agents/operator_grants.json -> ALLOWED on v1, DENIED when bytes change
    ok_v1, msg_v1 = ck.authorize_effect(ck.EffectTier.EXTERNAL_RELEASE, asset, tok_unbacked, root=tmp_path)
    assert ok_v1 is True, msg_v1
    assert "verified operator grant g1" in msg_v1

    # CHG-01: mutating asset to v2 invalidates v1 capability token
    asset.write_bytes(b"version-2-trimmed-bytes")
    ok_stale, msg_stale = ck.authorize_effect(ck.EffectTier.EXTERNAL_RELEASE, asset, tok_unbacked, root=tmp_path)
    assert ok_stale is False
    assert "stale CapabilityToken" in msg_stale

    # run_kernel passes root=root so stale/revoked grant triggers OPERATOR_ESCALATION
    esc = ck.run_kernel(
        tmp_path,
        outcome="Release cut",
        changed_files=[],
        requested_effects=[(ck.EffectTier.EXTERNAL_RELEASE, asset, tok_unbacked)],
    )
    assert esc["status"] == "OPERATOR_ESCALATION"
    assert len(esc["capability_denials"]) == 1


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
    assert ck.step_lyapunov_potential(1, 0) == "ZERO_HYGIENE_POTENTIAL"
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

    # Positive live hub kernel evaluation (checks pass without external verify_cmd/review)
    data = ck.run_kernel(HUB_ROOT, outcome="Verify hub invariants")
    assert data["status"] == "CHECKS_PASSED"
    assert data["potential_v"] == 0
    assert data["hygiene_ok"] is True
    assert data["checks_passed"] is True
    assert data["outcome_verified"] is False


def test_kernel_autofix_repairs_stale_sha256_and_pre_tool_guards(tmp_path: Path) -> None:
    # 1. Autofix repairs stale_sha256 mechanically (V=1 -> V=0)
    (tmp_path / "Personal Work").mkdir()
    dep = tmp_path / "src.txt"
    dep.write_text("fresh-bytes", encoding="utf-8")
    (tmp_path / "Personal Work" / "doc.md").write_text(
        "---\ndepends_on:\n  - src.txt\ndepends_on_sha256:\n  src.txt: " + ("0" * 64) + "\n---\n# Doc\n",
        encoding="utf-8",
    )
    fixed = ck.run_kernel(tmp_path, outcome="Autofix stale hash", changed_files=["src.txt"], autofix=True)
    assert fixed["status"] == "CHECKS_PASSED"
    assert fixed["potential_v"] == 0
    assert fixed["hygiene_ok"] is True
    assert fixed["outcome_verified"] is False
    assert len(fixed["autofixed"]) == 1

    # 2. Pre-tool SYNTAX_GUARD blocks invalid Python write_file in RAM
    bad_py = {
        "toolCall": {
            "name": "write_file",
            "args": {"Path": str(tmp_path / "broken.py"), "Content": "def broken(:\n    pass\n"},
        }
    }
    p_syn = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "crucible_gate.py"), "--root", str(tmp_path), "pre-tool"],
        input=json.dumps(bad_py),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert p_syn.returncode == 0
    syn_dec = json.loads(p_syn.stdout)
    assert syn_dec["decision"] == "deny"
    assert "SYNTAX_GUARD" in syn_dec["reason"]

    # 3. Pre-tool DELTA_ONLY blocks full-file Overwrite on >150-line existing file
    big_file = tmp_path / "large.py"
    big_file.write_text("\n".join(f"x_{i} = {i}" for i in range(160)) + "\n", encoding="utf-8")
    overwrite_req = {
        "toolCall": {
            "name": "write_file",
            "args": {"Path": str(big_file), "Content": "x = 1\n", "Overwrite": True},
        }
    }
    p_ow = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "crucible_gate.py"), "--root", str(tmp_path), "pre-tool"],
        input=json.dumps(overwrite_req),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert p_ow.returncode == 0
    ow_dec = json.loads(p_ow.stdout)
    assert ow_dec["decision"] == "deny"
    assert "DELTA_ONLY" in ow_dec["reason"]


def test_kernel_separates_checks_passed_from_outcome_verified(tmp_path: Path) -> None:
    src = tmp_path / "src.txt"
    src.write_text("verified-content\n", encoding="utf-8")
    actual_sha = ck.sha256_file(src)

    # 4. Clean hygiene (potential_v == 0) with no verify_cmd -> CHECKS_PASSED, outcome_verified is False
    res_no_cmd = ck.run_kernel(tmp_path, outcome="Deliver artifact", changed_files=[])
    assert res_no_cmd["status"] == "CHECKS_PASSED"
    assert res_no_cmd["hygiene_ok"] is True
    assert res_no_cmd["checks_passed"] is True
    assert res_no_cmd["outcome_verified"] is False
    assert res_no_cmd["verify_ran"] is False

    # 5. Clean hygiene + failing verify_cmd -> VERIFY_FAILED, checks_passed False, outcome_verified False
    res_fail_cmd = ck.run_kernel(
        tmp_path,
        outcome="Deliver artifact",
        changed_files=[],
        verify_cmd=f'"{sys.executable}" -c "import sys; sys.exit(1)"',
    )
    assert res_fail_cmd["status"] == "VERIFY_FAILED"
    assert res_fail_cmd["hygiene_ok"] is True
    assert res_fail_cmd["checks_passed"] is False
    assert res_fail_cmd["outcome_verified"] is False
    assert res_fail_cmd["verify_ran"] is True
    assert res_fail_cmd["verify_exit_code"] == 1

    # 6. Clean hygiene + passing verify_cmd + self-review or stale reviewed_sha256 -> CHECKS_PASSED, outcome_verified False
    passing_cmd = f'"{sys.executable}" -c "print(\'ok\')"'
    res_self = ck.run_kernel(
        tmp_path,
        outcome="Deliver artifact",
        changed_files=[],
        verify_cmd=passing_cmd,
        review_receipt={
            "status": "PASS",
            "reviewer": "author",
            "reviewed_sha256": {"src.txt": actual_sha},
        },
    )
    assert res_self["status"] == "CHECKS_PASSED"
    assert res_self["checks_passed"] is True
    assert res_self["review_valid"] is False
    assert res_self["outcome_verified"] is False

    res_stale_review = ck.run_kernel(
        tmp_path,
        outcome="Deliver artifact",
        changed_files=[],
        verify_cmd=passing_cmd,
        review_receipt={
            "status": "PASS",
            "reviewer": "ig-evidence-review",
            "reviewed_sha256": {"src.txt": "0" * 64},
        },
    )
    assert res_stale_review["status"] == "CHECKS_PASSED"
    assert res_stale_review["review_valid"] is False
    assert res_stale_review["outcome_verified"] is False

    # 7. Clean hygiene + non-empty outcome + passing live verify_cmd + valid independent SHA-256 receipt -> OUTCOME_VERIFIED
    res_verified = ck.run_kernel(
        tmp_path,
        outcome="Deliver artifact",
        changed_files=[],
        verify_cmd=passing_cmd,
        review_receipt={
            "status": "PASS",
            "reviewer": "ig-evidence-review",
            "reviewed_sha256": {"src.txt": actual_sha},
        },
    )
    assert res_verified["status"] == "OUTCOME_VERIFIED"
    assert res_verified["hygiene_ok"] is True
    assert res_verified["checks_passed"] is True
    assert res_verified["review_valid"] is True
    assert res_verified["outcome_verified"] is True
    assert res_verified["verify_ran"] is True
    assert res_verified["verify_exit_code"] == 0
