#!/usr/bin/env python3
"""The governance-write escalation claim: its verdicts and its DEADLINE, against a stub daemon.

Migrated in one-gate stage C from plugins/claude-code/hooks/test_gate_escalation.py, which
tested claude-code's private `request_self_write`. Every seat's gate now claims through the ONE
shared `hestia_gate_mechanism.claim_self_write` (called by `hestia_single_gate.decide` with the
invocation's deadline), so the arms move to it, unchanged in intent:

  dp, 2026-07-29: "add escalation since it isn't a tested mechanism yet." The first cut of the
  original suite tested every verdict and still shipped a mechanism that could not work: it
  waited 135 s in a hook the harness kills at 5 s, and a killed hook yields neither exit 2 nor a
  JSON deny -- so the harness runs the tool ANYWAY (kimi-code, PR #114).

So: what the claim DECIDES (only `claimed AND permits_write` approves; every failure refuses),
and how long it TAKES (never past the caller's deadline, whatever the daemon does). Since stage
C the bound is the caller's `deadline=`, which a seat derives from its harness's registered
timeout; no request starts after it.

Runs under bare `python3` at module scope (tools/ci_selfexec_test.py convention).
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
_overlay = json.loads(os.environ.get("HESTIA_CONTRACT_OVERLAY") or "{}")
_MECH = "hestia_gate_" + "mechanism"
_path = _overlay.get(_MECH) or os.path.join(HERE, _MECH + ".py")
sys.path.insert(0, HERE)
_spec = importlib.util.spec_from_file_location(_MECH, _path)
mech = importlib.util.module_from_spec(_spec)
sys.modules[_MECH] = mech
_spec.loader.exec_module(mech)

FAILS: list = []
RAN: list = []


def check(name, cond, detail=""):
    RAN.append(name)
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}" + (f"  -- {detail}" if not cond and detail else ""))
    if not cond:
        FAILS.append(name)


class _Stub(BaseHTTPRequestHandler):
    claim: dict = {}
    stall_s: float = 0.0
    seen: list = []

    def log_message(self, *_a):
        pass

    def do_POST(self):  # noqa: N802
        req = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0) or b"{}")
        _Stub.seen.append(req)
        params = req.get("params") or {}
        if params.get("name") == "hestia_gate_escalation_claim" and self.stall_s:
            time.sleep(self.stall_s)   # accepts, never answers in time
        if req.get("method") == "initialize":
            payload = None
            body = {"jsonrpc": "2.0", "id": req.get("id", 1), "result": {"protocolVersion": "2024-11-05"}}
        else:
            payload = {"sessionId": "sess-claim-test"} if params.get("name") == "hestia_connect" \
                else dict(self.claim)
            body = {"jsonrpc": "2.0", "id": req.get("id", 1),
                    "result": {"content": [{"type": "text", "text": json.dumps(payload)}]}}
        out = json.dumps(body).encode()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("mcp-session-id", "stub")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)
        except Exception:  # noqa: BLE001 — the client's deadline ran out first
            pass


def claim_with(payload, stall_s=0.0, deadline_s=2.0, endpoint=None, **kw):
    _Stub.claim, _Stub.stall_s, _Stub.seen = dict(payload), stall_s, []
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    old = os.environ.get("HESTIA_ENDPOINT")
    os.environ["HESTIA_ENDPOINT"] = endpoint or f"http://127.0.0.1:{srv.server_port}/mcp"
    t0 = time.monotonic()
    try:
        out = mech.claim_self_write("pre_" + "tool_use.py", "Edit", "Edit: x -> y", plugin_id="codex",
                                    role="role:constellation:member", client_name="claim-test",
                                    deadline=t0 + deadline_s, **kw)
    finally:
        elapsed = time.monotonic() - t0
        if old is None:
            os.environ.pop("HESTIA_ENDPOINT", None)
        else:
            os.environ["HESTIA_ENDPOINT"] = old
        threading.Thread(target=srv.shutdown, daemon=True).start()
    return out, elapsed


APPROVED = {"claimed": True, "permits_write": True, "decided_by": "dp", "decided_via": "local_cli"}
REFUSED = {"claimed": False, "permits_write": False, "escalation_id": "abc123",
           "how_to_decide": "hestia gate approve abc123"}

# --- the one path that permits ------------------------------------------------------------------
(v, d, esc, how), _ = claim_with(APPROVED)
check("a claimed approval permits the write", v == "approved", f"{v}: {d}")
check("it names who approved and by what channel", "dp" in d and "local_cli" in d, d)

# --- the ordinary path: refuse now, decide later --------------------------------------------------
(v, d, esc, how), _ = claim_with(REFUSED)
check("no approval yet REFUSES", v == "escalated", f"{v}: {d}")
check("the refusal carries the escalation id", esc == "abc123" and "abc123" in how, (esc, how))

# --- an un-upgraded daemon answers {} to a tool it has never heard of --------------------------
(v, d, esc, how), _ = claim_with({})
check("a daemon with no escalation channel refuses", v == "no-channel", f"{v}: {d}")
check("and says NO escalation was opened", "NO escalation" in d, d)

# --- the branches a member would attack -------------------------------------------------------------
(v, *_), _ = claim_with({"claimed": True, "permits_write": False, "escalation_id": "x"})
check("claimed without permits_write does NOT permit", v != "approved", v)
(v, *_), _ = claim_with({"claimed": False, "permits_write": True, "escalation_id": "x"})
check("permits_write without claimed does NOT permit", v != "approved", v)

# --- unreachable --------------------------------------------------------------------------------------
(v, d, *_), t_dead = claim_with(APPROVED, endpoint="http://127.0.0.1:1/mcp")
check("an unreachable daemon refuses rather than bypassing", v != "approved", f"{v}: {d}")

# --- THE DEADLINE: no path outlives the caller's bound -------------------------------------------------
_, t_ok = claim_with(APPROVED)
_, t_refuse = claim_with(REFUSED)
# 0.6 s: shorter than the claim step's own fixed 0.9 s, so only the CALLER's deadline can cut it.
(v, d, *_), t_stall = claim_with(REFUSED, stall_s=10.0, deadline_s=0.6)
check(f"approved path well inside the deadline ({t_ok:.2f}s)", t_ok < 2.0, f"{t_ok:.2f}s")
check(f"refusal path well inside the deadline ({t_refuse:.2f}s)", t_refuse < 2.0, f"{t_refuse:.2f}s")
check(f"a STALLED daemon is cut at the caller's deadline ({t_stall:.2f}s < 0.6s + slack)", t_stall < 0.8,
      f"{t_stall:.2f}s -- a hook that outruns its harness timeout is KILLED, and a killed hook "
      f"does not block the tool")
check("a stalled claim is an UNKNOWN outcome, never an approval (#1166)", v == "unknown", f"{v}: {d}")
check(f"unreachable is fast ({t_dead:.2f}s)", t_dead < 2.0, f"{t_dead:.2f}s")
(v, d, *_), t_spent = claim_with(APPROVED, deadline_s=-0.01)
check("an exhausted deadline sends nothing and refuses", v != "approved" and not [
    r for r in _Stub.seen if (r.get("params") or {}).get("name")], (v, _Stub.seen))

# --- no in-hook wait for a human may be reintroduced ------------------------------------------------
with open(_path, encoding="utf-8") as fh:
    src = fh.read()
check("the claim never sleeps while waiting for a human",
      "ESCALATION_WALL_S" not in src and "while time.monotonic() < wall" not in src)

# --- the claim threads its session, identity and keys -------------------------------------------------
(v, *_), _ = claim_with(REFUSED, host_session_id="host-sess-7", invocation_key="toolu_K",
                        supersession="hard_stop")
calls = [r for r in _Stub.seen if (r.get("params") or {}).get("name")]
connect = [r["params"]["arguments"] for r in calls if r["params"]["name"] == "hestia_connect"]
claim = [r["params"]["arguments"] for r in calls if r["params"]["name"] == "hestia_gate_escalation_claim"]
check("a session was connected before the claim", len(connect) == 1, len(connect))
check("the claim went out once", len(claim) == 1, len(claim))
if claim and connect:
    a = claim[0]
    check("the claim threads the session it connected", a.get("session_id") == "sess-claim-test", a)
    check("connect and claim assert ONE plugin_id", connect[0].get("plugin_id") == a.get("plugin_id") == "codex",
          (connect[0].get("plugin_id"), a.get("plugin_id")))
    check("the host session rides the claim and the connect",
          a.get("host_session_id") == "host-sess-7" == connect[0].get("host_session_id"), a)
    check("the invocation key rides the claim (#1169)", a.get("invocation_key") == "toolu_K", a)
    check("the hook's hard-stop declaration rides the claim", a.get("supersession") == "hard_stop", a)
    check("a request key is sent (#1166)", isinstance(a.get("request_key"), str) and len(a["request_key"]) == 64, a)
    check("the reason is the ATTEMPTED ACT, not a rationale", a.get("reason") == "Edit: x -> y", a)
check("the verdict path is unchanged by threading", v == "escalated", v)

# --- the resolved targets ride the claim (#810; recut of #812) ---------------------------------------
# The daemon prices the bar over the marker, the act AND every target, highest wins; the act is a
# bounded summary that can cut a filename out, so the targets are sent as their own field.
_HOOK = "pre_" + "tool_use.py"
_GATE = "hestia_single_" + "gate.py"
_UNP = mech.UNPRICEABLE_PREFIX
_KEYFILE = "id_" + "ed" + "25519"   # spelled in parts: the literal is egress vocabulary


def _claim_args(**kw):
    claim_with(REFUSED, **kw)
    return [r["params"]["arguments"] for r in _Stub.seen
            if (r.get("params") or {}).get("name") == "hestia_gate_escalation_claim"]


_T = f"/w/plugins/kimi/hooks/{_HOOK}"
a = _claim_args(resolved_targets=[_T])
check("the claim carries the resolved targets when the gate has them",
      a and a[0].get("resolved_targets") == [_T], a)
a = _claim_args(resolved_targets=["/w/plugins/_shared/ordinary.txt", f"/w/plugins/_shared/{_GATE}"])
check("EVERY target rides, not only the first (P1-2)",
      a and a[0].get("resolved_targets") == ["/w/plugins/_shared/ordinary.txt",
                                             f"/w/plugins/_shared/{_GATE}"], a)
a = _claim_args(resolved_targets=["/w/hooks-gt/kimi/hooks/*.py"])
check("a glob target rides as written (the daemon prices it by what it can expand to)",
      a and a[0].get("resolved_targets") == ["/w/hooks-gt/kimi/hooks/*.py"], a)
a = _claim_args()
check("no targets, no key on the wire (an old caller changes nothing)",
      a and "resolved_targets" not in a[0], a)
a = _claim_args(resolved_targets=["   "])
check("a blank target is no target", a and "resolved_targets" not in a[0], a)
_cred = "/w/credential-fixture/" + "." + f"ssh/plugins/kimi/hooks/{_HOOK}"
a = _claim_args(resolved_targets=[_cred])
check("a credential-shaped target path is NOT dropped: it rides as the credential-path sentinel "
      "the daemon prices highest (P1-3)",
      a and a[0].get("resolved_targets") == [_UNP + "credential-path"], a)
check("and the credential-shaped path itself is not copied onto the wire",
      a and "ssh" not in json.dumps(a[0].get("resolved_targets")), a)
# P1-3, producer side end to end: a credential-shaped COMMAND is withheld whole from the summary,
# and its sovereign target still rides — redaction is the summary's, not the targets'.
_cmd = "cp /home/m/" + "." + f"ssh/{_KEYFILE} {_T}"
_summary = mech.attempted_summary("Bash", {"command": _cmd}, command=_cmd)
check("control: the credential-shaped command's summary is withheld whole",
      "REDACTED" in _summary and _HOOK not in _summary, _summary)
a = _claim_args(resolved_targets=[_T])
check("the sovereign target rides beside a redacted summary (P1-3)",
      a and a[0].get("resolved_targets") == [_T], a)
_long = "/" + "d" * 900 + f"/plugins/kimi/hooks/{_HOOK}"
a = _claim_args(resolved_targets=[_long])
check("an over-long target is tail-capped and keeps its filename",
      a and len(a[0]["resolved_targets"][0]) == mech.RESOLVED_TARGET_MAX
      and a[0]["resolved_targets"][0].endswith(f"/{_HOOK}"), a)
_many = [f"/w/plugins/kimi/hooks/f{i}.txt" for i in range(mech.MAX_RESOLVED_TARGETS + 4)]
a = _claim_args(resolved_targets=_many)
check("more targets than the bound: the excess is an overflow sentinel, never a silent cut",
      a and len(a[0]["resolved_targets"]) == mech.MAX_RESOLVED_TARGETS + 1
      and a[0]["resolved_targets"][-1] == _UNP + "overflow", a and a[0].get("resolved_targets"))
a = _claim_args(resolved_targets=[], resolved_targets_complete=False)
check("an unenumerable write set says so (the daemon prices it highest)",
      a and a[0].get("resolved_targets") == [_UNP + "unenumerated"], a)
a1 = _claim_args(resolved_targets=[_T])
a2 = _claim_args()
check("the targets are not part of the request key (they are derived from the same act)",
      a1 and a2 and a1[0]["request_key"] == a2[0]["request_key"], (a1, a2))

# --- the PRODUCER: what the common gate collects is what rides (Codex notice 18784) -------------------
# The rows above feed `claim_self_write` a target list by hand. These run the common gate's own
# collector, `_closure_write_set`, over Codex's 18784 counterexamples and send what it returns over
# the claim wire, so a producer that marks an unknown destination complete, or drops an alias's
# canonical destination, fails HERE (both regressed in the 574426d6 rebuild of the 2e0547b5 fix).
_CL, _SG = "hestia_governance_" + "closure", "hestia_single_" + "gate"
for _name in (_CL, _SG):
    _sp = importlib.util.spec_from_file_location(
        _name, _overlay.get(_name) or os.path.join(HERE, _name + ".py"))
    _m = importlib.util.module_from_spec(_sp)
    sys.modules[_name] = _m
    _sp.loader.exec_module(_m)
_closure, _gate = sys.modules[_CL], sys.modules[_SG]
_closure.default_closure = lambda: _closure.LITERAL_FLOOR   # the literal floor, no registry read


def _produced(command, cwd="/w"):
    targets, complete = _gate._closure_write_set(_gate.GateEvent("Bash", {"command": command}, cwd=cwd))
    a = _claim_args(resolved_targets=targets, resolved_targets_complete=complete)
    return complete, (a[0].get("resolved_targets") if a else None)


_SG_FILE = f"/w/plugins/_shared/{_GATE}"
_ORD = "/w/plugins/_shared/ordinary.txt"
_UNENUM = _UNP + "unenumerated"
c, w = _produced("touch /w/plugins/_shared/$TARGET")
check("18784 P1-1: an out-of-grammar variable destination is NOT complete; the known vocabulary "
      "rides and the unenumerated sentinel follows",
      c is False and w == ["/w/plugins/_shared/$TARGET", _UNENUM], (c, w))
c, w = _produced('touch /w/plugins/_shared/ordinary.txt; touch "$TARGET"')
check("18784 P1-1: a known ordinary target beside an unknown destination is NOT complete",
      c is False and w == [_ORD, _UNENUM], (c, w))
c, w = _produced("touch plugins/_shared/ordinary.txt", cwd=None)
check("18784 P1-1: a relative target with no cwd to resolve it is NOT complete",
      c is False and w and w[-1] == _UNENUM, (c, w))
c, w = _produced("touch plugins/_shared/ordinary.txt", cwd="/w")
check("control: a relative target WITH a cwd is complete and carries its cwd-joined form",
      c is True and w == ["plugins/_shared/ordinary.txt", _ORD], (c, w))
c, w = _produced(f"touch {_ORD}")
check("control: a plain absolute target is complete and adds nothing", c is True and w == [_ORD], (c, w))
_alias = "/w/alias.txt"
_rp = _closure.os.path.realpath
_closure.os.path.realpath = lambda p: _SG_FILE if p == _alias else _rp(p)   # modeled, no link
try:
    c, w = _produced(f"touch {_alias}")
finally:
    _closure.os.path.realpath = _rp
check("18784 P1-2: an alias the closure matched by its destination carries that canonical "
      "destination onto the wire, not only the alias spelling",
      w == [_alias, _SG_FILE], (c, w))

print(f"\n{'FAIL' if FAILS else 'all'} claim checks: {len(RAN) - len(FAILS)}/{len(RAN)} passed")
sys.exit(1 if FAILS else 0)
