#!/usr/bin/env python3
"""Identity has no default, and the refusal must survive its callers.

WHAT HAPPENED (CBP, 2026-07-29). `hestia-mesh.py` defaulted `HESTIA_MESH_PLUGIN` to
`kimi-code` — correct when the file was Kimi's private send/receive surface, wrong once it
became the fleet's notification path. With the env unset, claude-code connected as
kimi-code three times using the tool exactly as documented. Not an error, and not an
anonymous act: a WELL-FORMED act attributed to a specific real member. It surfaced only
because the third attempt happened to address kimi-code and tripped the self-notify no-op
check; addressed to anyone else it would have landed silently in kimi's trust record.
(GATE_BYPASS_CATALOG D1, upgraded INFERRED → DEMONSTRATED on this incident. PR #108.)

The fix was to refuse. Which raised the second question, and it is the one this file
mostly exists for: **a refusal is only worth as much as the caller that hears it.**
`session-mesh-inbox.sh` ran the CLI under `2>/dev/null` and is deliberately fail-open, so
rc=2 rendered as an EMPTY INBOX — the member reads "no mail" and proceeds, permanently
dark, in exactly the absence-read-as-OK shape the refusal was written to kill, one layer
up (kimi's review of #108). Fail-open is a promise about the session surviving. It is not
a licence to be silent.

So the properties asserted here are two, and the second is the load-bearing one:

  A. THE GUARD REFUSES BEFORE IT SPEAKS. Unset (and whitespace-only, the sneakier unset)
     must exit 2 having sent ZERO bytes to the daemon — proved against a stub that counts
     requests, not by reading the source. A guard that refuses AFTER connecting has
     already minted the misattributed act it exists to prevent.
  B. THE CALLER SAYS SOMETHING. `session-mesh-inbox.sh` with no identity must still
     exit 0 (never break a session) AND emit a line that names `HESTIA_MESH_PLUGIN`.
     Silence and an empty inbox must not be the same output.

Plus the two attribution invariants that make a *successful* run honest: the id on the
wire is the one that was set (not a default), and `host_agent` derives from it rather than
being pinned to one member's name — the latent half of the same bug, since `PLUGIN=
claude-code` used to mint `host_agent=kimi-code-cli`.

Hermetic: a stub daemon on an ephemeral port. No real hestia required.
"""
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
CLI = os.path.join(HERE, "..", "hestia-mesh.py")
INBOX_HOOK = os.path.join(HERE, "..", "session-mesh-inbox.sh")

failures = []


def check(ok, label, detail=""):
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if detail and not ok else ""))
    if not ok:
        failures.append(label)


