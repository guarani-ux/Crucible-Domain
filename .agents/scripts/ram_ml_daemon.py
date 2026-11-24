#!/usr/bin/env python3
"""Persistent localhost-only in-RAM ML daemon for <10ms hot queries.

Keeps the repo's AST index, git co-change matrix, and trained LogisticRegression /
IsolationForest models hot in RAM over 127.0.0.1 JSON-lines TCP.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import socket
import socketserver
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import ram_ml_engine  # noqa: E402

STATE_FILE_REL = Path(".agents") / ".ml_daemon.json"


def _git_dir_paths(root: Path) -> list[Path]:
    dotgit = root / ".git"
    if dotgit.is_dir():
        return [dotgit]
    if dotgit.is_file():
        try:
            txt = dotgit.read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            return []
        if txt.startswith("gitdir:"):
            gd = Path(txt.split(":", 1)[1].strip())
            if not gd.is_absolute():
                gd = (root / gd).resolve()
            out = [gd]
            cd = gd / "commondir"
            if cd.is_file():
                try:
                    cpath = Path(cd.read_text(encoding="utf-8", errors="replace").strip())
                    if not cpath.is_absolute():
                        cpath = (gd / cpath).resolve()
                    out.append(cpath)
                except OSError:
                    pass
            return out
    return []


def _tree_stat_sig(root: Path) -> tuple[int, int, int, tuple[tuple[str, int, int], ...]]:
    """Fast <10ms stat signature used to detect working-tree or git-ref mutations."""
    count = 0
    mtime_acc = 0
    size_acc = 0
    stack = [str(root)]
    while stack:
        d = stack.pop()
        try:
            with os.scandir(d) as it:
                for entry in it:
                    name = entry.name
                    if name in (".git", "__pycache__", ".pytest_cache", "node_modules", ".ml_daemon.json"):
                        continue
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            stack.append(entry.path)
                        else:
                            st = entry.stat(follow_symlinks=False)
                            count += 1
                            mtime_acc ^= st.st_mtime_ns
                            size_acc += st.st_size
                    except OSError:
                        continue
        except OSError:
            continue

    git_meta: list[tuple[str, int, int]] = []
    git_dirs = _git_dir_paths(root)
    for gd in git_dirs:
        for rel in ("HEAD", "index", "packed-refs"):
            p = gd / rel
            try:
                if p.is_file():
                    st = p.stat()
                    git_meta.append((str(p), st.st_mtime_ns, st.st_size))
            except OSError:
                continue
        head = gd / "HEAD"
        try:
            if head.is_file():
                htxt = head.read_text(encoding="utf-8", errors="replace").strip()
                if htxt.startswith("ref:"):
                    ref = htxt.split(":", 1)[1].strip()
                    for base in git_dirs:
                        rp = base / ref
                        if rp.is_file():
                            st = rp.stat()
                            git_meta.append((str(rp), st.st_mtime_ns, st.st_size))
        except OSError:
            continue
    return (count, mtime_acc, size_acc, tuple(git_meta))


def _repo_fingerprint(root: Path) -> str:
    """Compute SHA-256 repo freshness fingerprint from git HEAD + working-tree status."""
    resolved = root.resolve()
    head_proc = subprocess.run(
        ["git", "-C", str(resolved), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    status_proc = subprocess.run(
        ["git", "-C", str(resolved), "status", "--porcelain"],
        capture_output=True,
        text=True,
        check=False,
    )
    if status_proc.returncode == 0:
        head_val = head_proc.stdout.strip() if head_proc.returncode == 0 else "UNBORN"
        payload = f"{head_val}\n{status_proc.stdout}"
    else:
        entries: list[str] = []
        for p in sorted(resolved.rglob("*")):
            if ".git" in p.parts or p.name == ".ml_daemon.json" or not p.is_file():
                continue
            try:
                st = p.stat()
                entries.append(f"{p.relative_to(resolved)}:{st.st_mtime_ns}:{st.st_size}")
            except OSError:
                continue
        payload = "\n".join(entries)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


class _MLDaemonServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address: tuple[str, int], root: Path, auth_token: str | None = None) -> None:
        self.root = root.resolve()
        self.auth_token = auth_token if auth_token is not None else secrets.token_hex(16)
        self.hot_state = ram_ml_engine.build_hot_state(self.root)
        self.repo_fingerprint = _repo_fingerprint(self.root)
        self._stat_sig = _tree_stat_sig(self.root)
        self.state_lock = threading.Lock()
        super().__init__(server_address, _MLRequestHandler)


class _MLRequestHandler(socketserver.StreamRequestHandler):
    def handle(self) -> None:
        raw = self.rfile.readline(65536)
        if not raw:
            return
        t0 = time.perf_counter()
        try:
            req = json.loads(raw.decode("utf-8"))
        except Exception as exc:
            resp: dict[str, Any] = {"ok": False, "error": f"invalid json: {exc}"}
            self.wfile.write((json.dumps(resp) + "\n").encode("utf-8"))
            return

        if not isinstance(req, dict):
            resp = {"ok": False, "error": "invalid request: expected json object"}
            self.wfile.write((json.dumps(resp) + "\n").encode("utf-8"))
            return

        srv: _MLDaemonServer = self.server  # type: ignore[assignment]
        provided_token = req.get("auth_token")
        if not isinstance(provided_token, str) or not secrets.compare_digest(provided_token, srv.auth_token):
            resp = {"ok": False, "error": "UNAUTHORIZED: invalid or missing daemon auth_token"}
            resp["server_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
            self.wfile.write((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
            return

        cmd = str(req.get("cmd") or "ping")
        shutdown_after = False

        with srv.state_lock:
            refreshed = False
            if cmd not in ("reload", "shutdown"):
                cur_sig = _tree_stat_sig(srv.root)
                if cur_sig != srv._stat_sig:
                    cur_fp = _repo_fingerprint(srv.root)
                    srv._stat_sig = cur_sig
                    if cur_fp != srv.repo_fingerprint:
                        srv.hot_state = ram_ml_engine.build_hot_state(srv.root)
                        srv.repo_fingerprint = cur_fp
                        refreshed = True

            state = srv.hot_state
            if cmd == "ping":
                resp = {
                    "ok": True,
                    "pid": os.getpid(),
                    "model_mode": state["model_mode"],
                    "training_rows": len(state["hist_rows"]),
                    "held_out_metrics": state["held_out_metrics"],
                    "built_ms": state["built_ms"],
                    "repo_fingerprint": srv.repo_fingerprint,
                }
            elif cmd == "rank":
                files = req.get("changed_files")
                resp = {"ok": True, **ram_ml_engine.rank_tests_for_changes(srv.root, changed_files=files, hot_state=state)}
            elif cmd == "review":
                files = req.get("changed_files")
                resp = {"ok": True, **ram_ml_engine.review_changes_in_ram(srv.root, changed_files=files, hot_state=state)}
            elif cmd == "preflight":
                resp = {
                    "ok": True,
                    **ram_ml_engine.preflight_outcome_gate(
                        srv.root,
                        task_text=str(req.get("task_text") or ""),
                        verify_cmd=str(req.get("verify_cmd") or ""),
                        changed_files=req.get("changed_files"),
                        hot_state=state,
                    ),
                }
            elif cmd == "context":
                resp = {"ok": True, **ram_ml_engine.compile_session_context(srv.root, hot_state=state)}
            elif cmd == "reload":
                srv.hot_state = ram_ml_engine.build_hot_state(srv.root)
                srv.repo_fingerprint = _repo_fingerprint(srv.root)
                srv._stat_sig = _tree_stat_sig(srv.root)
                resp = {"ok": True, "reloaded": True, "built_ms": srv.hot_state["built_ms"]}
            elif cmd == "shutdown":
                resp = {"ok": True, "shutting_down": True}
                shutdown_after = True
            else:
                resp = {"ok": False, "error": f"unknown cmd: {cmd}"}

            if refreshed and resp.get("ok"):
                resp["refreshed"] = True

        resp["server_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
        self.wfile.write((json.dumps(resp, ensure_ascii=False) + "\n").encode("utf-8"))
        if shutdown_after:
            threading.Thread(target=srv.shutdown, daemon=True).start()


def read_daemon_info(root: Path) -> dict[str, Any] | None:
    p = root.resolve() / STATE_FILE_REL
    if not p.is_file():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def query_daemon(root: Path, payload: dict[str, Any], timeout: float = 2.0) -> dict[str, Any] | None:
    info = read_daemon_info(root)
    if not info or not isinstance(info.get("port"), int):
        return None
    req_payload = dict(payload)
    if "auth_token" not in req_payload and isinstance(info.get("auth_token"), str):
        req_payload["auth_token"] = info["auth_token"]
    t0 = time.perf_counter()
    try:
        with socket.create_connection(("127.0.0.1", int(info["port"])), timeout=timeout) as sock:
            sock.sendall((json.dumps(req_payload, ensure_ascii=False) + "\n").encode("utf-8"))
            chunks: list[bytes] = []
            while True:
                data = sock.recv(65536)
                if not data:
                    break
                chunks.append(data)
                if b"\n" in data:
                    break
        raw = b"".join(chunks).decode("utf-8").strip()
        res = json.loads(raw)
        res["roundtrip_ms"] = round((time.perf_counter() - t0) * 1000.0, 3)
        return res
    except (OSError, json.JSONDecodeError):
        return None


def serve_forever(root: Path, port: int = 0) -> int:
    root = root.resolve()
    srv = _MLDaemonServer(("127.0.0.1", port), root)
    actual_port = srv.server_address[1]
    state_file = root / STATE_FILE_REL
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(
        json.dumps(
            {"pid": os.getpid(), "port": actual_port, "root": str(root), "auth_token": srv.auth_token},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    srv.repo_fingerprint = _repo_fingerprint(root)
    srv._stat_sig = _tree_stat_sig(root)
    try:
        srv.serve_forever(poll_interval=0.1)
    finally:
        srv.server_close()
        try:
            state_file.unlink(missing_ok=True)
        except OSError:
            pass
    return 0


def start_daemon_background(root: Path) -> dict[str, Any]:
    existing = query_daemon(root, {"cmd": "ping"}, timeout=0.5)
    if existing and existing.get("ok"):
        return {"started": False, "already_running": True, **existing}

    import subprocess

    creationflags = 0
    if sys.platform == "win32":
        creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    subprocess.Popen(
        [sys.executable, str(Path(__file__).resolve()), "--root", str(root.resolve()), "serve"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=creationflags,
    )
    deadline = time.perf_counter() + 8.0
    while time.perf_counter() < deadline:
        res = query_daemon(root, {"cmd": "ping"}, timeout=0.5)
        if res and res.get("ok"):
            return {"started": True, "already_running": False, **res}
        time.sleep(0.1)
    return {"started": False, "ok": False, "error": "daemon failed to start within 8s"}


def stop_daemon(root: Path) -> dict[str, Any]:
    res = query_daemon(root, {"cmd": "shutdown"}, timeout=1.0)
    state_file = root.resolve() / STATE_FILE_REL
    state_file.unlink(missing_ok=True)
    if res and res.get("ok"):
        return {"stopped": True, **res}
    return {"stopped": False, "note": "daemon not running"}


def benchmark_hot_daemon(root: Path, runs: int = 10) -> dict[str, Any]:
    latencies: list[float] = []
    for _ in range(runs):
        res = query_daemon(root, {"cmd": "rank", "changed_files": [".agents/scripts/crucible_gate.py"]})
        if not res or not res.get("ok"):
            return {"ok": False, "error": "daemon unavailable"}
        latencies.append(float(res["roundtrip_ms"]))
    return {
        "ok": True,
        "runs": runs,
        "min_ms": round(min(latencies), 3),
        "median_ms": round(sorted(latencies)[len(latencies) // 2], 3),
        "max_ms": round(max(latencies), 3),
        "under_10ms": sorted(latencies)[len(latencies) // 2] < 10.0,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Persistent localhost in-RAM ML daemon.")
    parser.add_argument("--root", type=Path, default=SCRIPT_DIR.parents[1])
    parser.add_argument("action", choices=("serve", "start", "stop", "status", "bench"))
    args = parser.parse_args(argv)
    root = args.root.resolve()

    if args.action == "serve":
        return serve_forever(root)
    if args.action == "start":
        out = start_daemon_background(root)
        print(json.dumps(out, indent=2))
        return 0 if out.get("ok") else 1
    if args.action == "stop":
        out = stop_daemon(root)
        print(json.dumps(out, indent=2))
        return 0
    if args.action == "status":
        out = query_daemon(root, {"cmd": "ping"}) or {"ok": False, "status": "stopped"}
        print(json.dumps(out, indent=2))
        return 0 if out.get("ok") else 1
    out = benchmark_hot_daemon(root)
    print(json.dumps(out, indent=2))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
