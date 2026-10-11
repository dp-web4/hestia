#!/usr/bin/env python3
"""#1169: a superseded invocation stops at EVERY seat, in EVERY rollout mode.

GPT's hold on ca5f394: the daemon fences the ORIGINAL invocation when a reclaim re-delivers its
permit (begin_action answers `_hestia_error.code == "hestia.invocation_superseded"`), but the
shared mechanism folded that refusal into an ordinary no-verdict, and the codex and kimi hooks let
a no-verdict through in warn-rollout mode. So `claim A -> reclaim B -> A's begin is fenced` still
exited 0 for A in warn mode -- A ran, and B held the replacement permit.

Supersession is an INTEGRITY fence, not a policy verdict: the call's permit was transferred to
another invocation. It must stop the call regardless of rollout mode.

Since one-gate stage C every seat's shim is pure translation and the law is the common gate's
`decide`, so this drives each seat's REAL `to_event` into the REAL `decide` and the REAL shared
mechanism (`claim_self_write` -> `query_society_safety` -> `record_decision`) against a stub
daemon that speaks the handler's wire shapes. Only the policy snapshot is stubbed. For each of the
four seats x {warn, enforce}:

  A. claim A succeeds; B's reclaim lands before A's begin (the stub fences A's invocation as the
     claim returns); A's begin is refused as superseded -> deny `invocation.superseded`;
  B. the REPLACEMENT invocation (reclaimed permit, unfenced begin) -> allowed: the fence does not
     stop the call that now owns the permit;
  C. an ORDINARY begin rejection is not mistaken for supersession. (Before stage C it warned and
     ran in warn mode; under "no verdict, no act" (dp 2026-10-01) it is denied in every rollout,
     so the arm now asserts the distinction, not the old warn.)
  D. the claim declares `supersession: "hard_stop"` (the daemon refuses a reclaim without it).

Plus the mechanism alone: the superseded refusal is a verdict with `superseded=True`, keyed on the
machine-readable code (not message text), and the daemon's constant matches the mechanism's.

Staging seams (unset in the repo and in CI): HESTIA_CONTRACT_OVERLAY, HESTIA_CONTRACT_SHIMS.
Runs as a script (CI executes discovered files directly).
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SHARED = REPO / "plugins" / "_shared"
# A THROWAWAY home, set BEFORE any import: nothing here may reach a live seat.
_HOME = Path(tempfile.mkdtemp(prefix="supersede-home-"))
os.environ["HOME"] = str(_HOME)
os.environ["HESTIA_HOME"] = str(_HOME / ".hestia")
os.environ["HESTIA_SHARED_DIR"] = str(SHARED)
os.environ["HESTIA_WORKSPACE"] = str(_HOME)
for _k in ("HESTIA_ENDPOINT", "HESTIA_ROLE", "HESTIA_TEST_SABOTAGE", "HESTIA_GATE_MODE"):
    os.environ.pop(_k, None)

_OVERLAY = json.loads(os.getenv("HESTIA_CONTRACT_OVERLAY") or "{}")
_SHIMS = json.loads(os.getenv("HESTIA_CONTRACT_SHIMS") or "{}")
sys.path.insert(0, str(SHARED))
for _n in ("hestia_gate_core", "hestia_governance_closure", "hestia_gate_mechanism",
           "hestia_single_gate"):
    if _OVERLAY.get(_n):
        _s = importlib.util.spec_from_file_location(_n, _OVERLAY[_n])
        _mod = importlib.util.module_from_spec(_s)
        sys.modules[_n] = _mod
        _s.loader.exec_module(_mod)
import hestia_single_gate as g  # noqa: E402

mech = g.mechanism
SEAT_SHIM = {"claude-code": "plugins/claude-code/hooks/pre_tool_use.py",
             "codex": "plugins/codex/hooks/pre_tool_use.py",
             "kimi": "plugins/kimi/hooks/pre_tool_use.py",
             "gemini": "plugins/gemini/hooks/before_tool.py"}
NATIVE = {"claude-code": ("PreToolUse", "Bash", "tool_use_id"),
          "codex": ("PreToolUse", "Bash", "tool_use_id"),
          "kimi": ("PreToolUse", "Shell", "tool_call_id"),
          "gemini": ("BeforeTool", "run_shell_command", None)}
GOVERNED = str(_HOME / "hestia" / "plugins" / "_shared" / "hestia_gate_core.py")

FAILS: list[str] = []


def check(name, ok, detail=""):
    print(f"  {'ok  ' if ok else 'FAIL'} {name}" + ("" if ok else f"  <- {detail}"))
    if not ok:
        FAILS.append(name)


def shim(seat):
    spec = importlib.util.spec_from_file_location(
        f"supersede_shim_{seat.replace('-', '_')}", _SHIMS.get(seat) or REPO / SEAT_SHIM[seat])
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SUPERSEDED = "hestia.invocation_superseded"


class Stub(BaseHTTPRequestHandler):
    """The daemon, in its wire shapes. `fence_on_claim`: fence the claiming invocation the moment
    its own claim returns -- the race GPT's re-review names."""
    claims: list = []
    begins: list = []
    fenced: set = set()
    fence_on_claim: bool = False
    reclaim: bool = False
    begin_error: str | None = None   # an ordinary (non-supersession) begin rejection

    def log_message(self, *_a):
        pass

    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0) or b"{}")
        params = body.get("params") or {}
        args = params.get("arguments") or {}
        name = params.get("name")
        payload: dict = {}
        if name == "hestia_connect":
            payload = {"sessionId": "S-1"}
        elif name == "hestia_gate_escalation_claim":
            Stub.claims.append(args)
            payload = {"claimed": True, "permits_write": True, "escalation_id": "E1",
                       "decided_by": "operator", "decided_via": "operator_session"}
            if Stub.reclaim:
                payload["reclaimed"] = True
            if Stub.fence_on_claim and args.get("invocation_key"):
                Stub.fenced.add(args["invocation_key"])  # B's reclaim lands before A's begin
        elif name == "hestia_begin_action":
            Stub.begins.append(args)
            k = args.get("correlation_key")
            if k in Stub.fenced:
                payload = {"_hestia_error": {
                    "code": SUPERSEDED,
                    "message": f"invocation {k} was superseded by a reclaim of escalation E1",
                    "data": {"correlation_key": k, "escalation_id": "E1", "fenced_at": 1}}}
            elif Stub.begin_error:
                payload = {"_hestia_error": {"code": Stub.begin_error, "message": "x", "data": {}}}
            else:
                payload = {"actionId": "act-" + str(k)}
        elif name == "hestia_query_policy":
            payload = {"status": "decided", "decision": "allow"}
        elif name == "hestia_witness_decision":
            d = args.get("decision")
            payload = {"witnessEntryHash": "b" * 64,
                       "eventType": "policy_allow" if d == "allow" else "policy_decision",
                       "decision": d, "recorded": "appended", "charged": d != "allow",
                       "actionId": args.get("action_id"),
                       "correlationKey": args.get("correlation_key"), "updatedTrust": None}
        out = json.dumps({"jsonrpc": "2.0", "id": body.get("id", 1),
                          "result": {"content": [{"type": "text", "text": json.dumps(payload)}]}}).encode()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("mcp-session-id", "stub")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)
        except Exception:
            pass


