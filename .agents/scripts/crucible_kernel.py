#!/usr/bin/env python3
"""Crucible Domain Autonomous Kernel (pure CS primitives, 0 LLM calls).

Fuses five CS foundations into one closed-loop execution kernel:
1. Incremental Dependency DAG (Salsa-style dirty closure + SHA-256 staleness propagation)
2. Typed Capability & Effect System (SHA-256-bound authority tokens)
3. Value-of-Information (EVOI) Escalation Gate (zero unnecessary operator interrupts)
4. CEGIS Counterexample Extraction (exact minimal failure witnesses)
5. Control-Theory Convergence (scalar Lyapunov progress potential V(state))
"""

from __future__ import annotations

import ast
import hashlib
import re
import subprocess
import time
from collections import defaultdict, deque
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class EffectTier(str, Enum):
    READ = "READ"
    LOCAL_MUTATE = "LOCAL_MUTATE"
    LOCAL_DESTRUCTIVE = "LOCAL_DESTRUCTIVE"
    EXTERNAL_RELEASE = "EXTERNAL_RELEASE"


@dataclass(frozen=True)
class CapabilityToken:
    scope: str
    target_sha256: str
    issuer: str
    granted: bool = True


@dataclass(frozen=True)
class Unknown:
    name: str
    flips_outcome: bool
    requires_authority: bool = False
    local_probe_cost: float = 0.5


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def authorize_effect(
    effect: EffectTier,
    target_path: Path | None = None,
    token: CapabilityToken | None = None,
) -> tuple[bool, str]:
    """Enforce capability-based security: destructive/external effects require SHA-256-bound token."""
    if effect in (EffectTier.READ, EffectTier.LOCAL_MUTATE):
        return True, f"{effect.value} permitted autonomously"
    if token is None or not token.granted:
        return False, f"DENIED: {effect.value} requires granted CapabilityToken"
    if target_path is not None and target_path.is_file():
        actual_hash = sha256_file(target_path)
        if token.target_sha256 != actual_hash:
            return (
                False,
                f"DENIED: stale CapabilityToken for {target_path.name} "
                f"(token={token.target_sha256[:12]} != actual={actual_hash[:12]})",
            )
    return True, f"{effect.value} authorized by {token.issuer}"


_YAML_DEP_RE = re.compile(r"^\s*-\s+(.+?)\s*$")
_YAML_SHA_RE = re.compile(r"^\s*([^\s:][^:]*?):\s*([0-9a-fA-F]{64})\s*$")


def _parse_frontmatter_deps(md_file: Path) -> tuple[list[str], dict[str, str]]:
    """Extract depends_on and depends_on_sha256 from YAML frontmatter without external deps."""
    try:
        text = md_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return [], {}
    if not text.startswith("---"):
        return [], {}
    parts = text.split("---", 2)
    if len(parts) < 3:
        return [], {}
    fm = parts[1]
    deps: list[str] = []
    hashes: dict[str, str] = {}
    mode = ""
    for line in fm.splitlines():
        stripped = line.strip()
        if stripped == "depends_on:":
            mode = "deps"
            continue
        if stripped == "depends_on_sha256:":
            mode = "sha"
            continue
        if not line.startswith((" ", "\t")) and stripped.endswith(":"):
            mode = ""
            continue
        if mode == "deps":
            m = _YAML_DEP_RE.match(line)
            if m:
                deps.append(m.group(1).strip().strip('"').strip("'").replace("\\", "/"))
        elif mode == "sha":
            m = _YAML_SHA_RE.match(line)
            if m:
                hashes[m.group(1).strip().strip('"').strip("'").replace("\\", "/")] = m.group(2).lower()
    return deps, hashes


