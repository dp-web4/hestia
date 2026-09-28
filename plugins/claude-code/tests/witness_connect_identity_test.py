#!/usr/bin/env python3
"""#981 prerequisite: the witness must present its HOST SESSION on connect.

WHY THIS IS A WIRE TEST AND NOT A SOURCE GREP. The claim is about what the daemon receives,
and the defect it guards was invisible in the source: `witness.py` passes `host_session_id` on
`hestia_begin_action`, so a reader checking "does it send the host session" finds a hit and
stops. It did not send it on `hestia_connect`, which is the only call connect idempotency
reads, so every PostToolUse invocation minted a fresh daemon session — measured on CBP over
4,554 rows: 80 host sessions, 48 daemon sessions behind the gate rows, and 4,076 behind the
outcome rows, sharing nothing.

That matters beyond tidiness. #981 will enforce that only the session which BEGAN an action
may close it. Until Pre and Post resolve to the same daemon session, every legitimate closer
is a foreign closer, and enforcing ownership would refuse every outcome on the fleet.

So this runs the real hook against a stub MCP endpoint and reads the connect frame off the
wire.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from projection_fixture import write_projection  # noqa: E402

WITNESS = HERE.parent / "hooks" / "witness.py"
FAILURES: list[str] = []
CALLS: list[dict] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f"  <- {detail}"))
    if not ok:
        FAILURES.append(name)


class Stub(BaseHTTPRequestHandler):
    """The smallest MCP endpoint that lets the hook get as far as connecting."""

    def log_message(self, *_args):  # silence
        pass

    def do_POST(self):  # noqa: N802
        raw = self.rfile.read(int(self.headers.get("content-length") or 0))
        try:
            msg = json.loads(raw or b"{}")
        except json.JSONDecodeError:
            msg = {}
        method = msg.get("method")
        params = msg.get("params") or {}
        if method == "tools/call":
            CALLS.append({"tool": params.get("name"), "args": params.get("arguments") or {}})
        result: dict = {}
        if method == "initialize":
            result = {"protocolVersion": "2024-11-05", "capabilities": {}}
        elif method == "tools/call":
            name = params.get("name")
            if name == "hestia_connect":
                result = {"structuredContent": {"sessionId": "daemon-session-1"}}
            elif name == "hestia_begin_action":
                result = {"structuredContent": {"actionId": "action-1"}}
            else:
                result = {"structuredContent": {"ok": True}}
        body = json.dumps({"jsonrpc": "2.0", "id": msg.get("id"), "result": result}).encode()
        self.send_response(200)
        self.send_header("content-type", "application/json")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def run_hook(home: Path, endpoint: str, host_session: str) -> subprocess.CompletedProcess:
    event = {
        "hook_event_name": "PostToolUse",
        "session_id": host_session,
        "tool_use_id": "tu-witness-1",
        "tool_name": "Bash",
        "tool_input": {"command": "echo hi"},
        "tool_response": {"stdout": "hi"},
    }
    env = {k: v for k, v in os.environ.items() if not k.startswith("HESTIA_")}
    env.update({"HESTIA_HOME": str(home), "HESTIA_ENDPOINT": endpoint,
                "PATH": os.environ.get("PATH", "")})
    # SYNCHRONOUSLY, via the hook's own background marker. Invoked plainly it forks a detached
    # child and the parent exits 0 at once — so a test that reads the wire without this races a
    # process it cannot see, and reports "it never connected" about a connect that was simply
    # not waited for. The marker runs `run()` in this process; it is the same code path the
    # child executes.
    return subprocess.run([sys.executable, str(WITNESS), "--hestia-bg"],
                          input=json.dumps(event), env=env,
                          capture_output=True, text=True, timeout=30)


def main() -> int:
    server = HTTPServer(("127.0.0.1", 0), Stub)
    endpoint = f"http://127.0.0.1:{server.server_port}/mcp"
    threading.Thread(target=server.serve_forever, daemon=True).start()
    try:
        with TemporaryDirectory() as tmp:
            home = Path(tmp)
            # HESTIA_STATE_DIR INTO THE FIXTURE, deliberately. Without it the hook resolves
            # its state dir to the real seat's, and `spool_drain` runs first — so this test
            # would replay the OPERATOR'S genuinely spooled rows into a stub endpoint and
            # unlink them. A test that can destroy live evidence is worse than no test.
            write_projection(home, "claude-code", {
                "HESTIA_PLUGIN_ID": "claude-code", "HESTIA_ENDPOINT": endpoint,
                "HESTIA_STATE_DIR": str(home / "state"),
            })
            host_session = "9261dc9a-1703-4964-9e72-a076bd468aca"
            proc = run_hook(home, endpoint, host_session)
            check("the hook ran and fail-opened as designed", proc.returncode == 0,
                  f"rc={proc.returncode} stderr={proc.stderr[-200:]}")

            connects = [c for c in CALLS if c["tool"] == "hestia_connect"]
            check("it connected", len(connects) == 1, json.dumps([c['tool'] for c in CALLS]))
            if not connects:
                raise SystemExit(1)
            args = connects[0]["args"]

            # THE ARM. Under the defect this key is simply absent, and the daemon has nothing
            # to make the connect idempotent on.
            check("the connect frame carries host_session_id",
                  args.get("host_session_id") == host_session,
                  json.dumps(args))
            # And it is the HOST's session, not something the hook invented for itself.
            check("it is the harness session id from the event, not a fresh value",
                  args.get("host_session_id") == host_session, json.dumps(args))
            check("the seat still identifies itself",
                  args.get("plugin_id") == "claude-code", json.dumps(args))

            # The begin/record pair still carries what it carried before: this change adds an
            # argument to connect, it does not move one off the action calls.
            record = [c for c in CALLS if c["tool"] == "hestia_record_outcome"]
            check("an outcome was still recorded", len(record) == 1,
                  json.dumps([c["tool"] for c in CALLS]))
            if record:
                check("the outcome names a session", "session_id" in record[0]["args"],
                      json.dumps(record[0]["args"]))
    finally:
        server.shutdown()

    print()
    if FAILURES:
        print(f"{len(FAILURES)} FAILURE(S): {FAILURES}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
