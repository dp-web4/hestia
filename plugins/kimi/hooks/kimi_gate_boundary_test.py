#!/usr/bin/env python3
"""Boundary test for the kimi gate — the hook EXECUTED, against a stubbed daemon.

Closes the arm the PR #372 blocking note named: `hestia_gate_mechanism_test.py` passes
`plugin_id="kimi-code"` into the shared mechanism but never executes kimi's hook, so the Gate-2
wiring (and the self-protection layer restored with it) ran in no test at all. These tests run
the real hook (`pre_tool_use.py`, beside this file) as a SUBPROCESS, the way the engine does —
JSON event on stdin, exit code as the verdict — against a stub MCP daemon on an ephemeral port,
inside a synthetic workspace. Hermetic: stdlib only, no sibling checkout, no live daemon.

The load-bearing arms:
  - a write-class act whose destination is a gate file is refused LOCALLY: escalation claimed,
    `gate_self_access` witnessed, and NO policy query issued (self-protection is pre-daemon);
  - a claimed human approval lifts that refusal for the one call, and the ordinary policy path
    still runs after it;
  - the refusal needs no daemon: endpoint down, gate-file write still denied;
  - ordinary writes reach the daemon and pass; gate-file READS are allowed and witnessed;
  - the hooks-dir-only names do not overreach (a `witness.py` outside any hooks/ dir is ordinary
    work), while the distinctive governance names govern anywhere.

check() RAISES on failure so pytest sees each case; the __main__ runner collects.
Run: python3 -m pytest <this file> -q   or   python3 kimi_gate_boundary_test.py
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "pre_tool_use.py")
SHARED = os.path.normpath(os.path.join(HERE, "..", "..", "_shared"))


def check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} — {detail}")


class StubDaemon:
    """Scripted MCP-over-HTTP daemon. Records every tools/call; scripts the verdicts.

    `policy` is what hestia_query_policy returns; `claim` is what hestia_gate_escalation_claim
    returns (None -> the default refusal-with-escalation-opened). Responses carry BOTH
    structuredContent and a content[0] text JSON so either unwrapping convention works."""

    def __init__(self, policy=None, claim=None):
        self.policy = policy if policy is not None else {"status": "decided",
                                                         "decision": "allow"}
        self.claim = claim
        self.calls = []  # [(tool_name, arguments)]

    def respond(self, name, args):
        if name == "hestia_connect":
            return {"sessionId": "stub-session"}
        if name == "hestia_begin_action":
            return {"actionId": "stub-action"}
        if name == "hestia_query_policy":
            return self.policy
        if name == "hestia_gate_escalation_claim":
            if self.claim is not None:
                return self.claim
            return {"claimed": False, "permits_write": False,
                    "escalation_id": "esc-stub-1",
                    "how_to_decide": "hestia gate approve esc-stub-1",
                    "retry_within_secs": 60}
        if name in ("hestia_request_witness", "hestia_witness_decision"):
            return {"ok": True}
        return {}

    def names(self):
        return [n for n, _ in self.calls]

    def witness_events(self):
        return [a.get("event_type") for n, a in self.calls
                if n == "hestia_request_witness"]


def _make_handler(stub):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def _send(self, obj, sid=None):
            body = json.dumps(obj).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            if sid:
                self.send_header("mcp-session-id", sid)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            n = int(self.headers.get("Content-Length") or 0)
            try:
                req = json.loads(self.rfile.read(n) or b"{}")
            except Exception:
                req = {}
            method = req.get("method")
            if method == "initialize":
                self._send({"jsonrpc": "2.0", "id": req.get("id"),
                            "result": {"protocolVersion": "2024-11-05", "capabilities": {},
                                       "serverInfo": {"name": "stub", "version": "0"}}},
                           sid="stub-mcp")
            elif method == "notifications/initialized":
                self._send({})
            elif method == "tools/call":
                params = req.get("params") or {}
                name, args = params.get("name"), params.get("arguments") or {}
                stub.calls.append((name, args))
                payload = stub.respond(name, args)
                self._send({"jsonrpc": "2.0", "id": req.get("id"),
                            "result": {"structuredContent": payload,
                                       "content": [{"type": "text",
                                                    "text": json.dumps(payload)}]}})
            else:
                self._send({"jsonrpc": "2.0", "id": req.get("id"), "result": {}})

    return Handler


class Server:
    def __init__(self, stub):
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _make_handler(stub))
        self.endpoint = f"http://127.0.0.1:{self.httpd.server_address[1]}/mcp"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


def make_workspace(tmp):
    """A synthetic HESTIA_WORKSPACE: hestia repo holding a COPY of the shared mechanism (what
    Gate 2 imports in-process), kimi's scope granted over it via a temp identity."""
    ws = os.path.join(tmp, "ws")
    shared_dst = os.path.join(ws, "hestia", "plugins", "_shared")
    os.makedirs(shared_dst)
    for f in ("hestia_gate_mechanism.py", "hestia_gate_core.py"):
        shutil.copy(os.path.join(SHARED, f), shared_dst)
    os.makedirs(os.path.join(ws, "hestia", "plugins", "kimi", "hooks"))
    os.makedirs(os.path.join(ws, "hestia", "forum", "kimi-code"))
    os.makedirs(os.path.join(ws, "hestia", "docs"))
    with open(os.path.join(ws, "identity.json"), "w", encoding="utf-8") as fh:
        json.dump({"role": "role:constellation:member",
                   "mrh": {"in_scope": ["repo:hestia"]}}, fh)
    return ws


