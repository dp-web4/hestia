#!/usr/bin/env python3
"""The daemon must report its own drift the way the watcher reports its own.

WHY THIS TEST EXISTS (mesh-vocabulary thread, 2026-08-03). The watcher already
refuses to run stale bytes of itself (watch_artifact_identity_test.py), but the
daemon had no equivalent: it knew its own build string and never compared it to
anything. So a scope door committed in 7c6ab83 sat absent from the running
daemon's 29-tool surface, and F1 (PR #165) sat merge-green while the daemon
answering every `unanswered` query predated the defect being named. "Merged" and
"running" were indistinguishable in every report the mesh produced.

The repair has two halves, and this test pins both against a stub MCP daemon:

  1. The daemon exposes its build provenance on the initialize handshake
     (serverInfo.version carries the same string `--version` prints). The stub
     speaks exactly that contract; a daemon that does not is precisely the
     drift case (a binary too old to report its build predates the exposure).
  2. The watcher compares that string to `git describe` of the checkout it runs
     from, equality not ancestry, and alarms on the EDGE while a periodic
     DAEMON line keeps the LEVEL visible — the same discipline as
     check_artifact_drift, because an alarm that fires once and goes quiet
     reads as resolved.

Properties asserted:

  A. MATCH: a daemon built from the checkout's own describe string reads
     state=ok reason=matches-source, with both raw strings on the line.
  B. DRIFT: a different build string produces an explicit
     "DAEMON DRIFT — rebuild+restart required" edge naming running AND source,
     and the periodic gauge keeps reporting state=drift after the edge.
  C. RECOVERY CLEARS THE EDGE: flipping the stub back to the matching build
     returns the gauge to state=ok (and re-drifting alarms again — the edge
     memory is not a one-shot latch).
  D. NO PROVENANCE IS DRIFT, NOT "UNVERIFIABLE": a pre-exposure daemon (a bare
     semver with no parenthesized build string) is the exact condition this
     check exists to catch; reporting it as "unverifiable" would let the one
     daemon that needs rebuilding pass silently.

Hermetic: the stub is a local HTTP server on an ephemeral port; the source
side of the comparison is the real checkout this test runs in (CI checkouts
have no tags and depth-1 history, so the test derives its expectation from
`git describe` itself rather than hardcoding a shape).
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import select
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


HERE = Path(__file__).resolve().parent
WATCHER = HERE.parent / "hestia-watch-member.sh"
TIMEOUT = 15.0


class StubDaemon:
    """Just enough MCP to carry serverInfo.version on initialize."""

    def __init__(self, version: str) -> None:
        self.version = version
        outer = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args) -> None:  # silence
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
                method = req.get("method")
                if method == "initialize":
                    self._sse({
                        "jsonrpc": "2.0",
                        "id": req.get("id"),
                        "result": {
                            "protocolVersion": "2024-11-05",
                            "capabilities": {},
                            "serverInfo": {"name": "hestia", "version": outer.version},
                        },
                    })
                elif method == "tools/call":
                    # The watcher's drain lands here; a refusal-shaped result
                    # keeps the loop on its empty-inbox path.
                    self._sse({
                        "jsonrpc": "2.0",
                        "id": req.get("id"),
                        "result": {"content": [{"type": "text",
                                                "text": '{"_hestia_error":"stub"}'}]},
                    })
                else:
                    self.send_response(202)
                    self.send_header("Content-Length", "0")
                    self.end_headers()

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    @property
    def endpoint(self) -> str:
        return f"http://127.0.0.1:{self.server.server_port}/mcp"

    def stop(self) -> None:
        self.server.shutdown()
        self.server.server_close()


def source_describe() -> str:
    out = subprocess.run(
        ["git", "-C", str(HERE.parent.parent.parent),
         "describe", "--tags", "--always", "--dirty"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    assert out, "git describe produced nothing — the watcher will read the same"
    return out


def read_until(proc: subprocess.Popen[str], needle: str, accept=None) -> str:
    lines: list[str] = []
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
            return "".join(lines)
    raise AssertionError(
        f"did not observe {needle!r}; rc={proc.poll()} output={''.join(lines)!r}"
    )


def stop(proc: subprocess.Popen[str]) -> None:
    proc.terminate()
    try:
        proc.wait(timeout=2)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=2)


def start(home: Path, endpoint: str) -> subprocess.Popen[str]:
    env = dict(
        os.environ,
        HOME=str(home),
        HESTIA_MESH_STATE=str(home / "state"),
        HESTIA_ENDPOINT=endpoint,
        WATCH_INTERVAL="0.1",
        UNANSWERED_EVERY="1",  # gauge every second: the level, not just the edge
    )
    return subprocess.Popen(
        [str(WATCHER), "daemon-drift-test", "test-host"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )


def main() -> None:
    describe = source_describe()
    matching = describe.removesuffix("-dirty")
    drifted = "v9.9.9-1-gdeadbeef"
    assert drifted != matching

    stub = StubDaemon(version=f"0.0.3 ({matching})")
    try:
        with tempfile.TemporaryDirectory() as td:
            proc = start(Path(td) / "home", stub.endpoint)
            try:
                # A. match reads ok at startup, with both raw strings visible.
                startup = read_until(proc, "DAEMON state=")
                assert "state=ok" in startup, startup
                assert "reason=matches-source" in startup, startup
                assert f"running={matching}" in startup, startup

                # B. a divergent build alarms on the edge, naming both sides…
                stub.version = f"0.0.3 ({drifted})"
                drift = read_until(proc, "DAEMON DRIFT")
                assert "rebuild+restart required" in drift, drift
                assert f"running={drifted}" in drift, drift
                assert f"source={describe}" in drift or f"source={matching}" in drift, drift

                # …and the periodic gauge HOLDS the drift after the edge — an
                # alarm that goes quiet must not read as resolved.
                gauge = read_until(proc, "DAEMON state=drift")
                assert "reason=differs-from-source" in gauge, gauge

                # C. recovery returns the gauge to ok…
                stub.version = f"0.0.3 ({matching})"
                recovered = read_until(
                    proc, "DAEMON state=ok",
                )
                assert "reason=matches-source" in recovered, recovered

                # …and a second drift alarms again — the edge is not latched.
                stub.version = "0.0.3"  # pre-provenance daemon: bare semver
                redrift = read_until(proc, "DAEMON DRIFT")
                # D. no parenthesized provenance IS drift, not "unverifiable".
                assert "reason=no-build-provenance" in redrift, redrift
                assert "DAEMON UNVERIFIABLE" not in redrift, redrift
            finally:
                stop(proc)
    finally:
        stub.stop()

    print("ok: daemon build drift is reported on the edge and held on the level")


if __name__ == "__main__":
    main()