class StubDaemon:
    """Counts every request it receives. The count IS the assertion for property A."""

    def __init__(self, notices=None):
        self.requests = 0
        self.connect_args = []
        self.notices = notices or []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, hdrs=None):
                self.send_response(code)
                for k, v in (hdrs or {"Content-Type": "application/json"}).items():
                    self.send_header(k, v)
                if outer.session_header:
                    self.send_header("mcp-session-id", "stub-session")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                outer.requests += 1
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
                if tool == "hestia_connect":
                    outer.connect_args.append(args)
                    payload = {"sessionId": "stub-session"}
                elif tool == "hestia_member_inbox":
                    payload = {"total": len(outer.notices), "notices": outer.notices}
                else:
                    payload = {}
                rpc = {"jsonrpc": "2.0", "id": req.get("id", 9),
                       "result": {"content": [{"type": "text", "text": json.dumps(payload)}]}}
                return self._send(200, f"data: {json.dumps(rpc)}\n\n".encode(),
                                  {"Content-Type": "text/event-stream"})

        self.session_header = True
        self.httpd = HTTPServer(("127.0.0.1", 0), H)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    @property
    def endpoint(self):
        return f"http://127.0.0.1:{self.port}/mcp"

    def stop(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def run(argv, env_overrides, daemon):
    """Run a command with a scrubbed identity env, so the harness cannot leak one in."""
    env = dict(os.environ)
    for k in ("HESTIA_MESH_PLUGIN", "HESTIA_MESH_HOST_AGENT", "HESTIA_ROLE"):
        env.pop(k, None)
    env["HESTIA_ENDPOINT"] = daemon.endpoint
    env.update(env_overrides)
    p = subprocess.run(argv, env=env, capture_output=True, text=True, timeout=30)
    return p


# ---------------------------------------------------------------------------
# A. The guard refuses BEFORE any byte reaches the daemon.
# ---------------------------------------------------------------------------
print("--- A. refuse before connecting ---")

d = StubDaemon()
p = run([sys.executable, CLI, "peek"], {}, d)
check(p.returncode == 2, "A1. unset HESTIA_MESH_PLUGIN exits 2", f"rc={p.returncode}")
check("HESTIA_MESH_PLUGIN" in p.stderr,
      "A2. the refusal names the variable to set", p.stderr[:200])
check(p.stdout.strip() == "",
      "A3. nothing on stdout (callers parse it as JSON)", repr(p.stdout[:120]))
check(d.requests == 0,
      "A4. ZERO requests reached the daemon — no act was minted on the refusal path",
      f"requests={d.requests}")

before = d.requests
p = run([sys.executable, CLI, "peek"], {"HESTIA_MESH_PLUGIN": "   "}, d)
check(p.returncode == 2, "A5. whitespace-only id exits 2 (the sneakier unset)", f"rc={p.returncode}")
check(d.requests == before, "A6. whitespace-only also sent nothing", f"requests={d.requests}")

# The refusal must be about identity, not about being offline: point at a dead endpoint
# and confirm the SAME rc=2 with no traceback, i.e. the guard runs before any I/O.
p = run([sys.executable, CLI, "peek"], {"HESTIA_ENDPOINT": "http://127.0.0.1:1/mcp"}, d)
check(p.returncode == 2 and "Traceback" not in p.stderr,
      "A7. guard precedes I/O — same rc=2 against a dead endpoint, no traceback",
      f"rc={p.returncode} stderr={p.stderr[-200:]}")

# ---------------------------------------------------------------------------
# A'. A set identity is the one that goes on the wire — and drags host_agent with it.
# ---------------------------------------------------------------------------
print("--- A'. a successful run is attributed to who it said ---")

d2 = StubDaemon()
p = run([sys.executable, CLI, "peek"], {"HESTIA_MESH_PLUGIN": "claude-code"}, d2)
check(p.returncode == 0, "A8. a set identity passes the guard", f"rc={p.returncode} {p.stderr[:200]}")
got = d2.connect_args[0] if d2.connect_args else {}
check(got.get("plugin_id") == "claude-code",
      "A9. plugin_id on the wire is what was set, not a default", json.dumps(got))
check(got.get("host_agent") == "claude-code-cli",
      "A10. host_agent DERIVES from the identity — the old pin minted kimi-code-cli here",
      json.dumps(got))

# ---------------------------------------------------------------------------
# B. The caller designed to swallow errors must not swallow THIS one.
# ---------------------------------------------------------------------------
print("--- B. fail-open is not fail-silent ---")

d3 = StubDaemon(notices=[{"id": 1, "kind": "reply", "from_plugin": "kimi-code",
                          "pointer_uri": "shared-context/forum/x.md"}])
p = run(["sh", INBOX_HOOK], {}, d3)
check(p.returncode == 0,
      "B1. no identity: the hook STILL exits 0 (a priming layer never breaks a session)",
      f"rc={p.returncode}")
check(p.stdout.strip() != "",
      "B2. no identity: the hook is NOT silent — rc=2 used to render as an empty inbox",
      repr(p.stdout))
check("HESTIA_MESH_PLUGIN" in p.stdout,
      "B3. the surfaced line names the variable, so the session can act on it", repr(p.stdout))
check(d3.requests == 0,
      "B4. and still no act was minted through this path", f"requests={d3.requests}")

# A dark session must not be confusable with an empty one: the words differ.
dark = p.stdout
d_empty = StubDaemon(notices=[])
p_empty = run(["sh", INBOX_HOOK], {"HESTIA_MESH_PLUGIN": "claude-code"}, d_empty)
check(p_empty.returncode == 0 and p_empty.stdout.strip() == "",
      "B5. a genuinely empty inbox stays quiet (no new noise on the happy path)",
      repr(p_empty.stdout))
check(dark.strip() != p_empty.stdout.strip(),
      "B6. 'never asked' and 'nothing there' are DIFFERENT output")

# Unreachable daemon: transient, still exits 0, still says something, and says something
# DIFFERENT from the identity case — the two failures have different remedies.
d4 = StubDaemon()
p_down = run(["sh", INBOX_HOOK],
             {"HESTIA_MESH_PLUGIN": "claude-code", "HESTIA_ENDPOINT": "http://127.0.0.1:1/mcp"}, d4)
check(p_down.returncode == 0, "B7. unreachable daemon: still exits 0", f"rc={p_down.returncode}")
check(p_down.stdout.strip() != "" and "HESTIA_MESH_PLUGIN is unset" not in p_down.stdout,
      "B8. unreachable daemon is reported, and NOT as an identity problem", repr(p_down.stdout))

# No regression: with an identity and mail, the hook still lists the mail.
d5 = StubDaemon(notices=[{"id": 7, "kind": "review_done", "from_plugin": "kimi-code",
                          "pointer_uri": "https://example.invalid/pr/108"}])
p_mail = run(["sh", INBOX_HOOK], {"HESTIA_MESH_PLUGIN": "claude-code"}, d5)
check(p_mail.returncode == 0 and "review_done" in p_mail.stdout
      and "https://example.invalid/pr/108" in p_mail.stdout,
      "B9. the happy path still surfaces notices with their pointers", repr(p_mail.stdout))

for stub in (d, d2, d3, d_empty, d4, d5):
    stub.stop()

print()
if failures:
    print(f"failures={len(failures)}")
    for f in failures:
        print(f"  - {f}")
    sys.exit(1)
print("all identity-required checks pass")