class IncrementalDAG:
    """Salsa-style live dependency DAG over SHA-256 artifacts and Python AST imports."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.edges: dict[str, set[str]] = defaultdict(set)  # upstream -> downstream dependents
        self.pinned_hashes: list[tuple[str, str, str]] = []  # (artifact_rel, dep_rel, expected_sha)
        self._build()

    def _build(self) -> None:
        # 1. Scan Markdown frontmatter depends_on / depends_on_sha256
        for folder in ("Personal Work", "Calgary Public Library", "Graphs", "Project"):
            base = self.root / folder
            if not base.is_dir():
                continue
            for md in base.rglob("*.md"):
                if "Archive" in md.parts or ".worktrees" in md.parts:
                    continue
                rel_art = md.relative_to(self.root).as_posix()
                deps, hashes = _parse_frontmatter_deps(md)
                for dep in deps:
                    self.edges[dep].add(rel_art)
                for dep, exp_sha in hashes.items():
                    self.edges[dep].add(rel_art)
                    self.pinned_hashes.append((rel_art, dep, exp_sha))

        # 2. Scan Python AST import graph under .agents/scripts
        scripts_dir = self.root / ".agents" / "scripts"
        if scripts_dir.is_dir():
            stem_to_rel: dict[str, str] = {}
            py_files = [
                p for p in scripts_dir.rglob("*.py")
                if not any(part in p.parts for part in ("__pycache__", ".pytest_cache", ".worktrees"))
            ]
            for pf in py_files:
                stem_to_rel[pf.stem] = pf.relative_to(self.root).as_posix()
            for pf in py_files:
                rel_mod = pf.relative_to(self.root).as_posix()
                try:
                    tree = ast.parse(pf.read_text(encoding="utf-8", errors="replace"))
                except (OSError, SyntaxError):
                    continue
                for node in ast.walk(tree):
                    names: list[str] = []
                    if isinstance(node, ast.Import):
                        names = [a.name.split(".")[-1] for a in node.names]
                    elif isinstance(node, ast.ImportFrom) and node.module:
                        names = [node.module.split(".")[-1]]
                    for nm in names:
                        upstream = stem_to_rel.get(nm)
                        if upstream and upstream != rel_mod:
                            self.edges[upstream].add(rel_mod)

    def dirty_closure(self, changed: list[str]) -> list[str]:
        """BFS propagation from changed upstream nodes to exact downstream affected closure."""
        seen: set[str] = set()
        q: deque[str] = deque(c.replace("\\", "/").removeprefix("./") for c in changed)
        downstream: set[str] = set()
        while q:
            cur = q.popleft()
            if cur in seen:
                continue
            seen.add(cur)
            for nxt in self.edges.get(cur, set()):
                downstream.add(nxt)
                if nxt not in seen:
                    q.append(nxt)
        return sorted(downstream)

    def stale_counterexamples(self) -> list[dict[str, Any]]:
        """Extract exact minimal CEGIS counterexamples for every stale SHA-256 dependency."""
        witnesses: list[dict[str, Any]] = []
        for art_rel, dep_rel, expected_sha in self.pinned_hashes:
            dep_path = self.root / dep_rel
            if not dep_path.is_file():
                witnesses.append(
                    {
                        "kind": "missing_dependency",
                        "artifact": art_rel,
                        "dependency": dep_rel,
                        "expected_sha256": expected_sha,
                        "actual_sha256": None,
                    }
                )
                continue
            actual_sha = sha256_file(dep_path)
            if actual_sha != expected_sha:
                witnesses.append(
                    {
                        "kind": "stale_sha256",
                        "artifact": art_rel,
                        "dependency": dep_rel,
                        "expected_sha256": expected_sha,
                        "actual_sha256": actual_sha,
                    }
                )
        return witnesses


def evaluate_evoi(unknowns: list[Unknown]) -> dict[str, list[str]]:
    """Decision-theoretic Value of Information (EVOI) routing for unknowns."""
    autonomous: list[str] = []
    local_probe: list[str] = []
    escalate: list[str] = []
    for u in unknowns:
        if u.requires_authority:
            escalate.append(f"{u.name} (authority_required)")
        elif not u.flips_outcome:
            autonomous.append(u.name)
        elif u.local_probe_cost <= 1.0:
            local_probe.append(f"{u.name} (probe_cost={u.local_probe_cost})")
        else:
            escalate.append(f"{u.name} (decision_fork)")
    return {
        "resolve_autonomously": autonomous,
        "run_local_probe": local_probe,
        "escalate_to_operator": escalate,
    }


def step_lyapunov_potential(prev_v: int | None, cur_v: int) -> str:
    """Control-theory convergence verdict on scalar progress potential V(state)."""
    if cur_v == 0:
        return "VERIFIED_DONE"
    if prev_v is None or cur_v < prev_v:
        return "CONVERGING"
    return "HALT_OSCILLATION"


def _git_dirty_files(root: Path) -> list[str]:
    proc = subprocess.run(
        ["git", "-C", str(root), "status", "--porcelain"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if proc.returncode != 0:
        return []
    out: list[str] = []
    for line in proc.stdout.splitlines():
        if len(line) >= 4:
            p = line[3:].strip()
            if " -> " in p:
                p = p.split(" -> ", 1)[1].strip()
            if p:
                out.append(p.replace("\\", "/").removeprefix("./"))
    return sorted(set(out))


def _syntax_counterexamples(root: Path, files: list[str]) -> list[dict[str, Any]]:
    witnesses: list[dict[str, Any]] = []
    for rel in files:
        if not rel.endswith(".py"):
            continue
        p = root / rel
        if not p.is_file():
            continue
        try:
            ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
        except SyntaxError as exc:
            witnesses.append({"kind": "syntax_error", "file": rel, "line": exc.lineno, "msg": exc.msg})
    return witnesses


def autofix_stale_sha256(root: Path) -> list[dict[str, str]]:
    """Mechanically repair stale depends_on_sha256 entries in YAML frontmatter (0 LLM tokens)."""
    root = root.resolve()
    dag = IncrementalDAG(root)
    repaired: list[dict[str, str]] = []
    for w in dag.stale_counterexamples():
        if w["kind"] != "stale_sha256" or not w.get("actual_sha256"):
            continue
        art_path = root / w["artifact"]
        if not art_path.is_file():
            continue
        text = art_path.read_text(encoding="utf-8", errors="replace")
        old_sha = w["expected_sha256"]
        new_sha = w["actual_sha256"]
        if old_sha in text:
            art_path.write_text(text.replace(old_sha, new_sha, 1), encoding="utf-8")
            repaired.append({"artifact": w["artifact"], "dependency": w["dependency"], "new_sha256": new_sha})
    return repaired


def run_kernel(
    root: Path,
    outcome: str = "",
    *,
    changed_files: list[str] | None = None,
    requested_effects: list[tuple[EffectTier, Path | None, CapabilityToken | None]] | None = None,
    unknowns: list[Unknown] | None = None,
    prev_potential: int | None = None,
    autofix: bool = False,
) -> dict[str, Any]:
    """Execute one closed-loop kernel evaluation over DAG, capabilities, EVOI, CEGIS, and Lyapunov V(state)."""
    t0 = time.perf_counter()
    root = root.resolve()
    changes = changed_files if changed_files is not None else _git_dirty_files(root)
    autofixed = autofix_stale_sha256(root) if autofix else []

    dag = IncrementalDAG(root)
    dirty_downstream = dag.dirty_closure(changes)
    stale_witnesses = dag.stale_counterexamples()
    syntax_witnesses = _syntax_counterexamples(root, changes)

    capability_denials: list[str] = []
    for eff, target_path, tok in requested_effects or []:
        ok, msg = authorize_effect(eff, target_path, tok)
        if not ok:
            capability_denials.append(msg)

    evoi = evaluate_evoi(unknowns or [])
    counterexamples = stale_witnesses + syntax_witnesses
    potential_v = len(counterexamples) + len(capability_denials) + len(evoi["escalate_to_operator"])
    convergence = step_lyapunov_potential(prev_potential, potential_v)

    if capability_denials or evoi["escalate_to_operator"]:
        status = "OPERATOR_ESCALATION"
    elif convergence == "HALT_OSCILLATION":
        status = "HALT_OSCILLATION"
    elif counterexamples:
        status = "AUTONOMOUS_REPAIR"
    else:
        status = "VERIFIED_DONE"

    return {
        "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        "outcome": outcome.strip() or "(working_tree_check)",
        "status": status,
        "potential_v": potential_v,
        "convergence": convergence,
        "changed_files": changes,
        "dirty_closure": dirty_downstream,
        "autofixed": autofixed,
        "counterexamples": counterexamples,
        "capability_denials": capability_denials,
        "evoi": evoi,
    }
