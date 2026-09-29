#!/usr/bin/env python3
"""#1166 / #774 on the hook side: an unknown outcome is said out loud, and the request key is one rule.

GPT, on #1166: a timeout means the outcome is UNKNOWN, not that nothing happened. The claude-code
gate gives initialize + connect + claim one 1.5 s deadline (the harness kills a hook at 5 s and a
killed hook fails OPEN), so past it the daemon may have opened an escalation or spent an approval.
This drives the REAL gate module and the REAL shared mechanism against a stub daemon:

  A. the claim is sent and the answer never arrives -> verdict `unknown`, and the refusal says
     OUTCOME UNKNOWN with the request key and `hestia gate lookup`;
  B. the daemon refuses the connection, so no claim was ever sent -> `unreachable`, no "unknown";
  C. a `reclaimed` answer (#774) is a permit;
  D. the key is stable for an identical request, changes with the act or the session, and the
     claude-code gate and the shared mechanism (codex, kimi) compute the same key;
  E. the mechanism's own dead round trip also says OUTCOME UNKNOWN with the key.

Runs as a script (CI executes discovered files directly). The shared engine is named explicitly,
as CI's hook job does -- never an ambient checkout lookup.
"""
from __future__ import annotations

import contextlib
import hashlib
import importlib.util
import io
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
# A THROWAWAY seat home whose projection names THIS tree's engine. The gate loads its projection
# at import and exports every key over the ambient environment, so on a machine with an installed
# seat an ambient HESTIA_SHARED_DIR is overridden and the test would exercise the INSTALLED
# engine instead of the one under review (measured while writing this test).
import tempfile  # noqa: E402
sys.path.insert(0, str(REPO / "plugins" / "claude-code" / "tests"))
from projection_fixture import write_projection  # noqa: E402
_HOME = Path(tempfile.mkdtemp(prefix="reqkey-home-"))
write_projection(_HOME, "claude-code", {"HESTIA_SHARED_DIR": str(REPO / "plugins" / "_shared")})
os.environ["HESTIA_HOME"] = str(_HOME)
os.environ["HESTIA_SHARED_DIR"] = str(REPO / "plugins" / "_shared")
os.environ.pop("HESTIA_ENDPOINT", None)

_spec = importlib.util.spec_from_file_location(
    "ptu_reqkey", REPO / "plugins" / "claude-code" / "hooks" / "pre_tool_use.py")
ptu = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ptu)
# The mechanism exactly as the gate loads it (its loader pins sys.modules to the installed
# authority dir); a separately imported copy would be a different module object, and patching
# it would test nothing.
mech = ptu._load_mechanism()

FAILS: list[str] = []


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f"  <- {detail}"))
    if not ok:
        FAILS.append(name)


class Stub(BaseHTTPRequestHandler):
    claim_reply: dict = {}
    claim_stall_s: float = 0.0
    claims: list = []

    def log_message(self, *_a):
        pass

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0) or b"{}")
        params = body.get("params") or {}
        payload: dict = {}
        if body.get("method") == "tools/call":
            name = params.get("name")
            if name == "hestia_connect":
                payload = {"sessionId": "S-1"}
            elif name == "hestia_gate_escalation_claim":
                Stub.claims.append(params.get("arguments") or {})
                if Stub.claim_stall_s:
                    time.sleep(Stub.claim_stall_s)  # received, and answered too late
                payload = dict(Stub.claim_reply)
        out = json.dumps({"jsonrpc": "2.0", "id": body.get("id", 1),
                          "result": {"content": [{"type": "text", "text": json.dumps(payload)}]}}).encode()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("mcp-session-id", "stub")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)
        except Exception:  # the client already gave up
            pass


def serve():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}/mcp"


def call_hook(endpoint):
    os.environ["HESTIA_ENDPOINT"] = endpoint
    err = io.StringIO()
    with contextlib.redirect_stderr(err):
        v, d = ptu.request_self_write("pre_tool_use.py", "Bash", "Bash: git apply /tmp/p/x.patch",
                                      host_session_id="hs-1", invocation_key="toolu_INV1")
    return v, d, err.getvalue()


