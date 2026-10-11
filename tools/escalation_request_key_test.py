#!/usr/bin/env python3
"""#1166 / #774 on the hook side: an unknown outcome is said out loud, and the request key is one rule.

GPT, on #1166: a timeout means the outcome is UNKNOWN, not that nothing happened. Past the claim's
deadline the daemon may have opened an escalation or spent an approval. Since one-gate stage C
every seat claims through ONE function, the shared mechanism's `claim_self_write` (called by the
common gate's `decide`), so this drives that function against a stub daemon:

  A. the claim is sent and the answer never arrives -> verdict `unknown`, and the detail says
     OUTCOME UNKNOWN with the request key and `hestia gate lookup`;
  B. the daemon refuses the connection -> a refusal, never a permit;
  C. a `reclaimed` answer (#774) is a permit;
  D. the key is stable for an identical request, changes with the act or the session, and is the
     documented rule (sha256 over member, marker, act, host session);
  D2. the society-safety begin carries the correlation key;
  E. the mechanism's own dead round trip also says OUTCOME UNKNOWN with the key.

Before stage C the claude-code shim carried its own `request_self_write` and
`escalation_request_key`, and arm D proved the two copies agreed. There is one copy now; the
claude-code gate's former split between `unreachable` (no claim left the process) and `unknown`
is not kept by the mechanism, which says `unknown` for both (arm B) — a conservative statement
(re-issuing is safe either way), declared in the stage C PR.

Runs as a script (CI executes discovered files directly). The shared engine is named explicitly.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "plugins" / "_shared"))
os.environ.pop("HESTIA_ENDPOINT", None)
import hestia_gate_mechanism as mech  # noqa: E402

FAILS: list[str] = []
MARKER = "plugins/_shared"
ACT = "Bash: git apply /tmp/p/x.patch"


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


def claim(endpoint, budget=1.5):
    """The claim exactly as the common gate makes it: hard-stop declaration, invocation key,
    and a caller deadline."""
    os.environ["HESTIA_ENDPOINT"] = endpoint
    return mech.claim_self_write(MARKER, "Bash", ACT, plugin_id="claude-code", role="r",
                                 client_name="c", host_session_id="hs-1",
                                 invocation_key="toolu_INV1",
                                 supersession=mech.SUPERSESSION_HARD_STOP,
                                 deadline=time.monotonic() + budget)


def key(member, marker, act, session):
    return hashlib.sha256("\x1f".join([member, marker, act, session]).encode()).hexdigest()


def main() -> int:
    srv, endpoint = serve()
    want_key = key("claude-code", MARKER, ACT, "hs-1")

    print("A. the claim is sent and its answer is lost")
    Stub.claims.clear()
    Stub.claim_reply, Stub.claim_stall_s = {"claimed": False, "escalation_id": "E1"}, 3.0
    t0 = time.monotonic()
    v, d, _esc, _how = claim(endpoint)
    took = time.monotonic() - t0
    check("A the claim reached the daemon", len(Stub.claims) == 1, Stub.claims)
    check("A the claim carried the request key",
          Stub.claims and Stub.claims[0].get("request_key") == want_key, Stub.claims)
    check("A the claim carried the invocation key (#1169)",
          Stub.claims and Stub.claims[0].get("invocation_key") == "toolu_INV1", Stub.claims)
    check("A the claim declares the hard stop (#1169, GPT on ca5f394)",
          Stub.claims and Stub.claims[0].get("supersession") == "hard_stop", Stub.claims)
    check("A verdict is `unknown`", v == "unknown", f"{v}: {d}")
    check("A the detail says OUTCOME UNKNOWN", "OUTCOME UNKNOWN" in d, d)
    check("A ...names the key and the lookup", want_key in d and "hestia gate lookup" in d, d)
    check("A ...and says a re-issue is safe", "re-issuing this identical act is safe" in d, d)
    check("A the caller's deadline bounds the wait", took < 2.5, f"{took:.2f}s")

    print("B. the claim never left the process")
    Stub.claim_stall_s = 0.0
    v, d, _esc, _how = claim("http://127.0.0.1:1/mcp")
    check("B a refused connection is a refusal, never a permit", v != "approved", f"{v}: {d}")

    print("C. a reclaimed answer is the same permit")
    Stub.claim_reply = {"claimed": True, "permits_write": True, "reclaimed": True,
                        "decided_by": "operator", "decided_via": "operator_session", "escalation_id": "E1"}
    v, d, _esc, _how = claim(endpoint)
    check("C reclaimed permits", v == "approved", f"{v}: {d}")
    check("C ...and says it is the grant this request already spent", "already spent" in d, d)

    print("D. one key rule")
    captured = {}

    def fake_call(tool, args, **kw):
        captured.clear()
        captured.update(args)
        return {"claimed": False, "escalation_id": "E2"}

    def key_of(member, act, session):
        mech.claim_self_write(MARKER, "Bash", act, plugin_id=member, role="r", client_name="c",
                              host_session_id=session)
        return captured.get("request_key")

    real = mech.gate_self_call
    mech.gate_self_call = fake_call
    try:
        k1, k1b = key_of("m", "act", "s"), key_of("m", "act", "s")
        k2, k3 = key_of("m", "act2", "s"), key_of("m", "act", "s2")
        k_doc = key_of("claude-code", ACT, "hs-1")
    finally:
        mech.gate_self_call = real
    check("D stable for an identical request", k1 == k1b)
    check("D changes with the act", k1 != k2)
    check("D changes with the session", k1 != k3)
    check("D is the documented rule", k_doc == want_key, k_doc)
    check("D is a 64-hex sha256", len(want_key) == 64 and all(c in "0123456789abcdef" for c in want_key))

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
        verdict, detail, _esc, _how = mech.claim_self_write(
            MARKER, "Bash", ACT, plugin_id="codex", role="r", client_name="c",
            host_session_id="hs-1")
    finally:
        mech.gate_self_call = real
    mkey = key("codex", MARKER, ACT, "hs-1")
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
