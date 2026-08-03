#!/usr/bin/env python3
"""ACCEPTANCE TEST for F3 (CBP 2026-08-03, notice 699/701/702 thread).

The watcher connects with the WATCHED MEMBER's `plugin_id` — legitimately, it
acts on that member's mailbox. Until F3 it also passed **no `role`**, so the
daemon failed it closed to `role:constellation:member` (PR #66's defect, fixed on
the member path, never applied to the watcher's own RPC). Consequences, both
measured on CBP's chain the same day:

  * kimi's trust record carries acts kimi never performed — the gateway filing
    under the member's grain.
  * On the chain a non-delivery report was indistinguishable from the member
    itself replying. Over the whole member_notice population (695 rows, chain
    positions 1..89974) all 27 undelivered reports carried the defaulted
    `member` role while genuine member replies carried the member's declared
    role — a PERFECT discriminator that was pure accident, and silently lost the
    moment any genuine sender drops `HESTIA_ROLE`.

F3 declares `role:constellation:mesh-worker`, already in the daemon's published
set (`reputation::KNOWN_CONSTELLATION_ROLES`), so it needs no daemon change and
turns the accident into a declaration.

The second case is the one that makes the first checkable. Declaring a role and
having it TAKE are different events: an unpublished string normalizes to
`member` and the connect succeeds identically. handler.rs says so in its own
words — "kimi-code's role repair was live-verified by a connect that answers —
which it does either way". The daemon reports the outcome in
`roleDeclarationHonored`; a guard that reads any other key never fires, which is
how this check was first written here (`role`/`role_lct` — neither is a key the
daemon sends).
"""

from __future__ import annotations

import json
import os
import signal
import subprocess
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
WATCHER = os.path.abspath(os.path.join(HERE, "..", "hestia-watch-member.sh"))

failures = []


def check(label, ok, detail=""):
    if not ok:
        failures.append(label)
    print(f"{'PASS' if ok else 'FAIL'}  {label}" + (f"\n        {detail}" if detail and not ok else ""))


class StubDaemon:
    """Records every `hestia_connect` argument set and scripts the role readback."""

    def __init__(self, honored=True, effective="role:constellation:mesh-worker"):
        self.connects = []
        outer = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, code, body, hdrs=None):
                self.send_response(code)
                for k, v in (hdrs or {}).items():
                    self.send_header(k, v)
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def do_POST(self):
                n = int(self.headers.get("Content-Length", 0))
                req = json.loads(self.rfile.read(n) or b"{}")
                method = req.get("method")
                if method == "initialize":
                    return self._send(200, b'{"jsonrpc":"2.0","id":1,"result":{}}',
                                      {"mcp-session-id": "stub-sid"})
                if method == "notifications/initialized":
                    return self._send(202, b"")
                if method != "tools/call":
                    return self._send(400, b"{}")

                tool = req["params"]["name"]
                args = req["params"].get("arguments", {})
                if tool == "hestia_connect":
                    outer.connects.append(args)
                    # Shaped like the real daemon (handler.rs tool_connect): the
                    # declaration outcome is echoed, it is not inferable from
                    # "the call succeeded".
                    payload = {"sessionId": "stub-session",
                               "assignedRole": "citizen",
                               "constellationRole": effective,
                               "roleDeclarationHonored": honored,
                               "protocolVersion": 1}
                elif tool == "hestia_member_inbox":
                    payload = {"total": 0, "notices": []}
                elif tool == "hestia_member_unanswered":
                    payload = {"i_owe": [], "owed_to_me": []}
                else:
                    payload = {}
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


def run_watcher(honored=True, effective="role:constellation:mesh-worker", run_secs=3.0):
    tmp = tempfile.mkdtemp(prefix="f3-role-test-")
    fire_stub = os.path.join(tmp, "fire-stub.sh")
    with open(fire_stub, "w") as f:
        f.write("#!/usr/bin/env bash\nexit 0\n")
    os.chmod(fire_stub, 0o755)

    daemon = StubDaemon(honored=honored, effective=effective)
    env = dict(os.environ)
    env.update({"HESTIA_ENDPOINT": f"http://127.0.0.1:{daemon.port}/mcp",
                "HESTIA_MESH_STATE": os.path.join(tmp, "state"),
                "WATCH_INTERVAL": "1", "UNANSWERED_EVERY": "3600"})
    env.pop("HESTIA_WATCH_ROLE", None)  # exercise the DEFAULT, not an operator override
    proc = subprocess.Popen(["bash", WATCHER, "dest-member", "dest-agent", fire_stub],
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, start_new_session=True)
    time.sleep(run_secs)
    os.killpg(proc.pid, signal.SIGTERM)
    out = proc.stdout.read() if proc.stdout else ""
    proc.wait()
    daemon.stop()
    return daemon.connects, out


def main():
    # --- Case A: the watcher declares mesh-worker, not the member default. -----
    connects, _ = run_watcher()
    check("A: the watcher connects at all", len(connects) > 0,
          "no hestia_connect reached the stub")
    if connects:
        roles = {c.get("role") for c in connects}
        check("A: EVERY connect declares role:constellation:mesh-worker",
              roles == {"role:constellation:mesh-worker"},
              f"observed roles across {len(connects)} connects: {roles!r} "
              "(None = the pre-F3 defect: daemon fails it closed to `member`)")
        # plugin_id stays the member's: the watcher genuinely acts on that
        # member's mailbox. F3 corrects the ROLE grain, not the subject.
        check("A: plugin_id is still the watched member (F3 fixes role, not subject)",
              {c.get("plugin_id") for c in connects} == {"dest-member"},
              f"{ {c.get('plugin_id') for c in connects} !r}")

    # --- Case B: a declaration that does not survive must be SAID OUT LOUD. ----
    # The daemon accepts the connect and returns a session either way, so
    # "it connected" is not evidence the grain is right.
    _, out = run_watcher(honored=False, effective="role:constellation:member")
    check("B: a refused role declaration warns on stderr",
          "did NOT survive connect" in out,
          f"no warning in watcher output; got:\n{out[-1500:]}")
    check("B: the warning names the role the gateway ACTUALLY got",
          "role:constellation:member" in out,
          "the warning must name the effective role, not just the declared one")

    # --- Case C: the warning must not fire when the declaration IS honored. ---
    # A guard that fires unconditionally is noise, and noise gets filtered.
    _, out_ok = run_watcher(honored=True)
    check("C: no warning when the declaration is honored",
          "did NOT survive connect" not in out_ok,
          f"spurious warning:\n{out_ok[-1500:]}")

    print()
    if failures:
        print(f"{len(failures)} FAILED: " + "; ".join(failures))
        raise SystemExit(1)
    print("all checks passed")


if __name__ == "__main__":
    main()
