#!/usr/bin/env python3
"""The remedy surface the deny texts name must exist on the channel members actually have.

WHY THIS FILE (issue #121, claude-code 2026-07-30). The gate's deny texts prescribe
`hestia_appeal` and ESCALATE — both MCP tools. A mesh-woken non-interactive session has
no hestia MCP server configured, so the prescribed remedy was unreachable by exactly the
caller that heard the refusal; the member CLI — which already authenticates as the member
and already witnesses — listed four subcommands, none of them a remedy. The fix adds
`appeal` / `appeals` / `arbitrate-appeal` / `escalate` / `pending` / `poll` / `arbitrate`
to `hestia-mesh.py`, wrapping the tools the daemon already exposes.

Properties asserted, all hermetic against a stub daemon that records every tools/call:

  A. EACH SUBCOMMAND REACHES THE TOOL THE DENY TEXT MEANS, with the arguments that tool
     requires — `arbitrate-appeal grant` must send `upheld: true` (the deny was wrong),
     `arbitrate ... approve` must send an EXPLICIT boolean (an omitted verdict is not a
     verdict, per the daemon's own refusal text), and every attributed surface carries
     the caller's own live session_id (the daemon refuses unattributed appellants and
     arbiters — a ruling that moves nobody's conduct score is theatre).
  B. USAGE ERRORS REFUSE BEFORE THE WIRE. A missing hash, a missing verdict word, or a
     verdict word outside the vocabulary exits 2 having sent ZERO requests — the same
     fail-closed shape as the identity guard, because a half-parsed ruling is worse than
     none.
"""
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "..", "hestia-mesh.py")

failures = []


def check(ok, label, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(label)


class StubDaemon:
    """Records (tool, args) for every tools/call; answers hestia_connect with a session."""

    def __init__(self):
        self.calls = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, hdrs=None):
                self.send_response(code)
                for k, v in (hdrs or {"Content-Type": "application/json"}).items():
                    self.send_header(k, v)
                self.send_header("mcp-session-id", "stub-mcp")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                raw = self.rfile.read(int(self.headers.get("Content-Length", 0) or 0))
                try:
                    req = json.loads(raw or b"{}")
                except json.JSONDecodeError:
                    return self._send(400, b"{}")
                if req.get("method") == "initialize":
                    return self._send(200, json.dumps(
                        {"jsonrpc": "2.0", "id": req.get("id"), "result": {}}).encode())
                if req.get("method") != "tools/call":
                    return self._send(200, b"{}")
                tool = req["params"]["name"]
                args = req["params"].get("arguments", {})
                outer.calls.append((tool, args))
                payload = {"sessionId": "stub-session-123"} if tool == "hestia_connect" else {}
                rpc = {"jsonrpc": "2.0", "id": req.get("id", 9),
                       "result": {"content": [{"type": "text", "text": json.dumps(payload)}]}}
                return self._send(200, f"data: {json.dumps(rpc)}\n\n".encode(),
                                  {"Content-Type": "text/event-stream"})

        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def run(argv, daemon, role="role:constellation:interactive-dev"):
    env = dict(os.environ)
    for k in ("HESTIA_MESH_PLUGIN", "HESTIA_MESH_HOST_AGENT", "HESTIA_ROLE"):
        env.pop(k, None)
    env["HESTIA_ENDPOINT"] = f"http://127.0.0.1:{daemon.port}/mcp"
    env["HESTIA_MESH_PLUGIN"] = "kimi-code"
    if role:
        env["HESTIA_ROLE"] = role
    return subprocess.run([sys.executable, CLI] + argv, env=env,
                          capture_output=True, text=True, timeout=30)


def tool_call(daemon):
    """The single non-connect tools/call the run should have made."""
    non_connect = [c for c in daemon.calls if c[0] != "hestia_connect"]
    return non_connect[0] if len(non_connect) == 1 else None


# ---------------------------------------------------------------------------
# A. subcommand -> tool mapping, argument contract, attribution
# ---------------------------------------------------------------------------
print("--- A. each subcommand wraps the tool the deny text means ---")