def reset(**kw):
    Stub.claims, Stub.begins, Stub.fenced = [], [], set()
    Stub.fence_on_claim, Stub.reclaim, Stub.begin_error = False, False, None
    for k, v in kw.items():
        setattr(Stub, k, v)


# The policy snapshot decides nothing here: scope grants the throwaway workspace's `hestia` repo,
# so the governed write reaches its real gate-self claim path and the ordinary law allows what
# follows.
mech.fetch_policy_snapshot = lambda *a, **k: {"in_scope": ["hestia"], "role": "citizen"}


def run(seat, mod, mode, inv):
    event_name, tool, id_key = NATIVE[seat]
    raw = {"hook_event_name": event_name, "tool_name": tool, "session_id": "hs-1",
           "cwd": str(_HOME), "tool_input": {"command": f"cp /tmp/new_core.py {GOVERNED}"}}
    if id_key:
        raw[id_key] = inv
    else:
        raw["tool_input"]["description"] = inv   # gemini carries no id: vary the content key
    profile = g.GateProfile(**{**mod.PROFILE, "identity_path": str(_HOME / "identity.json"),
                                "observe_dir": str(_HOME / "observe"),
                                "home_markers": (str(_HOME / f".{seat}"),)})
    return g.decide(mod.to_event(g, raw), profile, rollout=mode,
                    deadline=time.monotonic() + 10.0)


