"""Autonomous Discovery, Replay-Verified Execution & Fault-Recovery Loop (CD-W45)."""

from __future__ import annotations

import ast
import difflib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from crucible.ast_scanner import scan_repo_edges
from crucible.campaign_ir import (
    CampaignCheckpoint,
    CampaignSpec,
    ErrorCircuitBreaker,
    LoopStateMachine,
    RatchetEntry,
    SliceNode,
    append_ratchet_ledger,
    compile_campaign,
    compute_slice_input_sha256,
    execute_slice_transaction,
    load_campaign_checkpoint,
    optimize_campaign,
    save_campaign_checkpoint,
)
from crucible.doctor import _audit_mcp_configs
from crucible.models import DiagnosticFinding
from crucible.tx_patch import TransactionBuffer, TransactionValidationError

try:
    import test_quality_gate as tqg
except ImportError:
    tqg = None

try:
    import crucible_gate as cg
except ImportError:
    cg = None


ORPHAN_EXCLUDED_FILENAMES = frozenset(
    {
        "__init__.py",
        "__main__.py",
        "crucible_gate.py",
        "crucible_index.py",
        "verify_all.py",
        "mutation_gate.py",
        "ram_ml_daemon.py",
        "ram_ml_engine.py",
        "test_quality_gate.py",
        "crucible_kernel.py",
    }
)
ARTIFACT_DOMAIN_DIRS = ("Calgary Public Library", "Personal Work", "Graphs")
SKIP_PY_SCAN_DIRS = frozenset({".git", "__pycache__", ".pytest_cache", ".venv", "venv", "node_modules"})


@dataclass
class DiscoveredGap:
    """Single deterministic repository gap surfaced by discover_gaps()."""

    id: str
    kind: str
    severity: str
    target_path: str
    detail: str
    verify_cmd: str
    autofix_kind: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class DiscoveryReport:
    """Structured discovery scan result + synthesized disjoint CampaignSpec dictionary."""

    repo_root: str
    import_root: str
    elapsed_ms: float
    unit_count: int
    edge_count: int
    gaps: list[DiscoveredGap]
    campaign_spec: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "repo_root": self.repo_root,
            "import_root": self.import_root,
            "elapsed_ms": self.elapsed_ms,
            "unit_count": self.unit_count,
            "edge_count": self.edge_count,
            "gaps": [g.to_dict() for g in self.gaps],
            "campaign_spec": self.campaign_spec,
        }


@dataclass
class VerifiedDiff:
    """Replay-verified execution outcome for a single SliceNode."""

    slice_id: str
    passed: bool
    replay_verified: bool
    rolled_back: bool
    before_sha256: str
    after_sha256: str
    replay_sha256: str
    diff_text: str
    worktree_used: bool
    error: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class ReplayTraceEvent:
    """Append-only JSONL trace record emitted per replay-verified slice execution."""

    step_id: str
    slice_id: str
    input_sha256: str
    output_sha256: str
    exit_code: int
    status: str
    replay_match: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


VALID_REPAIR_CATEGORIES = frozenset(
    {
        "interpret input",
        "preserve data",
        "compute result",
        "serialize output",
        "handle boundary",
    }
)


@dataclass(frozen=True)
class CounterexampleProbe:
    """Executable recipient-goal counterexample anchored verbatim to the active objective."""

    id: str
    anchor: str
    command: str
    expected_stdout: str
    repair_category: str = "compute result"
    expected_exit_code: int = 0

    def signature(self) -> tuple[str, int, str]:
        return (self.command.strip(), int(self.expected_exit_code), self.expected_stdout.strip())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CounterexampleProbe:
        return cls(
            id=str(data["id"]),
            anchor=str(data["anchor"]),
            command=str(data["command"]),
            expected_stdout=str(data["expected_stdout"]),
            repair_category=str(data.get("repair_category", "compute result")),
            expected_exit_code=int(data.get("expected_exit_code", 0)),
        )


@dataclass
class CounterexampleResult:
    """Outcome of running CounterexampleRatchet.evaluate()."""

    passed: bool
    reason: str
    promoted_probe: CounterexampleProbe | None = None
    inherited_count: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "reason": self.reason,
            "promoted_probe": self.promoted_probe.to_dict() if self.promoted_probe else None,
            "inherited_count": self.inherited_count,
        }


def is_grounded_anchor(anchor: str, objective: str) -> bool:
    """Verify anchor appears verbatim in objective with at least min(2, word_count) tokens."""
    clean_anchor = anchor.strip()
    obj_words = re.findall(r"\w+", objective)
    anchor_words = re.findall(r"\w+", clean_anchor)
    return bool(obj_words and clean_anchor in objective and len(anchor_words) >= min(2, len(obj_words)))


