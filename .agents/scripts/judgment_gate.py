#!/usr/bin/env python3
"""Hard-layer process judgment & system-pointer enforcement hook (JG-01..JG-04).

Enforces deterministic runtime floors so upfront process judgment and GEMINI.md
system pointers are backed by code rather than prose alone:

- JG-01 (Pointer Integrity): Every executable script/JSON pointer declared in
  GEMINI.md's `## System Pointers` table must exist on disk and parse cleanly.
- JG-02 (No Reflexive Skill Chaining): Hard-denies reading a 3rd+ SKILL.md in
  the same turn without an intervening edit or command action.
- JG-03 (No Serial Remote API Polling): Hard-denies a 3rd+ `gh api` call to the
  same `repos/<owner>/<repo>` in the same turn (use one local `git fetch` +
  `git show`/`git diff` instead).
- JG-04 (Verify Once Per Slice): Hard-denies re-running the same verification
  command class (`doctor`, `check`, `unittest`/`pytest`, `mutation_gate`) after
  it already succeeded with zero file edits in between. Any edit resets it.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import sys
from pathlib import Path
from typing import Any

READ_TOOLS = frozenset({"read_file", "view_file"})
WRITE_TOOLS = frozenset({
    "write_file",
    "edit_file",
    "write_to_file",
    "replace_file_content",
    "multi_replace_file_content",
})
SHELL_TOOLS = frozenset({"run_command", "command"})

MAX_SKILLS_PER_TURN = 2
MAX_GH_API_PER_REPO_PER_TURN = 2

POINTER_ROW_RE = re.compile(r"`([^`]+\.(?:py|json|ps1))`")
GH_API_REPO_RE = re.compile(r"\bgh\s+api\s+['\"]?/?repos/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", re.IGNORECASE)

VERIFY_CLASSES: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("doctor", re.compile(r"\bcrucible_gate\.py['\"]?\s+doctor\b", re.IGNORECASE)),
    ("check", re.compile(r"\bcrucible_gate\.py['\"]?\s+check\b", re.IGNORECASE)),
    ("mutation_gate", re.compile(r"\bmutation_gate\.py\b", re.IGNORECASE)),
    ("unittest", re.compile(r"\b(?:python3?|py)\s+-m\s+unittest\b|\bpytest\b", re.IGNORECASE)),
)


def default_gemini_md() -> Path:
    env_override = os.environ.get("CRUCIBLE_GEMINI_MD")
    if env_override:
        return Path(env_override)
    return Path.home() / ".gemini" / "GEMINI.md"


def extract_system_pointers(gemini_md_path: Path) -> list[Path]:
    """Extract executable pointer paths declared under `## System Pointers` in GEMINI.md."""
    if not gemini_md_path.is_file():
        return []
    text = gemini_md_path.read_text(encoding="utf-8", errors="replace")
    in_section = False
    pointers: list[Path] = []
    seen: set[str] = set()
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            in_section = stripped.lower().startswith("## system pointers")
            continue
        if not in_section:
            continue
        for match in POINTER_ROW_RE.finditer(line):
            raw = match.group(1).strip()
            expanded = Path(os.path.expanduser(raw))
            key = os.path.normcase(str(expanded))
            if key not in seen:
                seen.add(key)
                pointers.append(expanded)
    return pointers


def check_system_pointers(gemini_md_path: Path | None = None) -> tuple[int, list[str]]:
    """JG-01: Verify every declared pointer in GEMINI.md exists, is non-empty, and parses."""
    md_path = gemini_md_path or default_gemini_md()
    if not md_path.is_file():
        return 0, [f"JG-01: GEMINI.md not found at {md_path}"]
    pointers = extract_system_pointers(md_path)
    if not pointers:
        return 0, [f"JG-01: No executable paths declared under `## System Pointers` in {md_path.name}"]

    errors: list[str] = []
    for target in pointers:
        if not target.is_file():
            errors.append(f"JG-01: Missing system pointer target: {target}")
            continue
        if target.stat().st_size == 0:
            errors.append(f"JG-01: Empty system pointer target: {target}")
            continue
        suffix = target.suffix.lower()
        try:
            content = target.read_text(encoding="utf-8")
        except OSError as exc:
            errors.append(f"JG-01: Unreadable system pointer {target}: {exc}")
            continue
        if suffix == ".py":
            try:
                ast.parse(content, filename=str(target))
            except SyntaxError as exc:
                errors.append(f"JG-01: SyntaxError in {target.name}:{exc.lineno}: {exc.msg}")
        elif suffix == ".json":
            try:
                json.loads(content)
            except json.JSONDecodeError as exc:
                errors.append(f"JG-01: Invalid JSON in {target.name}: {exc.msg}")
    return len(pointers), errors


def _state_file(payload: dict[str, Any]) -> Path | None:
    art_dir = payload.get("artifactDirectoryPath")
    if not isinstance(art_dir, str) or not art_dir.strip():
        return None
    return Path(art_dir) / "judgment-floor-state.json"


def _empty_state(conv_id: str, prompt_digest: str = "") -> dict[str, Any]:
    return {
        "conversation_id": conv_id,
        "prompt_digest": prompt_digest,
        "edit_seq": 0,
        "skills_read": [],
        "gh_api_repos": {},
        "verified_at_edit_seq": {},
    }


def _load_state(payload: dict[str, Any]) -> dict[str, Any]:
    conv_id = str(payload.get("conversationId") or "default")
    sf = _state_file(payload)
    if sf is None or not sf.is_file():
        return _empty_state(conv_id)
    try:
        data = json.loads(sf.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return _empty_state(conv_id)
    if not isinstance(data, dict) or data.get("conversation_id") != conv_id:
        return _empty_state(conv_id)
    for k, default in _empty_state(conv_id).items():
        if k not in data:
            data[k] = default
    return data


def handle_pre_invocation(payload: dict[str, Any]) -> dict[str, Any]:
    """Reset per-turn budgets cleanly whenever a new user prompt arrives."""
    prompt = str(payload.get("lastUserInput") or "")
    digest = hashlib.sha256(prompt.encode("utf-8", errors="replace")).hexdigest()[:16] if prompt else ""
    state = _load_state(payload)
    if digest and digest != state.get("prompt_digest"):
        state["prompt_digest"] = digest
        state["skills_read"] = []
        state["gh_api_repos"] = {}
        _save_state(payload, state)
    return {"injectSteps": []}


def _save_state(payload: dict[str, Any], state: dict[str, Any]) -> None:
    sf = _state_file(payload)
    if sf is None:
        return
    try:
        sf.parent.mkdir(parents=True, exist_ok=True)
        tmp = sf.with_suffix(".tmp")
        tmp.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(tmp, sf)
    except OSError:
        pass


def _extract_path(args: dict[str, Any]) -> str:
    for key in ("Path", "TargetFile", "file_path", "path", "AbsolutePath"):
        val = args.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _is_skill_doc(path_str: str) -> bool:
    norm = path_str.replace("\\", "/").lower()
    return norm.endswith("/skill.md") or norm == "skill.md"


def _classify_verify_command(cmd: str) -> str | None:
    for label, pattern in VERIFY_CLASSES:
        if pattern.search(cmd):
            return label
    return None


def _extract_gh_api_repo(cmd: str) -> str | None:
    m = GH_API_REPO_RE.search(cmd)
    return m.group(1).lower() if m else None


def handle_session_start(payload: dict[str, Any], *, gemini_md_path: Path | None = None) -> dict[str, Any]:
    count, errors = check_system_pointers(gemini_md_path)
    if errors:
        msg = "HOLD [JG-01 Pointer Integrity]: " + "; ".join(errors[:4])
    else:
        msg = (
            f"JUDGMENT FLOOR ACTIVE [JG-01..JG-04]: {count}/{count} GEMINI.md system pointers verified on disk | "
            f"Hard budgets: <= {MAX_SKILLS_PER_TURN} skills/turn before acting (JG-02), "
            f"<= {MAX_GH_API_PER_REPO_PER_TURN} gh api calls/repo (JG-03), verify once per edit slice (JG-04)."
        )
    return {"injectSteps": [{"systemMessage": {"systemMessage": msg}}]}


def handle_pre(payload: dict[str, Any]) -> dict[str, Any]:
    tool = payload.get("toolCall") or {}
    name = str(tool.get("name") or "")
    args = tool.get("args") if isinstance(tool.get("args"), dict) else {}
    state = _load_state(payload)

    # JG-02: Prevent reflexive skill-chaining without acting
    if name in READ_TOOLS:
        target = _extract_path(args)
        if target and _is_skill_doc(target):
            norm_skill = os.path.normcase(os.path.abspath(os.path.expanduser(target)))
            already = list(state.get("skills_read") or [])
            if norm_skill not in already and len(already) >= MAX_SKILLS_PER_TURN:
                return {
                    "decision": "deny",
                    "reason": (
                        f"JG-02 (No Reflexive Skill Chaining): {len(already)} distinct SKILL.md files already loaded "
                        "this turn without an edit or command action. Stop chaining skills — act on the selected "
                        "method or finish the current slice first."
                    ),
                }
        return {"decision": "allow"}

    if name in SHELL_TOOLS:
        cmd = str(args.get("CommandLine") or args.get("command") or args.get("cmd") or "")

        # JG-03: Block 3rd+ serial `gh api` call to the same repo in one turn
        repo = _extract_gh_api_repo(cmd)
        if repo is not None:
            counts = state.get("gh_api_repos") or {}
            prior = int(counts.get(repo, 0))
            if prior >= MAX_GH_API_PER_REPO_PER_TURN:
                return {
                    "decision": "deny",
                    "reason": (
                        f"JG-03 (No Serial Remote API Polling): Already ran {prior} `gh api` calls against "
                        f"`{repo}` this turn. Use ONE local `git fetch` + `git show`/`git diff` instead of "
                        "file-by-file remote API calls."
                    ),
                }

        # JG-04: Block redundant verification passes when 0 edits occurred since last PASS
        vclass = _classify_verify_command(cmd)
        if vclass is not None:
            verified_map = state.get("verified_at_edit_seq") or {}
            last_seq = verified_map.get(vclass)
            cur_seq = int(state.get("edit_seq", 0))
            if isinstance(last_seq, int) and last_seq == cur_seq:
                return {
                    "decision": "deny",
                    "reason": (
                        f"JG-04 (Verify Once Per Slice): `{vclass}` already passed at edit_seq={cur_seq} "
                        "with zero file edits since. Batch edits first and verify once at the slice boundary."
                    ),
                }

    return {"decision": "allow"}


def handle_post(payload: dict[str, Any]) -> dict[str, Any]:
    tool = payload.get("toolCall") or {}
    name = str(tool.get("name") or "")
    args = tool.get("args") if isinstance(tool.get("args"), dict) else {}
    failed = bool(payload.get("error"))
    state = _load_state(payload)

    if name in WRITE_TOOLS and not failed:
        state["edit_seq"] = int(state.get("edit_seq", 0)) + 1
        # Acting resets the skill-chaining counter for the next step
        state["skills_read"] = []
        _save_state(payload, state)
        return {}

    if name in READ_TOOLS and not failed:
        target = _extract_path(args)
        if target and _is_skill_doc(target):
            norm_skill = os.path.normcase(os.path.abspath(os.path.expanduser(target)))
            already = list(state.get("skills_read") or [])
            if norm_skill not in already:
                already.append(norm_skill)
                state["skills_read"] = already
                _save_state(payload, state)
        return {}

    if name in SHELL_TOOLS and not failed:
        cmd = str(args.get("CommandLine") or args.get("command") or args.get("cmd") or "")
        changed = False
        repo = _extract_gh_api_repo(cmd)
        if repo is not None:
            counts = dict(state.get("gh_api_repos") or {})
            counts[repo] = int(counts.get(repo, 0)) + 1
            state["gh_api_repos"] = counts
            changed = True
        vclass = _classify_verify_command(cmd)
        if vclass is not None:
            verified_map = dict(state.get("verified_at_edit_seq") or {})
            verified_map[vclass] = int(state.get("edit_seq", 0))
            state["verified_at_edit_seq"] = verified_map
            changed = True
        # Non-skill command action clears skill-chaining counter so agent can act -> load next needed skill
        if state.get("skills_read"):
            state["skills_read"] = []
            changed = True
        if changed:
            _save_state(payload, state)
    return {}


def handle_stop(payload: dict[str, Any], *, gemini_md_path: Path | None = None) -> dict[str, Any]:
    if payload.get("terminationReason") not in ("NO_TOOL_CALL", "model_stop", None):
        return {"decision": "allow"}
    attempt = payload.get("executionNum", 0)
    if not isinstance(attempt, int) or attempt >= 3:
        return {"decision": "allow"}
    _, errors = check_system_pointers(gemini_md_path)
    if errors:
        return {
            "decision": "continue",
            "reason": "JG-01 Pointer Integrity failed: " + "; ".join(errors[:4]),
        }
    return {"decision": "allow"}


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in ("session-start", "pre-invocation", "pre", "post", "stop"):
        sys.stdout.write(json.dumps({"decision": "allow"}) + "\n")
        return 0
    mode = sys.argv[1]
    raw = sys.stdin.read().strip()
    try:
        payload = json.loads(raw) if raw else {}
        if not isinstance(payload, dict):
            payload = {}
    except json.JSONDecodeError:
        payload = {}

    handlers = {
        "session-start": handle_session_start,
        "pre-invocation": handle_pre_invocation,
        "pre": handle_pre,
        "post": handle_post,
        "stop": handle_stop,
    }
    result = handlers[mode](payload)
    sys.stdout.write(json.dumps(result, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