def run_hook(ws, event, endpoint):
    """Execute the real hook the way the engine does: event JSON on stdin, exit code = verdict."""
    env = dict(os.environ)
    env.update({"HESTIA_WORKSPACE": ws,
                "HESTIA_KIMI_IDENTITY": os.path.join(ws, "identity.json"),
                "HESTIA_OBSERVE_DIR": os.path.join(ws, "observe"),
                "HESTIA_KIMI_GATE_MODE": "enforce",
                "HESTIA_ENDPOINT": endpoint})
    p = subprocess.run([sys.executable, HOOK], input=json.dumps(event),
                       capture_output=True, text=True, timeout=60,
                       cwd=os.path.join(ws, "hestia"), env=env)
    return p.returncode, p.stderr


def _event(tool, tool_input):
    return {"hook_event_name": "PreToolUse", "tool_name": tool, "tool_input": tool_input,
            "session_id": "boundary-test", "cwd": ""}


# ---- the arm nothing executed: a write to the gate, refused LOCALLY ----
def test_gate_file_write_refused_locally():
    with tempfile.TemporaryDirectory() as tmp:
        ws = make_workspace(tmp)
        stub = StubDaemon()
        srv = Server(stub)
        try:
            target = os.path.join(ws, "hestia", "plugins", "kimi", "hooks", "pre_tool_use.py")
            rc, err = run_hook(ws, _event("Write", {"file_path": target, "content": "x"}),
                               srv.endpoint)
            check("rc", rc == 2, f"rc={rc} stderr={err}")
            check("stderr-class", "gate-self" in err, err)
            check("escalation-surfaced", "esc-stub-1" in err, err)
            check("claim-made", "hestia_gate_escalation_claim" in stub.names(), stub.names())
            # The claimed-row join key (reply-2005/reply-2006): the per-wake host session rides
            # BOTH the connect and the claim, because it is the only session namespace that
            # appears on the outcome rows a claimed approval must join to.
            _conn = [a for n, a in stub.calls if n == "hestia_connect"]
            check("connect-carries-host-session",
                  _conn and _conn[0].get("host_session_id") == "boundary-test", stub.calls)
            _claim = [a for n, a in stub.calls if n == "hestia_gate_escalation_claim"]
            check("claim-carries-host-session",
                  _claim and _claim[0].get("host_session_id") == "boundary-test", stub.calls)
            check("witnessed", "gate_self_access" in stub.witness_events(), stub.calls)
            # Refused BEFORE the policy path — self-protection is pre-daemon, and an approved
            # gate edit is not a blanket allow: no begin_action may have run for this call.
            check("pre-daemon", "hestia_begin_action" not in stub.names(), stub.names())
        finally:
            srv.close()


def test_approved_gate_write_proceeds_to_policy():
    with tempfile.TemporaryDirectory() as tmp:
        ws = make_workspace(tmp)
        stub = StubDaemon(claim={"claimed": True, "permits_write": True,
                                 "decided_by": "test-operator", "decided_via": "test"})
        srv = Server(stub)
        try:
            target = os.path.join(ws, "hestia", "plugins", "kimi", "hooks", "pre_tool_use.py")
            rc, err = run_hook(ws, _event("Write", {"file_path": target, "content": "x"}),
                               srv.endpoint)
            check("rc", rc == 0, f"rc={rc} stderr={err}")
            check("approval-noted", "APPROVED" in err, err)
            # The approval lifts self-protection for THIS call only — the ordinary society-safety
            # query still ran.
            check("policy-ran", "hestia_begin_action" in stub.names(), stub.names())
        finally:
            srv.close()


