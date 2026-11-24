"""K-TEST-01 3-case qualification tests for Slice A (Hub Closure):
- Self-model drift check (_check_self_model_drift)
- Artifact depends_on & staleness check (_check_artifact_dependencies)
- Capability precedence tie-breaking (CAPABILITY_PRECEDENCE)
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import crucible_gate
from crucible.models import CapabilityEntry, CapabilityIndex
from crucible.router import CAPABILITY_PRECEDENCE, _score_entries


def _seed_minimal_workspace(tmp_path: Path) -> Path:
    (tmp_path / "AGENTS.md").write_text(
        "Registered plugins: inner-gravity, writers-room.\n",
        encoding="utf-8",
    )
    (tmp_path / "Graphs").mkdir(parents=True, exist_ok=True)
    (tmp_path / "Graphs" / "00_System_Atlas_and_Neon_Handoff.md").write_text(
        "Plugins: inner-gravity, writers-room. Kernel: models.py, router.py.\n",
        encoding="utf-8",
    )
    for pname in ("inner-gravity", "writers-room"):
        pdir = tmp_path / ".agents" / "plugins" / pname
        pdir.mkdir(parents=True, exist_ok=True)
        (pdir / "plugin.json").write_text(f'{{"name": "{pname}"}}\n', encoding="utf-8")

    kdir = tmp_path / ".agents" / "scripts" / "crucible"
    kdir.mkdir(parents=True, exist_ok=True)
    (kdir / "models.py").write_text("# models\n", encoding="utf-8")
    (kdir / "router.py").write_text("# router\n", encoding="utf-8")
    return tmp_path


def test_self_model_drift_catches_missing_plugin_and_module_failure(tmp_path: Path) -> None:
    root = _seed_minimal_workspace(tmp_path)

    # Good: all plugins and kernel modules are documented
    assert crucible_gate._check_self_model_drift(root) == []

    # Bad: new undocumented plugin + new undocumented kernel module
    ghost = root / ".agents" / "plugins" / "story-lane"
    ghost.mkdir(parents=True, exist_ok=True)
    (ghost / "plugin.json").write_text('{"name": "story-lane"}\n', encoding="utf-8")
    (root / ".agents" / "scripts" / "crucible" / "extra.py").write_text("# extra\n", encoding="utf-8")

    drift = crucible_gate._check_self_model_drift(root)
    assert any("story-lane" in msg and "AGENTS.md" in msg for msg in drift)
    assert any("story-lane" in msg and "00_System_Atlas" in msg for msg in drift)
    assert any("extra.py" in msg and "00_System_Atlas" in msg for msg in drift)

    # Changed: document story-lane in AGENTS.md only -> Atlas still flags it, AGENTS.md clears
    (root / "AGENTS.md").write_text(
        "Registered plugins: inner-gravity, writers-room, story-lane.\n",
        encoding="utf-8",
    )
    drift_after = crucible_gate._check_self_model_drift(root)
    assert not any("story-lane" in msg and "AGENTS.md" in msg for msg in drift_after)
    assert any("story-lane" in msg and "00_System_Atlas" in msg for msg in drift_after)


def test_artifact_dependencies_rejects_broken_and_warns_stale(tmp_path: Path, capsys) -> None:
    (tmp_path / "Personal Work").mkdir(parents=True, exist_ok=True)
    dep = tmp_path / "Personal Work" / "GROUND_TRUTH.md"
    dep.write_text("# Ground Truth\n", encoding="utf-8")

    # Good: fresh artifact newer than its depends_on target
    art = tmp_path / "Personal Work" / "brief.md"
    art.write_text(
        "---\ndepends_on:\n  - Personal Work/GROUND_TRUTH.md\n---\n# Brief\n",
        encoding="utf-8",
    )
    os.utime(dep, (1_700_000_000, 1_700_000_000))
    os.utime(art, (1_700_000_100, 1_700_000_100))

    failures, warnings = crucible_gate._check_artifact_dependencies(tmp_path, strict=False)
    assert failures == []
    assert warnings == []

    # Changed: dependency becomes newer than artifact -> WARN normally, FAIL under --strict
    os.utime(dep, (1_700_000_200, 1_700_000_200))
    failures_soft, warnings_soft = crucible_gate._check_artifact_dependencies(tmp_path, strict=False)
    assert failures_soft == []
    assert len(warnings_soft) == 1
    assert "stale artifact" in warnings_soft[0]

    failures_strict, warnings_strict = crucible_gate._check_artifact_dependencies(tmp_path, strict=True)
    assert len(failures_strict) == 1
    assert "stale artifact" in failures_strict[0]
    assert warnings_strict == []

    # Bad: broken/missing depends_on target fails even when strict=False
    art.write_text(
        "---\ndepends_on:\n  - Personal Work/DOES_NOT_EXIST.md\n---\n# Brief\n",
        encoding="utf-8",
    )
    failures_broken, _ = crucible_gate._check_artifact_dependencies(tmp_path, strict=False)
    assert len(failures_broken) == 1
    assert "broken depends_on" in failures_broken[0]

    rc = crucible_gate.cmd_check(tmp_path, strict=True)
    out = capsys.readouterr().out
    assert rc != 0
    assert "BLOCKED" in out


def test_capability_precedence_tie_break() -> None:
    entries = {}
    for cid, kind in (
        ("K-01", "knowledge"),
        ("PRIM-01", "primitive"),
        ("SK-01", "skill"),
        ("MW-01", "procedure"),
        ("DOC-01", "entry_doc"),
    ):
        entries[cid] = CapabilityEntry(
            id=cid,
            kind=kind,
            title="Crucible Routing",
            path=f"{cid}.md",
            line=1,
            domain="core",
            reachability="local",
            summary="Deterministic crucible routing check.",
        )

    idx = CapabilityIndex(
        root=Path("."),
        entries=entries,
        alias_map={},
        chatgpt_bindings={},
        build_ms=1.0,
        skill_frontmatter_bytes=0,
    )
    matches = _score_entries(idx, ["crucible"], min_score=0.1)
    ordered_kinds = [m.entry.kind for m in matches]
    assert ordered_kinds == ["entry_doc", "procedure", "skill", "primitive", "knowledge"]
    assert CAPABILITY_PRECEDENCE["entry_doc"] < CAPABILITY_PRECEDENCE["procedure"] < CAPABILITY_PRECEDENCE["skill"]
