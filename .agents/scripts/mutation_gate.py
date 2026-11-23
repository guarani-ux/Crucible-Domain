#!/usr/bin/env python3
"""Deterministic mutation-kill gate for Crucible Domain safety checks."""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class GateMutation:
    """Single deliberate regression applied in an isolated temp copy."""

    id: str
    description: str
    target: str
    replacement: str


GATE_MUTATIONS: tuple[GateMutation, ...] = (
    GateMutation(
        id="M1_DISABLE_ASANA_BLOCK",
        description="Disable app.asana.com check for staged Calgary Public Library files.",
        target='if norm.startswith("Calgary Public Library/") and _staged_contains_asana(norm, root):',
        replacement="if False:",
    ),
    GateMutation(
        id="M2_DISABLE_DRIVE_TMP_BLOCK",
        description="Disable .tmp.drive* staged sync-temp file block.",
        target='if any(part.startswith(".tmp.drive") for part in parts):',
        replacement="if False:",
    ),
    GateMutation(
        id="M3_DISABLE_TQ_GATE_IN_CHECK",
        description="Disable test_quality_gate.audit_paths enforcement inside cmd_check.",
        target="for tqf in test_quality_gate.audit_paths([tests_dir]):",
        replacement="for tqf in []:",
    ),
    GateMutation(
        id="M4_DISABLE_EDIT_FILE_SHIFTING_SAND",
        description="Exclude edit_file from SHIFTING_SAND pre-tool gate.",
        target='if tool_call.get("name") not in ("write_file", "edit_file"):',
        replacement='if tool_call.get("name") not in ("write_file",):',
    ),
    GateMutation(
        id="M5_DISABLE_IDEAS_MISSING_CHECK",
        description="Disable missing IDEAS.md check inside cmd_check.",
        target='if not (root / "IDEAS.md").is_file():',
        replacement="if False:",
    ),
    GateMutation(
        id="M6_DISABLE_LEDGER_SCHEMA_CHECK",
        description="Disable Knowledge/outcome_ledger.json schema validation inside cmd_check.",
        target='if (root / "Knowledge" / "outcome_ledger.json").is_file():',
        replacement="if False:",
    ),
)


@dataclass(frozen=True)
class MutationResult:
    """Outcome of running test_crucible_gate.py against one mutated copy."""

    id: str
    description: str
    status: str  # KILLED | SURVIVED | MISSING_TARGET
    detail: str


def run_mutation_gate(root: Path = ROOT) -> tuple[bool, list[MutationResult]]:
    """Run all registered gate mutations in isolated temp copies and report kill status."""
    scripts_dir = root / ".agents" / "scripts"
    gate_path = scripts_dir / "crucible_gate.py"
    if not gate_path.is_file():
        return False, [
            MutationResult(
                id="GATE_MISSING",
                description="Locate crucible_gate.py",
                status="MISSING_TARGET",
                detail=f"Missing {gate_path}",
            )
        ]

    orig_gate = gate_path.read_text(encoding="utf-8")
    results: list[MutationResult] = []

    for mut in GATE_MUTATIONS:
        occurrences = orig_gate.count(mut.target)
        if occurrences != 1:
            results.append(
                MutationResult(
                    id=mut.id,
                    description=mut.description,
                    status="MISSING_TARGET",
                    detail=f"Expected 1 occurrence of target in crucible_gate.py, found {occurrences}",
                )
            )
            continue

        with tempfile.TemporaryDirectory() as tmp:
            tmp_scripts = Path(tmp) / "scripts"
            shutil.copytree(
                scripts_dir,
                tmp_scripts,
                ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"),
            )
            (tmp_scripts / "crucible_gate.py").write_text(
                orig_gate.replace(mut.target, mut.replacement, 1),
                encoding="utf-8",
            )
            proc = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pytest",
                    str(tmp_scripts / "tests" / "test_crucible_gate.py"),
                    "-q",
                    "-p",
                    "no:cacheprovider",
                ],
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=False,
            )
            combined = (proc.stdout or proc.stderr).strip()
            tail = combined.splitlines()[-1] if combined else f"exit={proc.returncode}"
            status = "KILLED" if proc.returncode != 0 else "SURVIVED"
            results.append(
                MutationResult(
                    id=mut.id,
                    description=mut.description,
                    status=status,
                    detail=tail,
                )
            )

    ok = bool(results) and all(r.status == "KILLED" for r in results)
    return ok, results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Verify Crucible gate tests kill deliberate gate mutations.")
    parser.add_argument("--root", type=Path, default=ROOT, help="Repository root path.")
    parser.add_argument("--json", action="store_true", help="Emit structured JSON results.")
    args = parser.parse_args(argv)

    ok, results = run_mutation_gate(args.root.resolve())
    killed = sum(1 for r in results if r.status == "KILLED")
    if args.json:
        print(
            json.dumps(
                {
                    "ok": ok,
                    "killed": killed,
                    "total": len(GATE_MUTATIONS),
                    "results": [asdict(r) for r in results],
                },
                indent=2,
            )
        )
    else:
        for r in results:
            print(f"[{r.status}] {r.id}: {r.detail}")
        summary_label = "PASS" if ok else "BLOCKED"
        print(f"{summary_label}: Mutation kill rate {killed}/{len(GATE_MUTATIONS)}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