def main() -> int:
    srv, endpoint = serve()
    want_key = ptu.escalation_request_key(
        ptu._escalation_plugin_id(), "pre_tool_use.py", "Bash: git apply /tmp/p/x.patch", "hs-1")

    print("A. the claim is sent and its answer is lost")
    Stub.claims.clear()
    Stub.claim_reply, Stub.claim_stall_s = {"claimed": False, "escalation_id": "E1"}, ptu.ESCALATION_RPC_TIMEOUT_S + 1.0
    t0 = time.monotonic()
    v, d, err = call_hook(endpoint)
    took = time.monotonic() - t0
    check("A the claim reached the daemon", len(Stub.claims) == 1, Stub.claims)
    check("A the claim carried the request key", Stub.claims and Stub.claims[0].get("request_key") == want_key,
          Stub.claims)
    check("A the claim carried the invocation key (#1169)",
          Stub.claims and Stub.claims[0].get("invocation_key") == "toolu_INV1", Stub.claims)
    check("A verdict is `unknown`, not `unreachable`", v == "unknown", f"{v}: {d}")
    check("A the refusal says OUTCOME UNKNOWN", "OUTCOME UNKNOWN" in err, err)
    check("A ...names the key and the lookup", want_key in err and "hestia gate lookup" in err, err)
    check("A ...and says a re-issue is safe", "re-issuing this identical act is safe" in err, err)
    check("A the budget is unchanged: it gave up inside the harness kill", took < 4.0, f"{took:.2f}s")

    print("B. the claim never left the process")
    Stub.claim_stall_s = 0.0
    v, d, err = call_hook("http://127.0.0.1:1/mcp")
    check("B a refused connection is `unreachable`", v == "unreachable", f"{v}: {d}")
    check("B ...and does not claim an unknown outcome", "OUTCOME UNKNOWN" not in err, err)

    print("C. a reclaimed answer is the same permit")
    Stub.claim_reply = {"claimed": True, "permits_write": True, "reclaimed": True,
                        "decided_by": "operator", "decided_via": "operator_session", "escalation_id": "E1"}
    v, d, _ = call_hook(endpoint)
    check("C reclaimed permits", v == "approved", f"{v}: {d}")
    check("C ...and says it is the grant this request already spent", "already spent" in d, d)

    print("D. one key rule")
    k = ptu.escalation_request_key
    check("D stable for an identical request", k("m", "x", "act", "s") == k("m", "x", "act", "s"))
    check("D changes with the act", k("m", "x", "act", "s") != k("m", "x", "act2", "s"))
    check("D changes with the session", k("m", "x", "act", "s") != k("m", "x", "act", "s2"))
    check("D is a 64-hex sha256", len(want_key) == 64 and all(c in "0123456789abcdef" for c in want_key))
    captured = {}

    def fake_call(tool, args, **kw):
        captured.update(args)
        return {"claimed": False, "escalation_id": "E2"}

    real = mech.gate_self_call
    mech.gate_self_call = fake_call
    try:
        mech.claim_self_write("pre_tool_use.py", "Bash", "Bash: git apply /tmp/p/x.patch",
                              plugin_id=ptu._escalation_plugin_id(), role="r", client_name="c",
                              host_session_id="hs-1", invocation_key="call_XYZ")
    finally:
        mech.gate_self_call = real
    check("D the shared mechanism computes the SAME key as the claude-code gate",
          captured.get("request_key") == want_key, captured.get("request_key"))
    check("D the mechanism's claim carries the invocation key (#1169)",
          captured.get("invocation_key") == "call_XYZ", captured)

    print("D2. the society-safety begin carries the correlation key (#1169 execution evidence)")
    begins = []
    orig_do = Stub.do_POST

    def spy(self):  # noqa: N802
        n = int(self.headers.get("Content-Length", 0) or 0)
        body = json.loads(self.rfile.read(n) or b"{}")
        params = body.get("params") or {}
        name = params.get("name")
        payload = {}
        if name == "hestia_connect":
            payload = {"sessionId": "S-1"}
        elif name == "hestia_begin_action":
            begins.append(params.get("arguments") or {})
            payload = {"actionId": "A-1"}
        elif name == "hestia_query_policy":
            payload = {"status": "decided", "decision": "allow"}
        out = json.dumps({"jsonrpc": "2.0", "id": body.get("id", 1),
                          "result": {"content": [{"type": "text", "text": json.dumps(payload)}]}}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("mcp-session-id", "stub")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)

    Stub.do_POST = spy
    os.environ["HESTIA_ENDPOINT"] = endpoint
    try:
        mech.query_society_safety({"tool_name": "Bash", "tool_input": {"command": "true"}},
                                  plugin_id="codex", host_agent="codex", host_session_id="hs-1",
                                  correlation_key="call_XYZ")
    finally:
        Stub.do_POST = orig_do
    check("D2 begin_action carries correlation_key",
          bool(begins) and begins[0].get("correlation_key") == "call_XYZ", begins)

    print("E. the mechanism's dead round trip")
    mech.gate_self_call = lambda *a, **kw: None
    try:
        verdict, detail, esc, how = mech.claim_self_write(
            "pre_tool_use.py", "Bash", "Bash: git apply /tmp/p/x.patch", plugin_id="codex",
            role="r", client_name="c", host_session_id="hs-1")
    finally:
        mech.gate_self_call = real
    mkey = hashlib.sha256("\x1f".join(["codex", "pre_tool_use.py", "Bash: git apply /tmp/p/x.patch",
                                       "hs-1"]).encode()).hexdigest()
    check("E verdict is `unknown`", verdict == "unknown", verdict)
    check("E detail says OUTCOME UNKNOWN with the key and the lookup",
          "OUTCOME UNKNOWN" in detail and mkey in detail and "hestia gate lookup" in detail, detail)

    srv.shutdown()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): {FAILS}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