def run_counterexample_probe(exec_root: Path, probe: CounterexampleProbe) -> tuple[bool, int, str]:
    """Execute a single CounterexampleProbe in exec_root and compare exit code + stdout."""
    proc = subprocess.run(
        probe.command,
        cwd=exec_root,
        shell=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    matched = proc.returncode == probe.expected_exit_code and proc.stdout.strip() == probe.expected_stdout.strip()
    return matched, proc.returncode, proc.stdout.strip()


class CounterexampleRatchet:
    """Adversarial counterexample ratchet with verbatim anchor grounding and second-opinion confirmation."""

    def __init__(
        self,
        inherited: list[CounterexampleProbe] | None = None,
        persist_path: Path | str | None = None,
    ) -> None:
        self.persist_path: Path | None = Path(persist_path) if persist_path is not None else None
        self.inherited: list[CounterexampleProbe] = []
        self._signatures: set[tuple[str, int, str]] = set()
        if self.persist_path is not None and self.persist_path.is_file():
            raw = json.loads(self.persist_path.read_text(encoding="utf-8"))
            for item in raw.get("inherited", []):
                self._add_inherited(CounterexampleProbe.from_dict(item), save=False)
        for probe in inherited or []:
            self._add_inherited(probe, save=False)

    def _add_inherited(self, probe: CounterexampleProbe, *, save: bool = True) -> bool:
        sig = probe.signature()
        if sig in self._signatures:
            return False
        self._signatures.add(sig)
        self.inherited.append(probe)
        if save and self.persist_path is not None:
            self._save()
        return True

    def _save(self) -> None:
        if self.persist_path is None:
            return
        self.persist_path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"inherited": [p.to_dict() for p in self.inherited]},
            indent=2,
            sort_keys=True,
        ) + "\n"
        fd, tmp_name = tempfile.mkstemp(prefix=".ratchet_", dir=str(self.persist_path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(payload)
            os.replace(tmp_name, self.persist_path)
        except Exception:
            if os.path.exists(tmp_name):
                os.unlink(tmp_name)
            raise

    def evaluate(
        self,
        exec_root: Path,
        objective: str,
        propose_fn: Callable[[], CounterexampleProbe | None] | None = None,
        second_opinion_fn: Callable[[CounterexampleProbe], tuple[bool, str, str]] | None = None,
    ) -> CounterexampleResult:
        """Replay inherited probes, then optionally challenge candidate with a fresh grounded counterexample."""
        for probe in self.inherited:
            matched, _, _ = run_counterexample_probe(exec_root, probe)
            if not matched:
                return CounterexampleResult(
                    passed=False,
                    reason=f"REALIGN_INHERITED: {probe.repair_category} to satisfy {probe.anchor[:200]}",
                    promoted_probe=None,
                    inherited_count=len(self.inherited),
                )

        if propose_fn is None:
            return CounterexampleResult(
                passed=True,
                reason="inherited_probes_ok",
                promoted_probe=None,
                inherited_count=len(self.inherited),
            )

        proposed = propose_fn()
        if proposed is None:
            return CounterexampleResult(
                passed=True,
                reason="no_new_counterexample",
                promoted_probe=None,
                inherited_count=len(self.inherited),
            )

        if not is_grounded_anchor(proposed.anchor, objective):
            return CounterexampleResult(
                passed=False,
                reason="GOAL_REQUIRES_CLARIFICATION: counterexample anchor not grounded in active objective",
                promoted_probe=None,
                inherited_count=len(self.inherited),
            )

        if proposed.repair_category not in VALID_REPAIR_CATEGORIES:
            return CounterexampleResult(
                passed=False,
                reason=f"INVALID_COUNTEREXAMPLE: unknown repair_category '{proposed.repair_category}'",
                promoted_probe=None,
                inherited_count=len(self.inherited),
            )

        if proposed.signature() in self._signatures:
            return CounterexampleResult(
                passed=False,
                reason="REJECT_DUPLICATE_PROBE: counterexample repeats a previously checked input",
                promoted_probe=None,
                inherited_count=len(self.inherited),
            )

        matched, _, _ = run_counterexample_probe(exec_root, proposed)
        if matched:
            self._add_inherited(proposed, save=True)
            return CounterexampleResult(
                passed=True,
                reason="counterexample_passed_and_promoted",
                promoted_probe=proposed,
                inherited_count=len(self.inherited),
            )

        if second_opinion_fn is not None:
            determinate, second_anchor, second_expected = second_opinion_fn(proposed)
            if (
                not determinate
                or not is_grounded_anchor(second_anchor, objective)
                or second_expected.strip() != proposed.expected_stdout.strip()
            ):
                return CounterexampleResult(
                    passed=False,
                    reason="GOAL_REQUIRES_CLARIFICATION: independent expected outcomes disagree",
                    promoted_probe=None,
                    inherited_count=len(self.inherited),
                )

        self._add_inherited(proposed, save=True)
        return CounterexampleResult(
            passed=False,
            reason=f"REALIGN_GOAL: {proposed.repair_category} to satisfy {proposed.anchor[:200]}",
            promoted_probe=proposed,
            inherited_count=len(self.inherited),
        )


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def _collect_python_syntax_gaps(
    root: Path,
    import_root: str,
    gaps: list[DiscoveredGap],
    next_id: Callable[[str], str],
) -> None:
    scan_roots: list[Path] = []
    seen_roots: set[Path] = set()
    for candidate_rel in (".agents/scripts", import_root):
        if not candidate_rel:
            continue
        candidate = (root / candidate_rel).resolve()
        if candidate.is_dir() and (candidate == root or candidate.is_relative_to(root)):
            if candidate not in seen_roots:
                seen_roots.add(candidate)
                scan_roots.append(candidate)

    seen_files: set[Path] = set()
    for base in scan_roots:
        for py_file in sorted(base.rglob("*.py")):
            if any(part in SKIP_PY_SCAN_DIRS for part in py_file.parts):
                continue
            resolved = py_file.resolve()
            if resolved in seen_files:
                continue
            seen_files.add(resolved)
            rel_path = resolved.relative_to(root).as_posix()
            try:
                source = resolved.read_text(encoding="utf-8")
                ast.parse(source, filename=rel_path)
            except (UnicodeDecodeError, SyntaxError, OSError) as exc:
                gaps.append(
                    DiscoveredGap(
                        id=next_id("syntax"),
                        kind="syntax_error",
                        severity="FAIL",
                        target_path=rel_path,
                        detail=f"Python syntax/read error in {rel_path}: {exc}",
                        verify_cmd=f'python -m py_compile "{rel_path}"',
                        autofix_kind="fix_syntax",
                    )
                )


def _collect_mcp_gaps(
    root: Path,
    gaps: list[DiscoveredGap],
    next_id: Callable[[str], str],
) -> None:
    findings: list[DiagnosticFinding] = []
    mcp_info = _audit_mcp_configs(root, None, findings)

    for invalid in mcp_info.get("mcp_invalid_configs", []):
        target_path = str(invalid).split("::", 1)[0]
        gaps.append(
            DiscoveredGap(
                id=next_id("mcp"),
                kind="mcp_invalid_config",
                severity="FAIL",
                target_path=target_path,
                detail=f"Invalid MCP config: {invalid}",
                verify_cmd='python ".agents/scripts/crucible_gate.py" doctor',
                autofix_kind="fix_mcp_json",
            )
        )

    for hardcoded in mcp_info.get("mcp_hardcoded_host_paths", []):
        target_path = str(hardcoded).split("::", 1)[0]
        gaps.append(
            DiscoveredGap(
                id=next_id("mcp"),
                kind="mcp_hardcoded_path",
                severity="WARN",
                target_path=target_path,
                detail=f"Hardcoded Windows drive-letter path in {hardcoded}",
                verify_cmd='python ".agents/scripts/crucible_gate.py" doctor',
                autofix_kind="portable_mcp_path",
            )
        )


def _extract_frontmatter_depends_on_sha256_local(md_path: Path) -> dict[str, str]:
    lines = md_path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not lines or lines[0].strip() != "---":
        return {}
    fm: list[str] = []
    for line in lines[1:]:
        if line.strip() == "---":
            break
        fm.append(line)
    hashes: dict[str, str] = {}
    in_map = False
    for line in fm:
        stripped = line.strip()
        if stripped.startswith("depends_on_sha256:"):
            in_map = True
        elif in_map and line.startswith((" ", "\t")) and ":" in stripped:
            key, val = stripped.split(":", 1)
            k = key.strip().strip("'\"")
            v = val.strip().strip("'\"").lower()
            if k and v:
                hashes[k] = v
        elif in_map and stripped and not line.startswith((" ", "\t")):
            in_map = False
    return hashes


def _extract_target_from_dep_message(msg: str) -> str:
    if msg.startswith("stale artifact "):
        rest = msg[len("stale artifact ") :]
        return rest.split(" (", 1)[0].strip()
    if msg.startswith("broken depends_on in "):
        rest = msg[len("broken depends_on in ") :]
        return rest.split(": ", 1)[0].strip()
    return "Graphs"


def _collect_artifact_dep_gaps(
    root: Path,
    gaps: list[DiscoveredGap],
    next_id: Callable[[str], str],
) -> None:
    if cg is not None and hasattr(cg, "_check_artifact_dependencies"):
        failures, _warnings = cg._check_artifact_dependencies(root, strict=True)
        for msg in failures:
            target_path = _extract_target_from_dep_message(msg)
            gaps.append(
                DiscoveredGap(
                    id=next_id("dep"),
                    kind="stale_depends_on_sha256",
                    severity="FAIL",
                    target_path=target_path,
                    detail=msg,
                    verify_cmd='python ".agents/scripts/crucible_gate.py" check --strict',
                    autofix_kind="refresh_depends_on_sha256",
                )
            )
        return

    for folder_name in ARTIFACT_DOMAIN_DIRS:
        folder = root / folder_name
        if not folder.is_dir():
            continue
        for md_path in sorted(folder.rglob("*.md")):
            pinned = _extract_frontmatter_depends_on_sha256_local(md_path)
            if not pinned:
                continue
            rel_art = md_path.relative_to(root).as_posix()
            for dep, expected_sha in sorted(pinned.items()):
                dep_path = (root / dep).resolve()
                if dep_path != root and not dep_path.is_relative_to(root):
                    gaps.append(
                        DiscoveredGap(
                            id=next_id("dep"),
                            kind="stale_depends_on_sha256",
                            severity="FAIL",
                            target_path=rel_art,
                            detail=f"broken depends_on in {rel_art}: '{dep}' escapes workspace",
                            verify_cmd='python ".agents/scripts/crucible_gate.py" check --strict',
                            autofix_kind="refresh_depends_on_sha256",
                        )
                    )
                    continue
                if not dep_path.is_file():
                    gaps.append(
                        DiscoveredGap(
                            id=next_id("dep"),
                            kind="stale_depends_on_sha256",
                            severity="FAIL",
                            target_path=rel_art,
                            detail=f"broken depends_on in {rel_art}: missing '{dep}'",
                            verify_cmd='python ".agents/scripts/crucible_gate.py" check --strict',
                            autofix_kind="refresh_depends_on_sha256",
                        )
                    )
                    continue
                if _sha256_file(dep_path) != expected_sha:
                    gaps.append(
                        DiscoveredGap(
                            id=next_id("dep"),
                            kind="stale_depends_on_sha256",
                            severity="FAIL",
                            target_path=rel_art,
                            detail=f"stale artifact {rel_art} (content hash changed for '{dep}')",
                            verify_cmd='python ".agents/scripts/crucible_gate.py" check --strict',
                            autofix_kind="refresh_depends_on_sha256",
                        )
                    )


def _collect_self_model_drift_gaps(
    root: Path,
    gaps: list[DiscoveredGap],
    next_id: Callable[[str], str],
) -> None:
    atlas_path = root / "Graphs" / "00_System_Atlas_and_Neon_Handoff.md"
    crucible_dir = root / ".agents" / "scripts" / "crucible"
    if not (atlas_path.is_file() and crucible_dir.is_dir()):
        return

    atlas_text = atlas_path.read_text(encoding="utf-8", errors="replace")
    for py_file in sorted(crucible_dir.glob("*.py")):
        if py_file.name not in atlas_text:
            gaps.append(
                DiscoveredGap(
                    id=next_id("drift"),
                    kind="self_model_drift",
                    severity="WARN",
                    target_path="Graphs/00_System_Atlas_and_Neon_Handoff.md",
                    detail=f"crucible/{py_file.name} missing from Graphs/00_System_Atlas_and_Neon_Handoff.md",
                    verify_cmd='python ".agents/scripts/crucible_gate.py" check',
                    autofix_kind="update_atlas",
                )
            )


def _collect_test_quality_gaps(
    root: Path,
    gaps: list[DiscoveredGap],
    next_id: Callable[[str], str],
) -> None:
    tests_dir = root / ".agents" / "scripts" / "tests"
    if not tests_dir.is_dir() or tqg is None:
        return
    for finding in tqg.audit_paths([tests_dir]):
        f_path = Path(finding.file).resolve()
        if f_path.is_relative_to(root):
            rel_path = f_path.relative_to(root).as_posix()
        else:
            rel_path = str(finding.file).replace("\\", "/")
        gaps.append(
            DiscoveredGap(
                id=next_id("tq"),
                kind="test_quality",
                severity="FAIL",
                target_path=rel_path,
                detail=f"[{finding.rule_id}] line {finding.line}: {finding.message}",
                verify_cmd=f'python .agents/scripts/test_quality_gate.py "{rel_path}"',
                autofix_kind="fix_test_quality",
            )
        )


def _collect_orphan_module_gaps(
    scan: dict[str, Any],
    gaps: list[DiscoveredGap],
    next_id: Callable[[str], str],
) -> None:
    unit_files = sorted({str(u["file"]) for u in scan.get("units", []) if "file" in u})
    incoming: dict[str, int] = {}
    outgoing: dict[str, int] = {}
    for edge in scan.get("edges", []):
        src = str(edge.get("source_file", ""))
        dst = str(edge.get("target_file", ""))
        if src and dst and src != dst:
            outgoing[src] = outgoing.get(src, 0) + 1
            incoming[dst] = incoming.get(dst, 0) + 1

    for rel_file in unit_files:
        p = Path(rel_file)
        if p.name in ORPHAN_EXCLUDED_FILENAMES:
            continue
        if "tests" in p.parts:
            continue
        if incoming.get(rel_file, 0) == 0 and outgoing.get(rel_file, 0) == 0:
            gaps.append(
                DiscoveredGap(
                    id=next_id("orphan"),
                    kind="orphan_module",
                    severity="INFO",
                    target_path=rel_file,
                    detail=f"Standalone/unreferenced Python module '{rel_file}' has 0 incoming and 0 outgoing cross-file edges",
                    verify_cmd=f'python -m py_compile "{rel_file}"',
                    autofix_kind="review_orphan",
                )
            )


def discover_gaps(repo_root: Path, import_root: str = ".agents/scripts") -> DiscoveryReport:
    """Scan repository units/edges and deterministic integrity checks into a CampaignSpec."""
    t0 = time.perf_counter()
    root = Path(repo_root).resolve()
    scan = scan_repo_edges(root, import_root=import_root)

    gaps: list[DiscoveredGap] = []
    counters: dict[str, int] = {}

    def next_id(prefix: str) -> str:
        counters[prefix] = counters.get(prefix, 0) + 1
        return f"gap-{prefix}-{counters[prefix]:03d}"

    _collect_python_syntax_gaps(root, import_root, gaps, next_id)
    _collect_mcp_gaps(root, gaps, next_id)
    _collect_artifact_dep_gaps(root, gaps, next_id)
    _collect_self_model_drift_gaps(root, gaps, next_id)
    _collect_test_quality_gaps(root, gaps, next_id)
    _collect_orphan_module_gaps(scan, gaps, next_id)

    severity_rank = {"FAIL": 0, "WARN": 1, "INFO": 2}
    actionable = sorted(
        (g for g in gaps if g.severity in ("FAIL", "WARN")),
        key=lambda g: (severity_rank.get(g.severity, 9), g.target_path, g.id),
    )

    seen_targets: set[str] = set()
    synthesized_slices: list[dict[str, Any]] = []
    for gap in actionable:
        norm_target = Path(gap.target_path).as_posix()
        if norm_target in seen_targets:
            continue
        seen_targets.add(norm_target)
        synthesized_slices.append(
            {
                "id": gap.id,
                "target_paths": [norm_target],
                "depends_on": [],
                "verify_cmd": gap.verify_cmd,
            }
        )

    campaign_spec: dict[str, Any] = {
        "name": f"discovery-{root.name or 'repo'}",
        "repo_root": str(root),
        "allowed_roots": [str(root)],
        "max_rounds": max(12, len(synthesized_slices) * 2) if synthesized_slices else 12,
        "slices": synthesized_slices,
    }

    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 2)
    return DiscoveryReport(
        repo_root=str(root),
        import_root=import_root,
        elapsed_ms=elapsed_ms,
        unit_count=int(scan["unit_count"]),
        edge_count=int(scan["edge_count"]),
        gaps=gaps,
        campaign_spec=campaign_spec,
    )


def _resolve_slice_targets(root: Path, target_paths: list[str]) -> list[tuple[str, Path]]:
    resolved_list: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for raw_path in target_paths:
        p = Path(raw_path)
        resolved = p.resolve() if p.is_absolute() else (root / p).resolve()
        if resolved != root and not resolved.is_relative_to(root):
            raise ValueError(f"target_path '{raw_path}' escapes repo_root '{root}'")
        if resolved in seen:
            continue
        seen.add(resolved)
        rel = resolved.relative_to(root).as_posix()
        resolved_list.append((rel, resolved))
    return resolved_list


def _hash_target_state(base_root: Path, rel_paths: list[str]) -> str:
    h = hashlib.sha256()
    for rel in sorted(rel_paths):
        p = (base_root / rel).resolve()
        h.update(rel.encode("utf-8"))
        h.update(b"\x00")
        if p.is_file():
            h.update(b"1\x00")
            h.update(hashlib.sha256(p.read_bytes()).digest())
        else:
            h.update(b"0\x00")
    return h.hexdigest()


def _capture_bytes(base_root: Path, rel_paths: list[str]) -> dict[str, bytes | None]:
    out: dict[str, bytes | None] = {}
    for rel in rel_paths:
        p = (base_root / rel).resolve()
        out[rel] = p.read_bytes() if p.is_file() else None
    return out


def _compute_unified_diff(
    before_map: dict[str, bytes | None],
    after_map: dict[str, bytes | None],
) -> str:
    chunks: list[str] = []
    for rel in sorted(before_map):
        b_bytes = before_map[rel]
        a_bytes = after_map.get(rel)
        if b_bytes == a_bytes:
            continue
        b_lines = (b_bytes or b"").decode("utf-8", errors="replace").splitlines(keepends=True)
        a_lines = (a_bytes or b"").decode("utf-8", errors="replace").splitlines(keepends=True)
        fromfile = "/dev/null" if b_bytes is None else f"a/{rel}"
        tofile = "/dev/null" if a_bytes is None else f"b/{rel}"
        chunks.extend(difflib.unified_diff(b_lines, a_lines, fromfile=fromfile, tofile=tofile))
    return "".join(chunks)


def _run_withheld_holdout(exec_root: Path, node: SliceNode) -> tuple[bool, str]:
    """Run optional private withheld_verify_cmd without leaking private stdout/stderr on failure."""
    cmd = node.withheld_verify_cmd.strip()
    if not cmd:
        return True, ""
    proc = subprocess.run(
        cmd,
        cwd=exec_root,
        shell=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode == 0:
        return True, "withheld_holdout_ok"
    category = node.withheld_failure_category.strip() or "private_holdout_mismatch"
    return False, f"WITHHELD_HOLDOUT_FAILED: {category}"


def _run_slice_verify(
    exec_root: Path,
    node: SliceNode,
    verify_fn: Callable[[Path], tuple[bool, str]] | None,
) -> tuple[bool, str]:
    if verify_fn is not None:
        ok, detail = verify_fn(exec_root)
        if not ok:
            return False, str(detail)
        w_ok, w_detail = _run_withheld_holdout(exec_root, node)
        if not w_ok:
            return False, w_detail
        return True, str(detail)

    if node.verify_cmd.strip():
        proc = subprocess.run(
            node.verify_cmd,
            cwd=exec_root,
            shell=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        combined = "\n".join(part for part in (proc.stdout.strip(), proc.stderr.strip()) if part)
        if proc.returncode != 0:
            return False, (combined or f"exit_code={proc.returncode}")
        w_ok, w_detail = _run_withheld_holdout(exec_root, node)
        if not w_ok:
            return False, w_detail
        return True, (combined or f"exit_code={proc.returncode}")

    for raw_path in node.target_paths:
        target = (exec_root / raw_path).resolve()
        if not target.is_file():
            continue
        if target.suffix.lower() == ".py":
            try:
                ast.parse(target.read_text(encoding="utf-8"), filename=raw_path)
            except (SyntaxError, UnicodeDecodeError) as exc:
                return False, f"syntax error in {raw_path}: {exc}"
        elif target.suffix.lower() == ".json":
            try:
                json.loads(target.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                return False, f"json error in {raw_path}: {exc}"
    w_ok, w_detail = _run_withheld_holdout(exec_root, node)
    if not w_ok:
        return False, w_detail
    return True, "structural_ok"


def _append_trace_event(trace_path: Path, event: ReplayTraceEvent) -> None:
    p = Path(trace_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8", newline="\n") as fh:
        fh.write(json.dumps(event.to_dict(), sort_keys=True) + "\n")


def _emit_trace(
    trace_path: Path | None,
    node: SliceNode,
    input_sha256: str,
    diff: VerifiedDiff,
    round_num: int,
    status_override: str = "",
) -> None:
    if trace_path is None:
        return
    ok = diff.passed and diff.replay_verified
    event = ReplayTraceEvent(
        step_id=f"{node.id}-round-{round_num}",
        slice_id=node.id,
        input_sha256=input_sha256,
        output_sha256=diff.after_sha256 if ok else diff.before_sha256,
        exit_code=0 if ok else 1,
        status=status_override or ("PASS" if ok else "ROLLED_BACK"),
        replay_match=diff.replay_verified,
    )
    _append_trace_event(trace_path, event)


def _execute_in_worktree(
    root: Path,
    node: SliceNode,
    rel_paths: list[str],
    before_map: dict[str, bytes | None],
    before_sha256: str,
    apply_fn: Callable[[Path], None] | None,
    verify_fn: Callable[[Path], tuple[bool, str]] | None,
    checkpoint: CampaignCheckpoint,
    ratchet_check: Callable[[Path], tuple[bool, str]] | None = None,
) -> VerifiedDiff:
    if checkpoint.rounds_used >= checkpoint.max_rounds:
        return VerifiedDiff(
            slice_id=node.id,
            passed=False,
            replay_verified=False,
            rolled_back=True,
            before_sha256=before_sha256,
            after_sha256=before_sha256,
            replay_sha256="",
            diff_text="",
            worktree_used=False,
            error="HALT_MAX_ROUNDS: bounded execution limit reached",
        )

    wt_parent = Path(tempfile.mkdtemp(prefix="crucible_wt_"))
    wt_dir = wt_parent / "worktree"
    add_proc = subprocess.run(
        ["git", "worktree", "add", "--detach", str(wt_dir), "HEAD"],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if add_proc.returncode != 0:
        shutil.rmtree(wt_parent, ignore_errors=True)
        err = f"git worktree add failed: {(add_proc.stderr or add_proc.stdout).strip()}"
        checkpoint.rounds_used += 1
        checkpoint.completed_slices.pop(node.id, None)
        checkpoint.failed_slices[node.id] = hashlib.sha256(err.encode("utf-8")).hexdigest()[:16]
        return VerifiedDiff(
            slice_id=node.id,
            passed=False,
            replay_verified=False,
            rolled_back=True,
            before_sha256=before_sha256,
            after_sha256=before_sha256,
            replay_sha256="",
            diff_text="",
            worktree_used=False,
            error=err,
        )

    try:
        for rel, prev_bytes in before_map.items():
            wt_target = (wt_dir / rel).resolve()
            if prev_bytes is None:
                if wt_target.is_file():
                    wt_target.unlink()
            else:
                wt_target.parent.mkdir(parents=True, exist_ok=True)
                wt_target.write_bytes(prev_bytes)

        ok1 = False
        ok2 = False
        detail1 = ""
        detail2 = ""
        after_sha256 = before_sha256
        replay_sha256 = ""
        after_map = dict(before_map)

        try:
            if apply_fn is not None:
                apply_fn(wt_dir)
            ok1, detail1 = _run_slice_verify(wt_dir, node, verify_fn)
            after_sha256 = _hash_target_state(wt_dir, rel_paths)
            after_map = _capture_bytes(wt_dir, rel_paths)
            if ok1:
                ok2, detail2 = _run_slice_verify(wt_dir, node, verify_fn)
                replay_sha256 = _hash_target_state(wt_dir, rel_paths)
            else:
                replay_sha256 = after_sha256
        except Exception as exc:
            ok1 = False
            ok2 = False
            detail1 = f"{type(exc).__name__}: {exc}"

        replay_match = bool(ok1 and ok2 and after_sha256 == replay_sha256)
        ratchet_ok = True
        ratchet_detail = ""
        if ok1 and replay_match and ratchet_check is not None:
            ratchet_ok, ratchet_detail = ratchet_check(wt_dir)
        if ok1 and replay_match and ratchet_ok:
            diff_text = _compute_unified_diff(before_map, after_map)
            tx = TransactionBuffer(root)
            for rel, data in after_map.items():
                if data is None:
                    if (root / rel).exists():
                        tx.stage_delete(rel)
                else:
                    tx.stage_write(rel, data)
            try:
                tx.commit()
                diff = VerifiedDiff(
                    slice_id=node.id,
                    passed=True,
                    replay_verified=True,
                    rolled_back=False,
                    before_sha256=before_sha256,
                    after_sha256=after_sha256,
                    replay_sha256=replay_sha256,
                    diff_text=diff_text,
                    worktree_used=True,
                    error="",
                )
            except (TransactionValidationError, OSError, ValueError) as exc:
                diff = VerifiedDiff(
                    slice_id=node.id,
                    passed=False,
                    replay_verified=False,
                    rolled_back=True,
                    before_sha256=before_sha256,
                    after_sha256=after_sha256,
                    replay_sha256=replay_sha256,
                    diff_text="",
                    worktree_used=True,
                    error=f"atomic commit rejected: {exc}",
                )
        else:
            if not ok1:
                err = detail1 or "initial verification failed"
            elif not ok2:
                err = f"REPLAY_FAILED: {detail2}"
            elif after_sha256 != replay_sha256:
                err = f"REPLAY_DRIFT: after_sha256 {after_sha256} != replay_sha256 {replay_sha256}"
            else:
                err = ratchet_detail or "counterexample ratchet rejected candidate"
            diff = VerifiedDiff(
                slice_id=node.id,
                passed=False,
                replay_verified=False,
                rolled_back=True,
                before_sha256=before_sha256,
                after_sha256=after_sha256,
                replay_sha256=replay_sha256,
                diff_text="",
                worktree_used=True,
                error=err,
            )
    finally:
        subprocess.run(
            ["git", "worktree", "remove", "--force", str(wt_dir)],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        subprocess.run(
            ["git", "worktree", "prune"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        shutil.rmtree(wt_parent, ignore_errors=True)

    checkpoint.rounds_used += 1
    if diff.passed and diff.replay_verified:
        checkpoint.completed_slices[node.id] = compute_slice_input_sha256(node, root)
        checkpoint.failed_slices.pop(node.id, None)
    else:
        checkpoint.completed_slices.pop(node.id, None)
        checkpoint.failed_slices[node.id] = hashlib.sha256(diff.error.encode("utf-8")).hexdigest()[:16]
    return diff


def execute_replay_verified_slice(
    repo_root: Path,
    node: SliceNode,
    apply_fn: Callable[[Path], None] | None = None,
    verify_fn: Callable[[Path], tuple[bool, str]] | None = None,
    *,
    use_worktree: bool = False,
    checkpoint: CampaignCheckpoint | None = None,
    trace_path: Path | None = None,
    ratchet: CounterexampleRatchet | None = None,
    objective: str = "",
    propose_fn: Callable[[], CounterexampleProbe | None] | None = None,
    second_opinion_fn: Callable[[CounterexampleProbe], tuple[bool, str, str]] | None = None,
) -> VerifiedDiff:
    """Execute a slice in RAM or isolated git worktree, verify twice for replay determinism, and rollback on any fault."""
    root = Path(repo_root).resolve()
    targets = _resolve_slice_targets(root, node.target_paths)
    rel_paths = [rel for rel, _ in targets]

    before_map = _capture_bytes(root, rel_paths)
    before_sha256 = _hash_target_state(root, rel_paths)
    input_sha256 = compute_slice_input_sha256(node, root)
    active_cp = checkpoint if checkpoint is not None else CampaignCheckpoint(campaign_name="single-slice", max_rounds=1)

    def _run_ratchet(exec_root: Path) -> tuple[bool, str]:
        if ratchet is None:
            return True, ""
        res = ratchet.evaluate(
            exec_root=exec_root,
            objective=objective,
            propose_fn=propose_fn,
            second_opinion_fn=second_opinion_fn,
        )
        return res.passed, res.reason

    if use_worktree and (root / ".git").exists():
        diff = _execute_in_worktree(
            root=root,
            node=node,
            rel_paths=rel_paths,
            before_map=before_map,
            before_sha256=before_sha256,
            apply_fn=apply_fn,
            verify_fn=verify_fn,
            checkpoint=active_cp,
            ratchet_check=_run_ratchet if ratchet is not None else None,
        )
        status_override = "HALT_MAX_ROUNDS" if diff.error.startswith("HALT_MAX_ROUNDS") else ""
        _emit_trace(trace_path, node, input_sha256, diff, active_cp.rounds_used, status_override=status_override)
        return diff

    state: dict[str, Any] = {
        "after_sha256": before_sha256,
        "replay_sha256": "",
        "after_map": dict(before_map),
    }

    def _apply_wrapper() -> None:
        if apply_fn is not None:
            apply_fn(root)

    def _double_verify() -> tuple[bool, str]:
        ok1, detail1 = _run_slice_verify(root, node, verify_fn)
        state["after_sha256"] = _hash_target_state(root, rel_paths)
        state["after_map"] = _capture_bytes(root, rel_paths)
        if not ok1:
            state["replay_sha256"] = state["after_sha256"]
            return False, (detail1 or "initial verification failed")
        ok2, detail2 = _run_slice_verify(root, node, verify_fn)
        state["replay_sha256"] = _hash_target_state(root, rel_paths)
        if not ok2:
            return False, f"REPLAY_FAILED: {detail2}"
        if state["after_sha256"] != state["replay_sha256"]:
            return False, f"REPLAY_DRIFT: after_sha256 {state['after_sha256']} != replay_sha256 {state['replay_sha256']}"
        if ratchet is not None:
            r_ok, r_detail = _run_ratchet(root)
            if not r_ok:
                return False, r_detail
        return True, detail1

    tx_ok, tx_detail = execute_slice_transaction(
        repo_root=root,
        node=node,
        apply_fn=_apply_wrapper,
        verify_fn=_double_verify,
        checkpoint=active_cp,
    )

    if tx_ok:
        diff_text = _compute_unified_diff(before_map, state["after_map"])
        diff = VerifiedDiff(
            slice_id=node.id,
            passed=True,
            replay_verified=True,
            rolled_back=False,
            before_sha256=before_sha256,
            after_sha256=str(state["after_sha256"]),
            replay_sha256=str(state["replay_sha256"]),
            diff_text=diff_text,
            worktree_used=False,
            error="",
        )
    else:
        diff = VerifiedDiff(
            slice_id=node.id,
            passed=False,
            replay_verified=False,
            rolled_back=True,
            before_sha256=before_sha256,
            after_sha256=str(state["after_sha256"]),
            replay_sha256=str(state["replay_sha256"]),
            diff_text="",
            worktree_used=False,
            error=tx_detail,
        )

    status_override = "HALT_MAX_ROUNDS" if tx_detail.startswith("HALT_MAX_ROUNDS") else ""
    _emit_trace(trace_path, node, input_sha256, diff, active_cp.rounds_used, status_override=status_override)
    return diff


def _current_commit_sha(root: Path, fallback_sha: str) -> str:
    if (root / ".git").exists():
        proc = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    return (fallback_sha or "ram-verified")[:12]


def run_autonomous_campaign(
    repo_root: Path,
    spec: CampaignSpec,
    *,
    apply_map: dict[str, Callable[[Path], None]] | None = None,
    verify_map: dict[str, Callable[[Path], tuple[bool, str]]] | None = None,
    use_worktree: bool = False,
    cache_path: Path | None = None,
    trace_path: Path | None = None,
    ledger_path: Path | None = None,
) -> dict[str, Any]:
    """Compile & optimize a CampaignSpec, enforce LoopStateMachine + ErrorCircuitBreaker, and surface only replay-verified diffs."""
    root = Path(repo_root).resolve()
    effective_spec = CampaignSpec(
        name=spec.name,
        repo_root=str(root),
        slices=list(spec.slices),
        allowed_roots=list(spec.allowed_roots) if spec.allowed_roots else [str(root)],
        max_rounds=spec.max_rounds,
    )

    checkpoint: CampaignCheckpoint | None = None
    receipt_cache: dict[str, str] = {}
    if cache_path is not None:
        cp_loaded = load_campaign_checkpoint(cache_path)
        if cp_loaded is not None:
            checkpoint = cp_loaded
            receipt_cache = dict(cp_loaded.completed_slices)
    if checkpoint is None:
        checkpoint = CampaignCheckpoint(
            campaign_name=effective_spec.name,
            max_rounds=effective_spec.max_rounds,
        )

    compile_campaign(effective_spec)
    compiled = optimize_campaign(effective_spec, receipt_cache=receipt_cache)

    fsm = LoopStateMachine()
    breaker = ErrorCircuitBreaker(max_consecutive_failures=3)
    diffs: list[VerifiedDiff] = []
    halted_reason = ""

    if ledger_path is not None:
        for skipped in compiled.skipped_slices:
            append_ratchet_ledger(
                ledger_path,
                RatchetEntry(
                    timestamp=_utc_now_iso(),
                    campaign=effective_spec.name,
                    round_id=checkpoint.rounds_used,
                    slice_id=skipped.node.id,
                    status="SKIP_CACHED",
                    seconds=0.0,
                    after_sha256=skipped.computed_sha256,
                ),
            )

    for wave in compiled.execution_waves:
        if halted_reason:
            break
        for planned in wave:
            if checkpoint.rounds_used >= checkpoint.max_rounds:
                halted_reason = "HALT_MAX_ROUNDS"
                break
            if breaker.tripped:
                halted_reason = f"BREAKER_TRIPPED:{breaker.trip_reason}"
                break

            node = planned.node
            fsm.reset()
            fsm.plan(effective_spec.name, node.id)

            t_slice = time.perf_counter()
            apply_fn = apply_map.get(node.id) if apply_map else None
            verify_fn = verify_map.get(node.id) if verify_map else None

            diff = execute_replay_verified_slice(
                root,
                node,
                apply_fn=apply_fn,
                verify_fn=verify_fn,
                use_worktree=use_worktree,
                checkpoint=checkpoint,
                trace_path=trace_path,
            )
            diffs.append(diff)
            elapsed_sec = round(time.perf_counter() - t_slice, 4)

            ok = diff.passed and diff.replay_verified
            stage_sha = diff.after_sha256 or planned.computed_sha256 or "empty"
            fsm.stage(stage_sha)
            fsm.verify(0 if ok else 1, stage_sha, diff.error)

            if ok:
                breaker.record_success()
                commit_sha = _current_commit_sha(root, diff.after_sha256)
                fsm.commit(commit_sha)
                fsm.cache()
                if ledger_path is not None:
                    append_ratchet_ledger(
                        ledger_path,
                        RatchetEntry(
                            timestamp=_utc_now_iso(),
                            campaign=effective_spec.name,
                            round_id=checkpoint.rounds_used,
                            slice_id=node.id,
                            status="KEEP",
                            seconds=elapsed_sec,
                            commit_sha=commit_sha,
                            after_sha256=diff.after_sha256,
                        ),
                    )
            else:
                bstate = breaker.record_failure(diff.error or "slice verification failed")
                ratchet_status = "TRIPPED" if bstate.tripped else "REVERT"
                if ledger_path is not None:
                    append_ratchet_ledger(
                        ledger_path,
                        RatchetEntry(
                            timestamp=_utc_now_iso(),
                            campaign=effective_spec.name,
                            round_id=checkpoint.rounds_used,
                            slice_id=node.id,
                            status=ratchet_status,
                            seconds=elapsed_sec,
                            after_sha256=diff.before_sha256,
                            error_sha256=bstate.error_sha256 or "",
                        ),
                    )
                if bstate.tripped:
                    halted_reason = f"BREAKER_TRIPPED:{bstate.reason}"
                    break

    if cache_path is not None:
        save_campaign_checkpoint(cache_path, checkpoint)

    verified_diffs = [d.to_dict() for d in diffs if d.passed and d.replay_verified]
    all_passed = all(d.passed and d.replay_verified for d in diffs)
    return {
        "campaign": effective_spec.name,
        "repo_root": str(root),
        "ok": (not breaker.tripped) and all_passed and halted_reason == "",
        "halted_reason": halted_reason,
        "breaker_tripped": breaker.tripped,
        "breaker_reason": breaker.trip_reason,
        "rounds_used": checkpoint.rounds_used,
        "skipped_slices": [ps.node.id for ps in compiled.skipped_slices],
        "all_diffs": [d.to_dict() for d in diffs],
        "verified_diffs": verified_diffs,
    }


def _is_sha256_hex(val: str) -> bool:
    return len(val) == 64 and all(ch in "0123456789abcdef" for ch in val.lower())


def replay_trace_file(
    trace_path: Path,
    repo_root: Path,
    verify_map: dict[str, Callable[[Path], tuple[bool, str]]] | None = None,
) -> dict[str, Any]:
    """Read JSONL ReplayTraceEvent records and verify input_sha256 / deterministic replay consistency."""
    t_path = Path(trace_path)
    root = Path(repo_root).resolve()
    raw_lines = t_path.read_text(encoding="utf-8").splitlines()

    events: list[ReplayTraceEvent] = []
    mismatches: list[str] = []
    seen_determinism: dict[tuple[str, str], tuple[str, int]] = {}

    for idx, line in enumerate(raw_lines, 1):
        stripped = line.strip()
        if not stripped:
            continue
        try:
            obj = json.loads(stripped)
        except json.JSONDecodeError as exc:
            mismatches.append(f"line {idx}: invalid JSON ({exc})")
            continue
        if not isinstance(obj, dict):
            mismatches.append(f"line {idx}: expected JSON object")
            continue

        event = ReplayTraceEvent(
            step_id=str(obj.get("step_id", "")),
            slice_id=str(obj.get("slice_id", "")),
            input_sha256=str(obj.get("input_sha256", "")),
            output_sha256=str(obj.get("output_sha256", "")),
            exit_code=int(obj.get("exit_code", -1)),
            status=str(obj.get("status", "")),
            replay_match=bool(obj.get("replay_match", False)),
        )
        events.append(event)

        if not _is_sha256_hex(event.input_sha256):
            mismatches.append(f"{event.step_id}: invalid input_sha256 '{event.input_sha256}'")
        if not _is_sha256_hex(event.output_sha256):
            mismatches.append(f"{event.step_id}: invalid output_sha256 '{event.output_sha256}'")

        if event.exit_code == 0 and not event.replay_match:
            mismatches.append(f"{event.step_id}: exit_code=0 without replay_match=True")
        if event.exit_code != 0 and event.status == "PASS":
            mismatches.append(f"{event.step_id}: status=PASS with exit_code={event.exit_code}")

        det_key = (event.slice_id, event.input_sha256)
        det_val = (event.output_sha256, event.exit_code)
        if det_key in seen_determinism and seen_determinism[det_key] != det_val:
            mismatches.append(
                f"{event.step_id}: non-deterministic replay for ({event.slice_id}, {event.input_sha256[:12]})"
            )
        else:
            seen_determinism[det_key] = det_val

        if verify_map and event.slice_id in verify_map:
            ok, detail = verify_map[event.slice_id](root)
            actual_code = 0 if ok else 1
            if actual_code != event.exit_code:
                mismatches.append(
                    f"{event.step_id}: live verify exit_code={actual_code} != traced exit_code={event.exit_code} ({detail})"
                )

    return {
        "trace_path": str(t_path),
        "repo_root": str(root),
        "replay_ok": len(mismatches) == 0,
        "total": len(events),
        "mismatches": mismatches,
        "events": [e.to_dict() for e in events],
    }
