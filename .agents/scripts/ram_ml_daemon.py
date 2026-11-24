#!/usr/bin/env python3
"""Persistent localhost-only in-RAM ML daemon for <10ms hot queries.

Keeps the repo's AST index, git co-change matrix, and trained LogisticRegression /
IsolationForest models hot in RAM over 127.0.0.1 JSON-lines TCP.
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import socketserver
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


class _MLDaemonServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True

    def __init__(self, server_address: tuple[str, int], root: Path) -> None:
        self.root = root.resolve()
        self.hot_state = ram_ml_engine.build_hot_state(self.root)
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

        cmd = str(req.get("cmd") or "ping")
        srv: _MLDaemonServer = self.server  # type: ignore[assignment]
        shutdown_after = False

        with srv.state_lock:
            state = srv.hot_state
            if cmd == "ping":
                resp = {
                    "ok": True,
                    "pid": os.getpid(),
                    "model_mode": state["model_mode"],
                    "training_rows": len(state["hist_rows"]),
                    "held_out_metrics": state["held_out_metrics"],
                    "built_ms": state["built_ms"],
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
            elif cmd == "reload":
                srv.hot_state = ram_ml_engine.build_hot_state(srv.root)
                resp = {"ok": True, "reloaded": True, "built_ms": srv.hot_state["built_ms"]}
            elif cmd == "shutdown":
                resp = {"ok": True, "shutting_down": True}
                shutdown_after = True
            else:
                resp = {"ok": False, "error": f"unknown cmd: {cmd}"}

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
    t0 = time.perf_counter()
    try:
        with socket.create_connection(("127.0.0.1", int(info["port"])), timeout=timeout) as sock:
            sock.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))
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
        json.dumps({"pid": os.getpid(), "port": actual_port, "root": str(root)}, indent=2) + "\n",
        encoding="utf-8",
    )
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
