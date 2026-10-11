#!/usr/bin/env python3
"""D2c CLI contract: operation identity reaches the daemon and owns retry semantics."""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(os.path.dirname(HERE), "hestia-mesh.py")
STATE = tempfile.mkdtemp(prefix="mesh-operation-id-")
CALLS = []
MODE = {"slow": False}


class Stub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or "{}")
        method = body.get("method")
        if method == "initialize":
            return self._json(
                {"jsonrpc": "2.0", "id": body["id"],
                 "result": {"protocolVersion": "2024-11-05"}},
                sid="stub-session",
            )
        if method == "notifications/initialized":
            self.send_response(202)
            self.end_headers()
            return

        name = body.get("params", {}).get("name")
        if name == "hestia_connect":
            return self._sse(body["id"], {
                "sessionId": "s-1",
                "constellationRole": "role:constellation:member",
            })
        if name == "hestia_member_notify":
            args = body["params"]["arguments"]
            CALLS.append(dict(args))
            if MODE["slow"]:
                time.sleep(0.35)
            op = args.get("operation_id")
            return self._sse(body["id"], {
                "queued_id": 900 + len(CALLS),
                "to_plugin_id": args.get("to_plugin_id"),
                "kind": args.get("kind"),
                "recipient_liveness": "unknown",
                "operation_id": op,
                "replayed": len([c for c in CALLS if c.get("operation_id") == op]) > 1
                            if op else False,
            })
        return self._sse(body["id"], {})

    def _json(self, payload, sid=None):
        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        if sid:
            self.send_header("mcp-session-id", sid)
        self.end_headers()
        self.wfile.write(raw)

    def _sse(self, rid, obj):
        raw = (
            "event: message\ndata: "
            + json.dumps({
                "jsonrpc": "2.0",
                "id": rid,
                "result": {"content": [{"type": "text", "text": json.dumps(obj)}]},
            })
            + "\n\n"
        ).encode()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError):
            pass


def run(args, timeout="2"):
    env = dict(
        os.environ,
        HESTIA_MESH_PLUGIN="test-member",
        HESTIA_MESH_STATE=STATE,
        HESTIA_ENDPOINT=EP,
        HESTIA_MESH_TIMEOUT=timeout,
    )
    env.pop("HESTIA_ROLE", None)
    return subprocess.run(
        [sys.executable, CLI] + args,
        text=True,
        capture_output=True,
        env=env,
        timeout=10,
    )


FAIL = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f" -- {detail}" if detail and not cond else ""))
    if not cond:
        FAIL.append(name)


if __name__ == "__main__":
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    EP = f"http://127.0.0.1:{srv.server_port}/mcp"
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    print("member-mesh operation-id CLI test")

    keyed = ["send", "kimi-code", "coordination", "p.md", "--operation-id", "op-1"]
    a = run(keyed)
    b = run(keyed)
    check("keyed first send succeeds", a.returncode == 0, a.stderr)
    check("keyed retry reaches daemon instead of local content guard", b.returncode == 0, b.stderr)
    keyed_calls = [c for c in CALLS if c.get("operation_id") == "op-1"]
    check("operation id is forwarded exactly", len(keyed_calls) == 2, repr(keyed_calls))
    check("session id remains outside operation identity",
          all(c.get("session_id") == "s-1" for c in keyed_calls), repr(keyed_calls))
    check("confirmation names replay",
          "operation_id=op-1" in b.stderr and "replayed=yes" in b.stderr, b.stderr)

    unkeyed = ["send", "kimi-code", "coordination", "legacy.md"]
    before = len(CALLS)
    first = run(unkeyed)
    second = run(unkeyed)
    check("unkeyed first send keeps legacy success", first.returncode == 0, first.stderr)
    check("unkeyed byte-identical resend keeps legacy local refusal", second.returncode == 5,
          second.stderr)
    check("local refusal did not reach daemon", len(CALLS) == before + 1, repr(CALLS[before:]))

    MODE["slow"] = True
    timed_keyed = run(
        ["send", "kimi-code", "coordination", "slow.md", "--operation-id", "slow-op"],
        timeout="0.05",
    )
    check("keyed timeout is still rc=4", timed_keyed.returncode == 4, timed_keyed.stderr)
    check("keyed timeout tells caller same-id retry is safe",
          "Retry the SAME send" in timed_keyed.stderr and "slow-op" in timed_keyed.stderr,
          timed_keyed.stderr)

    timed_plain = run(
        ["send", "kimi-code", "coordination", "slow-plain.md"],
        timeout="0.05",
    )
    check("unkeyed timeout remains rc=4", timed_plain.returncode == 4, timed_plain.stderr)
    check("unkeyed timeout still warns about duplication",
          "no operation id" in timed_plain.stderr and "may duplicate" in timed_plain.stderr,
          timed_plain.stderr)

    srv.shutdown()
    if FAIL:
        print(f"\nFAILED: {', '.join(FAIL)}")
        sys.exit(1)
    print("\nAll cases passed.")