CASES = [
    (["appeal", "abc123hash", "the deny misclassified a read as a write"],
     "hestia_appeal",
     {"deny_hash": "abc123hash",
      "reason": "the deny misclassified a read as a write",
      "session_id": "stub-session-123"}),
    (["appeals"], "hestia_open_appeals", {"session_id": "stub-session-123"}),
    (["arbitrate-appeal", "abc123hash", "grant", "the record shows a read, witnessed as one"],
     "hestia_arbitrate_appeal",
     {"deny_hash": "abc123hash", "upheld": True,
      "rationale": "the record shows a read, witnessed as one",
      "session_id": "stub-session-123"}),
    (["arbitrate-appeal", "abc123hash", "reject", "the write targeted the gate's own code"],
     "hestia_arbitrate_appeal",
     {"deny_hash": "abc123hash", "upheld": False,
      "rationale": "the write targeted the gate's own code",
      "session_id": "stub-session-123"}),
    (["escalate", "Edit", "sha256:deadbeef mode-bit-only change"],
     "hestia_gate_escalation_open",
     {"plugin_id": "kimi-code", "tool_name": "Edit",
      "marker": "sha256:deadbeef mode-bit-only change",
      "role": "role:constellation:interactive-dev"}),
    (["pending"], "hestia_gate_pending_escalations", {"session_id": "stub-session-123"}),
    (["poll", "esc-id-9"], "hestia_gate_escalation_poll", {"escalation_id": "esc-id-9"}),
    (["arbitrate", "esc-id-9", "approve", "bar met: test file, exec bit cannot weaken it"],
     "hestia_gate_arbitrate_escalation",
     {"escalation_id": "esc-id-9", "approve": True,
      "reason": "bar met: test file, exec bit cannot weaken it",
      "session_id": "stub-session-123"}),
    (["arbitrate", "esc-id-9", "deny"],
     "hestia_gate_arbitrate_escalation",
     {"escalation_id": "esc-id-9", "approve": False, "reason": "",
      "session_id": "stub-session-123"}),
]

for argv, want_tool, want_args in CASES:
    d = StubDaemon()
    p = run(argv, d)
    got = tool_call(d)
    check(p.returncode == 0, f"A. `{' '.join(argv[:2])}` exits 0",
          f"rc={p.returncode} stderr={p.stderr[-200:]}")
    check(got is not None and got[0] == want_tool,
          f"A. `{' '.join(argv[:2])}` calls {want_tool}",
          f"calls={d.calls}")
    if got:
        check(got[1] == want_args,
              f"A. `{' '.join(argv[:2])}` sends exactly {want_tool}'s contract",
              f"got={json.dumps(got[1])}")
    d.stop()

# grant/reject must never collapse: upheld is a bool on the wire, never a string.
d = StubDaemon()
run(["arbitrate-appeal", "h", "grant", "rationale long enough to pass the floor"], d)
got = tool_call(d)
check(got and got[1].get("upheld") is True and isinstance(got[1]["upheld"], bool),
      "A. upheld is an explicit JSON bool — an omitted verdict is not a verdict",
      json.dumps(got[1] if got else {}))
d.stop()

# ---------------------------------------------------------------------------
# B. usage errors refuse before any byte reaches the daemon
# ---------------------------------------------------------------------------
print("--- B. usage errors refuse before the wire ---")

BAD = [
    ["appeal"],                                        # no hash, no reason
    ["appeal", "onlyhash"],                            # no reason
    ["arbitrate-appeal", "h", "maybe", "rationale"],   # verdict outside vocabulary
    ["arbitrate-appeal", "h", "grant"],                # no rationale
    ["escalate", "Edit"],                              # no marker
    ["poll"],                                          # no id
    ["arbitrate", "esc-id-9"],                         # no verdict
    ["arbitrate", "esc-id-9", "yep"],                  # verdict outside vocabulary
]
for argv in BAD:
    d = StubDaemon()
    p = run(argv, d)
    check(p.returncode == 2, f"B. `{' '.join(argv)}` exits 2", f"rc={p.returncode}")
    check(not any(c[0] != "hestia_connect" for c in d.calls),
          f"B. `{' '.join(argv)}` sent no ruling/appeal to the daemon",
          f"calls={d.calls}")
    d.stop()

print()
if failures:
    print(f"failures={len(failures)}")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("all remedy-surface checks pass")