def test_shared_mechanism_write_refused_anywhere():
    """A distinctive governance name governs wherever it lives — the shared mechanism is the
    fail-closed contract for every harness, so editing it is gate-self even off a hooks/ path."""
    with tempfile.TemporaryDirectory() as tmp:
        ws = make_workspace(tmp)
        stub = StubDaemon()
        srv = Server(stub)
        try:
            target = os.path.join(ws, "hestia", "plugins", "_shared", "hestia_gate_mechanism.py")
            rc, err = run_hook(ws, _event("Edit", {"file_path": target, "old_string": "a",
                                                   "new_string": "b"}), srv.endpoint)
            check("rc", rc == 2, f"rc={rc} stderr={err}")
            check("claim-made", "hestia_gate_escalation_claim" in stub.names(), stub.names())
        finally:
            srv.close()


def test_hooks_dir_only_names_do_not_overreach():
    """A common filename outside any hooks/ dir is ordinary work — the FP class that would fire
    on vendor trees and docs is exactly what _SELF_HOOKS_DIR_ONLY exists to spare."""
    with tempfile.TemporaryDirectory() as tmp:
        ws = make_workspace(tmp)
        stub = StubDaemon()
        srv = Server(stub)
        try:
            target = os.path.join(ws, "hestia", "docs", "witness.py")
            rc, err = run_hook(ws, _event("Write", {"file_path": target, "content": "x"}),
                               srv.endpoint)
            check("rc", rc == 0, f"rc={rc} stderr={err}")
            check("no-claim", "hestia_gate_escalation_claim" not in stub.names(), stub.names())
            check("policy-ran", "hestia_begin_action" in stub.names(), stub.names())
        finally:
            srv.close()


def test_ordinary_write_uses_policy_path():
    with tempfile.TemporaryDirectory() as tmp:
        ws = make_workspace(tmp)
        stub = StubDaemon()
        srv = Server(stub)
        try:
            target = os.path.join(ws, "hestia", "forum", "kimi-code", "post.md")
            rc, err = run_hook(ws, _event("Write", {"file_path": target, "content": "x"}),
                               srv.endpoint)
            check("rc", rc == 0, f"rc={rc} stderr={err}")
            check("no-claim", "hestia_gate_escalation_claim" not in stub.names(), stub.names())
            check("policy-ran", "hestia_begin_action" in stub.names(), stub.names())
        finally:
            srv.close()


def test_gate_file_read_allowed_and_witnessed():
    with tempfile.TemporaryDirectory() as tmp:
        ws = make_workspace(tmp)
        stub = StubDaemon()
        srv = Server(stub)
        try:
            target = os.path.join(ws, "hestia", "plugins", "kimi", "hooks", "pre_tool_use.py")
            rc, err = run_hook(ws, _event("Read", {"file_path": target}), srv.endpoint)
            check("rc", rc == 0, f"rc={rc} stderr={err}")
            check("witnessed", "gate_self_read" in stub.witness_events(), stub.calls)
            check("no-policy", "hestia_begin_action" not in stub.names(), stub.names())
        finally:
            srv.close()


def test_gate_write_refused_with_daemon_down():
    """Self-protection is never conditional on the daemon: endpoint dead, a gate-file write is
    still refused — locally, and fast (a gate-self exchange that hangs would fail OPEN on this
    engine). Port 9 (discard) is closed by convention; nothing in this test binds it."""
    with tempfile.TemporaryDirectory() as tmp:
        ws = make_workspace(tmp)
        target = os.path.join(ws, "hestia", "plugins", "kimi", "hooks", "pre_tool_use.py")
        rc, err = run_hook(ws, _event("Write", {"file_path": target, "content": "x"}),
                           "http://127.0.0.1:9/mcp")
        check("rc", rc == 2, f"rc={rc} stderr={err}")
        check("stderr-class", "gate-self" in err, err)


def test_ordinary_write_daemon_down_fails_closed():
    """The pre-existing fail-closed arm, executed end-to-end through the real hook: no verdict
    for a consequential act is a deny, never an allow."""
    with tempfile.TemporaryDirectory() as tmp:
        ws = make_workspace(tmp)
        target = os.path.join(ws, "hestia", "forum", "kimi-code", "post.md")
        rc, err = run_hook(ws, _event("Write", {"file_path": target, "content": "x"}),
                           "http://127.0.0.1:9/mcp")
        check("rc", rc == 2, f"rc={rc} stderr={err}")


def main():
    tests = [(n, f) for n, f in sorted(globals().items())
             if n.startswith("test_") and callable(f)]
    failed = []
    for name, fn in tests:
        try:
            fn()
            print(f"ok   {name}")
        except Exception as e:  # noqa: BLE001 — collect, don't stop: one red must not mask the rest
            failed.append(name)
            print(f"FAIL {name} — {e}")
    print(f"\n{len(tests) - len(failed)}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
