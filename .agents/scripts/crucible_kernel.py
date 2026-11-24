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
import json
import os
import re
import shlex
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


OPERATOR_GRANTS_REL_PATH = Path(".agents") / "operator_grants.json"
_FORBIDDEN_ISSUERS = frozenset({"", "model", "agent", "assistant", "llm", "subagent", "self", "auto"})


@dataclass(frozen=True)
class CapabilityToken:
    scope: str
    target_sha256: str
    issuer: str
    granted: bool = True
    grant_id: str = ""



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
    *,
    root: Path | None = None,
) -> tuple[bool, str]:
    """Enforce capability-based security: destructive/external effects require verified operator grant."""
    if effect in (EffectTier.READ, EffectTier.LOCAL_MUTATE):
        return True, f"{effect.value} permitted autonomously"
    if token is None or not token.granted:
        return False, f"DENIED: {effect.value} requires granted CapabilityToken"
    if token.issuer.strip().lower() in _FORBIDDEN_ISSUERS:
        return (
            False,
            f"DENIED: forbidden model/self issuer '{token.issuer}' cannot authorize {effect.value}",
        )
    if not token.grant_id.strip() or root is None:
        return (
            False,
            f"DENIED: unbacked in-memory CapabilityToken; {effect.value} requires verified grant_id in .agents/operator_grants.json",
        )

    root_resolved = root.resolve()
    grants_path = root_resolved / OPERATOR_GRANTS_REL_PATH
    try:
        data = json.loads(grants_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False, "DENIED: missing or invalid .agents/operator_grants.json"
    if not isinstance(data, dict) or not isinstance(data.get("grants", []), list):
        return False, "DENIED: missing or invalid .agents/operator_grants.json"

    grant = next(
        (g for g in data.get("grants", []) if isinstance(g, dict) and g.get("grant_id") == token.grant_id),
        None,
    )
    if grant is None or grant.get("granted") is not True:
        return (
            False,
            f"DENIED: grant_id '{token.grant_id}' not found or revoked in .agents/operator_grants.json",
        )

    grant_issuer = str(grant.get("issuer", ""))
    if (
        grant.get("effect") != effect.value
        or grant.get("scope") != token.scope
        or grant_issuer.strip().lower() in _FORBIDDEN_ISSUERS
        or grant_issuer != token.issuer
        or str(grant.get("target_sha256", "")).lower() != token.target_sha256.lower()
    ):
        return False, f"DENIED: grant record mismatch for '{token.grant_id}'"

    if grant.get("target_path") and target_path is not None:
        grant_target = (root_resolved / str(grant["target_path"])).resolve()
        req_target = (root_resolved / target_path).resolve()
        if grant_target != req_target:
            return False, f"DENIED: grant record mismatch for '{token.grant_id}'"

    if target_path is not None:
        eff_target = target_path if target_path.is_absolute() else (root_resolved / target_path)
        if eff_target.is_file():
            actual_hash = sha256_file(eff_target)
            if token.target_sha256.lower() != actual_hash.lower():
                return (
                    False,
                    f"DENIED: stale CapabilityToken for {target_path.name} "
                    f"(token={token.target_sha256[:12]} != actual={actual_hash[:12]})",
                )
    return True, f"{effect.value} authorized by verified operator grant {token.grant_id} ({token.issuer})"


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

        # 3. Static config, verification, and CI dependency edges
        static_edges = {
            "requirements.txt": (
                ".github/workflows/crucible-ci.yml",
                ".agents/scripts/tests/test_portable_verify.py",
            ),
            ".agents/scripts/verify_all.py": (
                "scripts/verify_all.ps1",
                ".github/workflows/crucible-ci.yml",
            ),
        }
        for upstream, downstreams in static_edges.items():
            for downstream in downstreams:
                if (self.root / downstream).is_file():
                    self.edges[upstream].add(downstream)

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
        return "ZERO_HYGIENE_POTENTIAL"
    if prev_v is None or cur_v < prev_v:
        return "CONVERGING"
    return "HALT_OSCILLATION"


_NON_INDEPENDENT_REVIEWERS = frozenset({"", "self", "author", "same-agent", "model-self"})


def validate_review_receipt(root: Path, receipt: dict[str, Any] | None) -> tuple[bool, str]:
    """Verify independent review receipt bound by SHA-256 hashes of reviewed files."""
    if not isinstance(receipt, dict):
        return False, "missing or invalid review_receipt"
    if receipt.get("status") != "PASS":
        return False, f"review_receipt status is '{receipt.get('status')}', expected 'PASS'"
    reviewer = str(receipt.get("reviewer", "")).strip()
    if reviewer.lower() in _NON_INDEPENDENT_REVIEWERS:
        return False, f"non-independent or missing reviewer '{reviewer}'"
    reviewed_sha256 = receipt.get("reviewed_sha256")
    if not isinstance(reviewed_sha256, dict) or len(reviewed_sha256) == 0:
        return False, "review_receipt missing non-empty reviewed_sha256"
    root_resolved = root.resolve()
    for rel_path, expected_sha in reviewed_sha256.items():
        candidate = (root_resolved / str(rel_path)).resolve()
        try:
            candidate.relative_to(root_resolved)
        except ValueError:
            return False, f"reviewed path escapes root: {rel_path}"
        if not candidate.is_file():
            return False, f"reviewed file missing: {rel_path}"
        actual_sha = sha256_file(candidate).lower()
        if actual_sha != str(expected_sha).lower():
            return (
                False,
                f"stale review_receipt for {rel_path} "
                f"(expected={str(expected_sha)[:12]} != actual={actual_sha[:12]})",
            )
    return True, f"verified by {reviewer}"


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


def _split_verify_cmd(verify_cmd: str) -> list[str]:
    parts = shlex.split(verify_cmd, posix=(os.name != "nt"))
    if os.name == "nt":
        return [
            p[1:-1] if len(p) >= 2 and p[0] == p[-1] and p[0] in ('"', "'") else p
            for p in parts
        ]
    return parts


def run_kernel(
    root: Path,
    outcome: str = "",
    *,
    changed_files: list[str] | None = None,
    requested_effects: list[tuple[EffectTier, Path | None, CapabilityToken | None]] | None = None,
    unknowns: list[Unknown] | None = None,
    prev_potential: int | None = None,
    autofix: bool = False,
    verify_cmd: str = "",
    review_receipt: dict[str, Any] | None = None,
    consequential: bool = True,
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
        ok, msg = authorize_effect(eff, target_path, tok, root=root)
        if not ok:
            capability_denials.append(msg)

    evoi = evaluate_evoi(unknowns or [])
    counterexamples = stale_witnesses + syntax_witnesses
    potential_v = len(counterexamples) + len(capability_denials) + len(evoi["escalate_to_operator"])
    convergence = step_lyapunov_potential(prev_potential, potential_v)

    verify_ran = False
    verify_exit_code: int | None = None
    verify_detail = ""
    if potential_v == 0 and verify_cmd.strip():
        verify_ran = True
        try:
            args = _split_verify_cmd(verify_cmd)
            proc = subprocess.run(
                args,
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=60,
                check=False,
            )
            verify_exit_code = proc.returncode
            verify_detail = (proc.stdout or proc.stderr or "").strip()
        except subprocess.TimeoutExpired:
            verify_exit_code = 124
            verify_detail = "verify_cmd timed out after 60s"
        except (ValueError, OSError) as exc:
            verify_exit_code = 127
            verify_detail = f"verify_cmd execution failed: {exc}"

    review_valid, review_detail = validate_review_receipt(root, review_receipt)
    hygiene_ok = potential_v == 0
    checks_passed = hygiene_ok and (not verify_ran or verify_exit_code == 0)
    outcome_verified = bool(
        hygiene_ok
        and outcome.strip()
        and verify_ran
        and verify_exit_code == 0
        and (review_valid if consequential else True)
    )

    if capability_denials or evoi["escalate_to_operator"]:
        status = "OPERATOR_ESCALATION"
    elif convergence == "HALT_OSCILLATION":
        status = "HALT_OSCILLATION"
    elif counterexamples:
        status = "AUTONOMOUS_REPAIR"
    elif verify_ran and verify_exit_code != 0:
        status = "VERIFY_FAILED"
    elif outcome_verified:
        status = "OUTCOME_VERIFIED"
    else:
        status = "CHECKS_PASSED"

    return {
        "elapsed_ms": round((time.perf_counter() - t0) * 1000.0, 2),
        "outcome": outcome.strip() or "(working_tree_check)",
        "status": status,
        "potential_v": potential_v,
        "convergence": convergence,
        "hygiene_ok": hygiene_ok,
        "checks_passed": checks_passed,
        "outcome_verified": outcome_verified,
        "verify_ran": verify_ran,
        "verify_exit_code": verify_exit_code,
        "verify_detail": verify_detail,
        "review_valid": review_valid,
        "review_detail": review_detail,
        "changed_files": changes,
        "dirty_closure": dirty_downstream,
        "autofixed": autofixed,
        "counterexamples": counterexamples,
        "capability_denials": capability_denials,
        "evoi": evoi,
    }


_INTAKE_DOMAIN_SIGNALS: dict[str, tuple[tuple[str, re.Pattern[str]], ...]] = {
    "crucible_engine": tuple(
        (label, re.compile(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])", re.IGNORECASE))
        for label, pattern in (
            ("crucible_kernel", r"crucible[_ -]?kernel"),
            ("crucible_gate", r"crucible[_ -]?gate"),
            ("crucible_index", r"crucible[_ -]?index"),
            ("crucible_engine", r"crucible[_ -]?engine"),
            ("crucible-ci", r"crucible[_ -]?ci"),
            ("verify_all", r"verify[_ -]?all"),
            ("dirty_closure", r"dirty[_ -]?closure"),
            ("tx_patch", r"tx[_ -]?patch"),
            ("campaign_ir", r"campaign[_ -]?ir"),
            ("ram_ml_engine", r"ram[_ -]?ml[_ -]?engine"),
            ("pytest", r"pytest"),
            ("kernel", r"kernel"),
            ("dag", r"dag"),
            ("capability_token", r"capability[_ -]?tokens?"),
            ("cegis", r"cegis"),
            ("lyapunov", r"lyapunov"),
            ("evoi", r"evoi"),
            ("worktree", r"worktrees?"),
            ("pre-commit", r"pre[_ -]?commit"),
            ("dependency_graph", r"dependency[_ -]?graph"),
            ("requirements.txt", r"requirements\.txt"),
            ("ci", r"ci"),
        )
    ),
    "writers_room": tuple(
        (label, re.compile(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])", re.IGNORECASE))
        for label, pattern in (
            ("writers_room", r"writers[_ -]?room"),
            ("cover_letter", r"cover[_ -]?letters?"),
            ("documentary", r"documentar(?:y|ies)"),
            ("treatment", r"treatments?"),
            ("scriptwriting", r"scriptwriting"),
            ("paper_edit", r"paper[_ -]?edits?"),
            ("production_brief", r"production[_ -]?briefs?"),
            ("manuscript", r"manuscripts?"),
            ("prose", r"prose"),
            ("draft", r"drafts?"),
            ("outline", r"outlines?"),
            ("copyedit", r"copyedit(?:ing)?"),
            ("memo", r"memos?"),
            ("narrative", r"narratives?"),
            ("editorial", r"editorial"),
            ("chapter", r"chapters?"),
            ("essay", r"essays?"),
            ("docx", r"docx"),
            ("script", r"scripts?"),
        )
    ),
    "story_lane": tuple(
        (label, re.compile(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])", re.IGNORECASE))
        for label, pattern in (
            ("story_lane", r"story[_ -]?lane"),
            ("transcript", r"transcripts?"),
            ("timecode", r"timecodes?"),
            ("timestamp", r"timestamps?"),
            ("clip_selection", r"clip[_ -]?selections?"),
            ("clip_manifest", r"clip[_ -]?manifests?"),
            ("cut_approval", r"cut[_ -]?approvals?"),
            ("video_clip", r"video[_ -]?clips?"),
            ("b-roll", r"b[_ -]?roll"),
            ("soundbite", r"soundbites?"),
            ("caption", r"captions?"),
            ("subtitles", r"subtitles?"),
            ("rough_cut", r"rough[_ -]?cuts?"),
            ("fine_cut", r"fine[_ -]?cuts?"),
            ("footage", r"footage"),
            ("interview_clip", r"interview[_ -]?clips?"),
        )
    ),
    "meeting_prep": tuple(
        (label, re.compile(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])", re.IGNORECASE))
        for label, pattern in (
            ("meeting_prep", r"meeting[_ -]?prep"),
            ("live_room_cockpit", r"live[_ -]?room[_ -]?cockpit"),
            ("cold-start_shield", r"cold[_ -]?start[_ -]?shield"),
            ("pre-read", r"pre[_ -]?reads?"),
            ("agenda", r"agendas?"),
            ("stakeholder", r"stakeholders?"),
            ("meeting", r"meetings?"),
            ("attendees", r"attendees"),
            ("talking_points", r"talking[_ -]?points"),
            ("briefing_packet", r"briefing[_ -]?packets?"),
            ("standup", r"standups?"),
            ("board_meeting", r"board[_ -]?meetings?"),
            ("committee", r"committees?"),
        )
    ),
    "observatory": tuple(
        (label, re.compile(rf"(?<![a-z0-9]){pattern}(?![a-z0-9])", re.IGNORECASE))
        for label, pattern in (
            ("observatory", r"observatory"),
            ("prior-art", r"prior[_ -]?art"),
            ("melt-diff", r"melt[_ -]?diff"),
            ("melt-scan", r"melt[_ -]?scan"),
            ("outcome_ledger", r"outcome[_ -]?ledger"),
            ("capability_map", r"capability[_ -]?map"),
            ("telemetry", r"telemetry"),
            ("observability", r"observability"),
            ("causal_trace", r"causal[_ -]?trace"),
            ("benchmark", r"benchmarks?"),
            ("audit_trail", r"audit[_ -]?trail"),
            ("archaeology", r"archaeology"),
            ("repo_scan", r"repo[_ -]?scan"),
        )
    ),
}


def classify_intake_intent(task_text: str) -> dict[str, Any]:
    """Score domain signals and abstain as ambiguous on empty or tied intake prompts."""
    text = task_text.strip() if isinstance(task_text, str) else ""
    scores: dict[str, int] = {}
    matched_by_domain: dict[str, list[str]] = {}
    for dom, patterns in _INTAKE_DOMAIN_SIGNALS.items():
        hits = [label for label, regex in patterns if regex.search(text)]
        scores[dom] = len(hits)
        matched_by_domain[dom] = hits

    ranked = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    top_domain, top_score = ranked[0]
    second_score = ranked[1][1] if len(ranked) > 1 else 0
    total_score = sum(scores.values())

    ambiguous = (top_score == 0) or (top_score == second_score)
    if ambiguous:
        domain = "ambiguous"
        confidence = 0.0
    else:
        domain = top_domain
        confidence = round((top_score - second_score) / total_score, 4)

    matched_signals = sorted({sig for hits in matched_by_domain.values() for sig in hits})
    return {
        "domain": domain,
        "ambiguous": ambiguous,
        "confidence": confidence,
        "matched_signals": matched_signals,
        "scores": scores,
    }
