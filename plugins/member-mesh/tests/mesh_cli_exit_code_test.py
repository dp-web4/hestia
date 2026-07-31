#!/usr/bin/env python3
"""A daemon refusal must reach the CLI's caller as a non-zero exit code.

The bug: `hestia_member_notify` refusals arrive over a 200 with a well-formed
JSON-RPC result whose payload is `{"_hestia_error": ...}`. hestia-mesh.py printed
that payload and exited 0, so:

    hestia-mesh.py send <to> <kind> <pointer> || handle_failure

never fired, and the sender believed a notice was queued that never was. Measured
2026-07-31 against the live daemon on CBP: an over-length pointer and an unknown
recipient BOTH exited 0.

This is the same class the repo already names twice — "a refusal is only worth the
caller that hears it" (#108) — and session-mesh-inbox.sh:35-45 is written on the
assumption that this CLI signals failure by exit code. It didn't.

Drives the REAL hestia-mesh.py against a stub MCP daemon, same no-test-seam posture
as the other tests here: nothing in the CLI knows it is under test.

Cases:
  A  send refused by the daemon        -> rc=3, and the error payload still on stdout
  B  send accepted                     -> rc=0
  C  peek refused by the daemon        -> rc!=0, so "could not read" != "empty inbox"
  D  response carrying no data: frame  -> rc!=0, not a silent empty result
  E  missing HESTIA_MESH_PLUGIN        -> rc=2 (unchanged; identity != refusal)
"""
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(os.path.dirname(HERE), "hestia-mesh.py")

# What the stub returns for the next tools/call, set per case.
MODE = {"tool": "ok"}


class Stub(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])) or "{}")
        method = body.get("method")

        if method == "initialize":
            return self._json({"jsonrpc": "2.0", "id": body["id"],
                               "result": {"protocolVersion": "2024-11-05"}},
                              sid="stub-session")
        if method == "notifications/initialized":
            self.send_response(202)
            self.end_headers()
            return

        name = body.get("params", {}).get("name")
        if name == "hestia_connect":
            return self._sse(body["id"], {"sessionId": "s-1", "constellationRole":
                                          "role:constellation:member"})

        if MODE["tool"] == "no_frame":
            # A 200 whose body has no `data:` line at all — the shape that used to
            # collapse to {} and print as a successful empty result.
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.end_headers()
            self.wfile.write(b": keepalive\n\n")
            return
        if MODE["tool"] == "refuse":
            return self._sse(body["id"], {"_hestia_error": {
                "code": "hestia.member_notify_bad_pointer",
                "message": "pointer_uri must be a single-line pointer (<=512 bytes)",
                "data": {"pointer_len": 672}}})
        return self._sse(body["id"], {"queued_id": 999, "in_reply_to": 444,
                                      "binding_verified": True})

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
        frame = json.dumps({"jsonrpc": "2.0", "id": rid,
                            "result": {"content": [{"type": "text",
                                                    "text": json.dumps(obj)}]}})
        raw = f"event: message\ndata: {frame}\n\n".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


def run(args, env_extra=None, mode="ok"):
    MODE["tool"] = mode
    env = dict(os.environ, HESTIA_ENDPOINT=EP, HESTIA_MESH_PLUGIN="test-member")
    env.pop("HESTIA_ROLE", None)
    env.update(env_extra or {})
    p = subprocess.run([sys.executable, CLI] + args, capture_output=True, text=True,
                       env=env, timeout=20)
    return p.returncode, p.stdout, p.stderr


FAILURES = []


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  -- {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


if __name__ == "__main__":
    srv = HTTPServer(("127.0.0.1", 0), Stub)
    EP = f"http://127.0.0.1:{srv.server_port}/mcp"
    threading.Thread(target=srv.serve_forever, daemon=True).start()

    print("mesh CLI exit-code test")

    rc, out, _ = run(["send", "kimi-code", "reply", "p.md#x", "444"], mode="refuse")
    check("A  refused send exits non-zero", rc != 0, f"rc={rc}")
    check("A  refused send exits 3 specifically", rc == 3, f"rc={rc}")
    check("A  error payload still on stdout", "_hestia_error" in out, out[:120])

    rc, out, _ = run(["send", "kimi-code", "reply", "p.md#x", "444"], mode="ok")
    check("B  accepted send exits 0", rc == 0, f"rc={rc}")
    check("B  receipt on stdout", "queued_id" in out, out[:120])

    rc, out, _ = run(["peek"], mode="refuse")
    check("C  refused peek exits non-zero -- 'could not read' != 'empty'", rc != 0, f"rc={rc}")

    rc, out, _ = run(["drain"], mode="no_frame")
    check("D  response with no data: frame exits non-zero", rc != 0, f"rc={rc}")

    rc, out, err = run(["send", "kimi-code", "reply", "p.md#x"],
                       env_extra={"HESTIA_MESH_PLUGIN": ""}, mode="ok")
    check("E  missing identity still exits 2 (unchanged)", rc == 2, f"rc={rc}")

    srv.shutdown()
    if FAILURES:
        print(f"\nFAILED: {', '.join(FAILURES)}")
        sys.exit(1)
    print("\nAll cases passed.")
