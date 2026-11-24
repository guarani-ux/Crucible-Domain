#!/usr/bin/env python3
"""Tests for localhost ML daemon auth token enforcement and repo freshness."""

from __future__ import annotations

import json
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1]
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import ram_ml_daemon  # noqa: E402


def _init_git_repo(root: Path) -> None:
    (root / ".gitignore").write_text(".agents/.ml_daemon.json\n", encoding="utf-8")
    (root / "sample.py").write_text("x = 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "init"], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.com"], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Test User"], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(root), "add", ".gitignore", "sample.py"], capture_output=True, check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-m", "init"], capture_output=True, check=True)


def _start_daemon_thread(root: Path) -> threading.Thread:
    thread = threading.Thread(target=ram_ml_daemon.serve_forever, args=(root, 0), daemon=True)
    thread.start()
    deadline = time.perf_counter() + 5.0
    while time.perf_counter() < deadline:
        info = ram_ml_daemon.read_daemon_info(root)
        if info and isinstance(info.get("port"), int) and isinstance(info.get("auth_token"), str):
            return thread
        time.sleep(0.05)
    raise AssertionError("Daemon did not publish .agents/.ml_daemon.json within 5s")


def _raw_tcp_query(port: int, payload: dict[str, object]) -> dict[str, object]:
    with socket.create_connection(("127.0.0.1", port), timeout=2.0) as sock:
        sock.sendall((json.dumps(payload) + "\n").encode("utf-8"))
        chunks: list[bytes] = []
        while True:
            data = sock.recv(65536)
            if not data:
                break
            chunks.append(data)
            if b"\n" in data:
                break
    return json.loads(b"".join(chunks).decode("utf-8").strip())


def test_daemon_rejects_missing_or_invalid_auth_token(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    thread = _start_daemon_thread(tmp_path)
    try:
        info = ram_ml_daemon.read_daemon_info(tmp_path)
        assert info is not None
        assert isinstance(info.get("auth_token"), str)
        assert len(info["auth_token"]) == 32
        port = int(info["port"])

        missing_resp = _raw_tcp_query(port, {"cmd": "ping"})
        assert missing_resp["ok"] is False
        assert "UNAUTHORIZED" in str(missing_resp.get("error", ""))

        bad_shutdown = _raw_tcp_query(port, {"cmd": "shutdown", "auth_token": "invalid-token"})
        assert bad_shutdown["ok"] is False
        assert "UNAUTHORIZED" in str(bad_shutdown.get("error", ""))

        bad_query = ram_ml_daemon.query_daemon(tmp_path, {"cmd": "ping", "auth_token": "wrong"})
        assert bad_query is not None
        assert bad_query["ok"] is False
        assert "UNAUTHORIZED" in str(bad_query.get("error", ""))

        # Unauthenticated shutdown must not have terminated the daemon
        valid_ping = ram_ml_daemon.query_daemon(tmp_path, {"cmd": "ping"})
        assert valid_ping is not None
        assert valid_ping["ok"] is True
    finally:
        ram_ml_daemon.stop_daemon(tmp_path)
        thread.join(timeout=3.0)


def test_daemon_auth_success_and_freshness_refresh_on_mutation(tmp_path: Path) -> None:
    _init_git_repo(tmp_path)
    fp_before = ram_ml_daemon._repo_fingerprint(tmp_path)
    thread = _start_daemon_thread(tmp_path)
    try:
        first = ram_ml_daemon.query_daemon(tmp_path, {"cmd": "ping"})
        assert first is not None
        assert first["ok"] is True
        assert first["repo_fingerprint"] == fp_before
        assert "refreshed" not in first

        (tmp_path / "sample.py").write_text("x = 2\n", encoding="utf-8")
        fp_after = ram_ml_daemon._repo_fingerprint(tmp_path)
        assert fp_after != fp_before

        second = ram_ml_daemon.query_daemon(tmp_path, {"cmd": "ping"})
        assert second is not None
        assert second["ok"] is True
        assert second.get("refreshed") is True
        assert second["repo_fingerprint"] == fp_after

        third = ram_ml_daemon.query_daemon(tmp_path, {"cmd": "ping"})
        assert third is not None
        assert third["ok"] is True
        assert "refreshed" not in third
        assert third["repo_fingerprint"] == fp_after
    finally:
        ram_ml_daemon.stop_daemon(tmp_path)
        thread.join(timeout=3.0)
