#!/usr/bin/env python3
"""The witness spool (#696): a slow referee must DEFER the row, not DESTROY it.

The defect this guards: witness.py fails open with a 2s budget, and before the
spool, a missed window meant the outcome row was gone WITHOUT A TRACE — the
ledger's loss rate was invisible by construction (measured 2026-08-28: 5 rows
for an hour with ~36 tool calls, and no component recording the loss).

Three arms against a stub MCP server:
  A. healthy daemon: the outcome is recorded AND carries client_ts (the act's
     own clock — append-lag is the measurement #696 needs);
  B. slow daemon (record_outcome sleeps past the budget): the intent lands in
     the spool instead of vanishing;
  C. recovery: the next healthy run replays the spooled intent with its
     ORIGINAL client_ts, then records the live act. FIFO, nothing lost.

Runs under bare `python3` at module scope (CI executes these files directly).
HESTIA_WITNESS_TIMEOUT_S shrinks the budget so arm B does not cost real time.
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).parent
WITNESS = HERE / "witness.py"

RECORDED = []  # record_outcome argument dicts, in arrival order
SLOW = {"on": False}


class Stub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        method = body.get("method")
        if method == "initialize":
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("mcp-session-id", "stub-session")
            self.end_headers()
            self.wfile.write(json.dumps(
                {"jsonrpc": "2.0", "id": body["id"], "result": {"protocolVersion": "2024-11-05"}}
            ).encode())
            return
        if method and method.startswith("notifications/"):
            self.send_response(202)
            self.end_headers()
            return
        if method == "tools/call":
            name = body["params"]["name"]
            args = body["params"].get("arguments") or {}
            if name == "hestia_record_outcome" and SLOW["on"]:
                time.sleep(2.0)  # past HESTIA_WITNESS_TIMEOUT_S=0.3
            payload = {
                "hestia_connect": {"sessionId": "S1"},
                "hestia_begin_action": {"actionId": str(uuid.uuid4())},
                "hestia_record_outcome": {"recorded": True},
            }.get(name, {})
            if name == "hestia_record_outcome":
                RECORDED.append(args)
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps({
                "jsonrpc": "2.0", "id": body["id"],
                "result": {"structuredContent": payload},
            }).encode())
            return
        self.send_response(404)
        self.end_headers()


def run_witness(state_dir, endpoint, tool_name="Bash"):
    event = {
        "hook_event_name": "PostToolUse",
        "tool_name": tool_name,
        "tool_input": {"command": "echo hi"},
        "tool_response": {},
        "session_id": "host-sess-1",
    }
    # The witness consumes the seat's projection like the gate does (#944): the fixture home
    # carries one for `test-seat`, and the launcher's part is only the locator.
    home = state_dir / "hestia-home"
    seats = home / "seats"
    seats.mkdir(parents=True, exist_ok=True)
    (seats / ("test-seat" + "." + "env")).write_text(
        f"# member: test-seat\nHESTIA_HOME={home}\nHESTIA_STATE_DIR={state_dir}\n"
        f"HESTIA_ENDPOINT={endpoint}\n", encoding="utf-8")
    env = dict(
        os.environ,
        HESTIA_HOME=str(home),
        HESTIA_WITNESS_TIMEOUT_S="0.3",
        HESTIA_PLUGIN_ID="test-seat",
    )
    env.pop("HESTIA_STATE_DIR", None)
    env.pop("HESTIA_ENDPOINT", None)
    # BACKGROUND_MARKER bypasses the detach wrapper: the test IS the child.
    subprocess.run(
        [sys.executable, str(WITNESS), "--hestia-bg"],
        input=json.dumps(event).encode(),
        env=env, timeout=30, check=True,
    )


def main() -> int:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    endpoint = f"http://127.0.0.1:{server.server_port}/mcp"
    failures = []

    with tempfile.TemporaryDirectory() as td:
        state_dir = Path(td)

        # Arm A: healthy — recorded, with client_ts, nothing spooled.
        run_witness(state_dir, endpoint)
        if len(RECORDED) != 1:
            failures.append(f"A: expected 1 record_outcome, got {len(RECORDED)}")
        elif not isinstance(RECORDED[0].get("client_ts"), float):
            failures.append(f"A: record_outcome carried no float client_ts: {RECORDED[0]}")
        if list((state_dir / "spool").glob("*.json")):
            failures.append("A: healthy run must not spool")

        # Arm B: slow daemon — the row must be DEFERRED, not destroyed.
        RECORDED.clear()
        SLOW["on"] = True
        run_witness(state_dir, endpoint)
        SLOW["on"] = False
        spooled = sorted((state_dir / "spool").glob("*.json"))
        # The stub DID eventually answer (server completes late — the #696
        # shape); the client had already given up. What matters is the spool.
        if len(spooled) != 1:
            failures.append(f"B: expected 1 spooled intent, got {len(spooled)}")
            intent = None
        else:
            intent = json.loads(spooled[0].read_text())
            if not isinstance(intent.get("client_ts"), float):
                failures.append("B: spooled intent lost client_ts")

        original_ts = intent.get("client_ts") if intent else None

        # Arm C: recovery — replay with the ORIGINAL clock, then the live act.
        RECORDED.clear()
        run_witness(state_dir, endpoint, tool_name="Read")
        if original_ts is not None:
            replayed = [r for r in RECORDED if r.get("client_ts") == original_ts]
            if not replayed:
                failures.append(
                    f"C: spooled intent not replayed with original client_ts "
                    f"{original_ts}; saw {[r.get('client_ts') for r in RECORDED]}"
                )
            if not any(r.get("client_ts") != original_ts for r in RECORDED):
                failures.append("C: the live act was not recorded after the replay")
        if list((state_dir / "spool").glob("*.json")):
            failures.append("C: spool must be empty after a healthy run")

    server.shutdown()
    if failures:
        print("FAIL — witness spool (#696):")
        for f in failures:
            print("  " + f)
        return 1
    print("ok: recorded carries client_ts; slow daemon spools; recovery replays with the original clock")
    return 0


if __name__ == "__main__":
    sys.exit(main())