def main() -> int:
    srv = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    os.environ["HESTIA_ENDPOINT"] = f"http://127.0.0.1:{srv.server_port}/mcp"

    print("0. the mechanism alone")
    reset(fenced={"inv-M"})
    v = mech.query_society_safety({"tool_name": "Bash", "tool_input": {"command": "true"}},
                                  plugin_id="codex", host_agent="codex", host_session_id="hs-1",
                                  correlation_key="inv-M")
    check("0 superseded begin -> not allowed", v.allow is False, v)
    check("0 ...and marked superseded (a distinct, unconditional stop)",
          getattr(v, "superseded", False) is True, v)
    check("0 ...keyed on the code: the constant is the daemon's",
          getattr(mech, "INVOCATION_SUPERSEDED", None) == SUPERSEDED,
          getattr(mech, "INVOCATION_SUPERSEDED", None))
    check("0 the daemon emits that exact code",
          f'"{SUPERSEDED}"' in (REPO / "core" / "src" / "server" / "handler.rs").read_text())
    reset(begin_error="hestia.some_other_rejection")
    v = mech.query_society_safety({"tool_name": "Bash", "tool_input": {"command": "true"}},
                                  plugin_id="codex", host_agent="codex", host_session_id="hs-1",
                                  correlation_key="inv-N")
    check("0 an ordinary begin rejection is NOT superseded",
          v.allow is False and getattr(v, "superseded", False) is False, v)

    for seat in SEAT_SHIM:
        mod = shim(seat)
        for mode in ("warn", "enforce"):
            tag = f"{seat}/{mode}"
            print(tag)
            reset(fence_on_claim=True)
            d = run(seat, mod, mode, "inv-A")
            keys = [c.get("invocation_key") for c in Stub.claims]
            check(f"A {tag} one claim, carrying the invocation key", len(keys) == 1 and keys[0], Stub.claims)
            check(f"D {tag} the claim declares supersession hard_stop",
                  bool(Stub.claims) and Stub.claims[0].get("supersession") == "hard_stop", Stub.claims)
            check(f"A {tag} A's begin carried the same key",
                  [b.get("correlation_key") for b in Stub.begins] == keys, Stub.begins)
            check(f"A {tag} superseded A is denied as superseded",
                  d.decision == "deny" and d.rule == "invocation.superseded", d)

            reset(reclaim=True, fenced={"some-other-invocation"})
            d = run(seat, mod, mode, "inv-B")
            check(f"B {tag} replacement B is allowed", d.decision == "allow", d)

            reset(begin_error="hestia.some_other_rejection")
            d = run(seat, mod, mode, "inv-C")
            check(f"C {tag} an ordinary no-verdict is not called superseded",
                  d.decision == "deny" and d.rule != "invocation.superseded", d)

    srv.shutdown()
    print()
    if FAILS:
        print(f"{len(FAILS)} FAILURE(S): {FAILS}")
        return 1
    print("ALL CHECKS PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
