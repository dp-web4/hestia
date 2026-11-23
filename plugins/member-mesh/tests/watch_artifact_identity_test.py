#!/usr/bin/env python3
"""The watcher records its startup source snapshot and detects a replacement.

A repository commit is not sufficient evidence: the watcher may run an installed
copy or a dirty worktree file. Bash does not expose its parsed buffer, so the
record is explicitly a snapshot of the source bytes at startup. This test starts
an isolated copy, verifies that snapshot, changes one byte without changing file
length, and requires an explicit restart-required drift event.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from pathlib import Path
import select
import shutil
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


HERE = Path(__file__).resolve().parent
WATCHER = HERE.parent / "hestia-watch-member.sh"
TIMEOUT = 8.0


def read_until(proc: subprocess.Popen[str], needle: str, accept=None, count: int = 1) -> str:
    lines: list[str] = []
    seen = 0
    deadline = time.monotonic() + TIMEOUT
    assert proc.stdout is not None
    while time.monotonic() < deadline:
        ready, _, _ = select.select([proc.stdout], [], [], 0.25)
        if not ready:
            if proc.poll() is not None:
                break
            continue
        line = proc.stdout.readline()
        if not line:
            break
        lines.append(line)
        if needle in line and (accept is None or accept(line)):
            seen += 1
            if seen == count:
                return "".join(lines)
    raise AssertionError(
        f"did not observe {needle!r} {count} time(s); rc={proc.poll()} output={''.join(lines)!r}"
    )


def stop(proc: subprocess.Popen[str]) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=2)


def start(script: Path, home: Path, **extra_env: str) -> subprocess.Popen[str]:
    env = dict(
        os.environ,
        HOME=str(home),
        HESTIA_MESH_STATE=str(home / "state"),
        HESTIA_ENDPOINT="http://127.0.0.1:1/mcp",
        WATCH_INTERVAL="0.1",
        LEVEL_EVERY="1",
        UNANSWERED_EVERY="3600",
    )
    env.update(extra_env)
    return subprocess.Popen(
        [str(script), "artifact-test", "test-host"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )


class OneDebtDaemon:
    def __init__(self) -> None:
        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:
                pass

            def _sse(self, payload: dict) -> None:
                body = f"data: {json.dumps(payload)}\n\n".encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self) -> None:
                length = int(self.headers.get("Content-Length") or 0)
                try:
                    req = json.loads(self.rfile.read(length) or b"{}")
                except Exception:
                    req = {}
                if req.get("method") == "initialize":
                    self._sse({"jsonrpc": "2.0", "id": req.get("id"), "result": {
                        "protocolVersion": "2024-11-05", "capabilities": {},
                        "serverInfo": {"name": "hestia", "version": "artifact-test"},
                    }})
                    return
                if req.get("method") != "tools/call":
                    self.send_response(202)
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                name = req.get("params", {}).get("name")
                if name == "hestia_connect":
                    result = {"sessionId": "artifact-session"}
                elif name == "hestia_member_unanswered":
                    result = {"i_owe": [{"id": 1, "kind": "review_request",
                                         "from_plugin": "claude-code", "to_plugin": "artifact-test",
                                         "pointer_uri": "shared-context/one-debt", "drained_at": None,
                                         "queued_at": "2026-01-01T00:00:00Z"}], "owed_to_me": []}
                else:
                    result = {"total": 0, "notices": []}
                self._sse({"jsonrpc": "2.0", "id": req.get("id"),
                           "result": {"content": [{"type": "text", "text": json.dumps(result)}]}})

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def endpoint(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}/mcp"

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def real_drift_stays_visible() -> None:
    with tempfile.TemporaryDirectory() as td_raw:
        td = Path(td_raw)
        script = td / "hestia-watch-member.sh"
        original = WATCHER.read_bytes()
        script.write_bytes(original)
        script.chmod(0o755)
        expected = hashlib.sha256(original).hexdigest()

        proc = start(script, td / "home")
        try:
            startup = read_until(proc, "ARTIFACT plugin=")
            assert "state=ok" in startup, startup
            assert f"startup_sha256={expected}" in startup, startup
            assert str(script) not in startup, "artifact record leaked its absolute path"

            # Replace atomically. Truncating the inode bash is still parsing can make
            # it observe EOF and exit successfully before the loop starts — a flaky
            # test that reports the watcher healthy by killing it is worse than none.
            changed = original.replace(b"local-mesh", b"local_mesh", 1)
            assert changed != original and len(changed) == len(original)
            replacement = script.with_suffix(".new")
            replacement.write_bytes(changed)
            replacement.chmod(0o755)
            os.replace(replacement, script)
            drifted = hashlib.sha256(changed).hexdigest()

            drift = read_until(proc, "ARTIFACT DRIFT")
            assert "restart required" in drift, drift
            assert f"startup_sha256={expected}" in drift, drift
            assert f"disk_sha256={drifted}" in drift, drift

            # Outlive the edge alarm. The next periodic gauge must continue to
            # report drift, never return to the healthy startup-only shape.
            gauge = read_until(proc, "ARTIFACT plugin=")
            assert "state=drift" in gauge, gauge
            assert "reason=differs-from-startup" in gauge, gauge
            assert f"disk_sha256={drifted}" in gauge, gauge
        finally:
            stop(proc)


def unavailable_startup_is_absorbing() -> None:
    with tempfile.TemporaryDirectory() as td_raw:
        td = Path(td_raw)
        script = td / "hestia-watch-member.sh"
        script.write_bytes(WATCHER.read_bytes())
        script.chmod(0o755)

        real_python = shutil.which("python3")
        assert real_python is not None
        bin_dir = td / "bin"
        bin_dir.mkdir()
        enabled = td / "python-enabled"
        shim = bin_dir / "python3"
        shim.write_text(
            "#!/bin/sh\n"
            f'[ -f "{enabled}" ] || exit 1\n'
            f'exec "{real_python}" "$@"\n'
        )
        shim.chmod(0o755)

        proc = start(
            script,
            td / "home",
            PATH=f"{bin_dir}:{os.environ['PATH']}",
        )
        try:
            startup = read_until(proc, "ARTIFACT plugin=")
            assert "state=unverifiable" in startup, startup
            assert "reason=startup-baseline-unavailable" in startup, startup
            assert "startup_sha256=unavailable" in startup, startup

            # Restoring the hasher does not create a time machine: the current disk
            # hash becomes visible evidence, but no startup baseline can be inferred.
            enabled.touch()
            later = read_until(
                proc,
                "ARTIFACT plugin=",
                lambda line: "disk_sha256=unavailable" not in line,
            )
            measured = [
                line for line in later.splitlines() if "ARTIFACT plugin=" in line
            ][-1]
            assert "state=unverifiable" in measured, later
            assert "reason=startup-baseline-unavailable" in measured, later
            assert "disk_sha256=unavailable" not in measured, later
            assert "ARTIFACT DRIFT" not in later, later
        finally:
            stop(proc)


def default_gauge_cadence_fits_measured_journal_retention() -> None:
    text = WATCHER.read_text()
    level = re.search(r'^LEVEL_EVERY="\$\{LEVEL_EVERY:-(\d+)\}"', text, re.MULTILINE)
    debt = re.search(r'^UNANSWERED_EVERY="\$\{UNANSWERED_EVERY:-(\d+)\}"', text, re.MULTILINE)
    assert level is not None and debt is not None, "level and debt cadences must be independent"
    assert int(level.group(1)) == 600, "the level gauge must fit the measured retention window"
    assert int(debt.group(1)) == 3600, "per-row debt announcements must remain hourly"


def level_and_debt_cadences_schedule_independently() -> None:
    with tempfile.TemporaryDirectory() as td_raw:
        td = Path(td_raw)
        script = td / "hestia-watch-member.sh"
        script.write_bytes(WATCHER.read_bytes())
        script.chmod(0o755)
        script.with_name("peek-new.py").write_bytes(WATCHER.with_name("peek-new.py").read_bytes())
        daemon = OneDebtDaemon()
        proc = start(script, td / "home", HESTIA_ENDPOINT=daemon.endpoint,
                     LEVEL_EVERY="1", UNANSWERED_EVERY="3")
        try:
            output = read_until(proc, "UNANSWERED (", count=2)
            assert output.count("UNANSWERED (") == 2, output
            assert output.count("ARTIFACT plugin=") >= 2, output
        finally:
            stop(proc)
            daemon.stop()


def malformed_cadence_fails_at_startup() -> None:
    with tempfile.TemporaryDirectory() as td_raw:
        td = Path(td_raw)
        script = td / "hestia-watch-member.sh"
        script.write_bytes(WATCHER.read_bytes())
        script.chmod(0o755)
        for name, value in (("LEVEL_EVERY", "abc"), ("UNANSWERED_EVERY", "0")):
            proc = start(script, td / "home", **{name: value})
            output, _ = proc.communicate(timeout=5)
            assert proc.returncode == 2, (name, proc.returncode, output)
            assert f"invalid {name}={value}" in output, (name, output)


def main() -> None:
    default_gauge_cadence_fits_measured_journal_retention()
    level_and_debt_cadences_schedule_independently()
    malformed_cadence_fails_at_startup()
    real_drift_stays_visible()
    unavailable_startup_is_absorbing()

    print("ok: watcher artifact state is persistent, live, and race-free")


if __name__ == "__main__":
    main()
