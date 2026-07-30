#!/usr/bin/env python3
"""Stage-2 escalation: the verdict path, against a stub daemon.

dp, 2026-07-29: "add escalation since it isn't a tested mechanism yet. do that in separate pr."
So the mechanism arrives with the tests that make its failure modes visible, and the ones that
matter are the REFUSALS -- an approval that works and a timeout that quietly allows would look
identical in a demo.

The protocol under test is deny-now / approve-out-of-band / retry:

    1st attempt  ->  no grant  ->  open an escalation, DENY NOW
    retry        ->  grant     ->  spent, write proceeds

It is not a wait, and the reason is measured rather than assumed: a PreToolUse hook that overruns
its harness timeout does not deny, it ALLOWS. See `the_budget_fits_inside_the_harness_timeout`
below, which is the guard that keeps this file's constants honest against plugin.json.

Runs under bare `python3` at module scope on purpose: CI executes these files directly (see
tools/ci_discovery.py), and a pytest-style file would be imported, define its functions, exit 0
and report green no matter what it asserts -- the exact shape tools/ci_selfexec_test.py refuses.

Every case stubs the daemon over real HTTP on a loopback port rather than monkeypatching the
client, so the envelope handling (`_dig`) is exercised the way the daemon actually answers.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HOOK = Path(__file__).resolve().parent / "pre_tool_use.py"
PLUGIN_JSON = Path(__file__).resolve().parents[1] / ".claude-plugin" / "plugin.json"

_spec = importlib.util.spec_from_file_location("ptu_under_test", HOOK)
ptu = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(ptu)

FAILS: list[str] = []
RAN: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    RAN.append(name)
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}" + (f"  -- {detail}" if not cond and detail else ""))
    if not cond:
        FAILS.append(name)


class _Stub(BaseHTTPRequestHandler):
    """Minimal MCP-over-HTTP daemon. `script` decides what each tool answers."""

    script: dict = {}

    def log_message(self, *_a):  # silence
        pass

    def handle_error(self, *_a):
        # A hook that gives up on a slow daemon hangs up mid-response. That BrokenPipe is the
        # budget WORKING; printing its traceback would make a passing run look broken.
        pass

    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0)
        try:
            req = json.loads(body or b"{}")
        except ValueError:
            req = {}
        name = (req.get("params") or {}).get("name", "")
        self.script.setdefault("_calls", []).append(name)
        if name == "hestia_gate_escalation_claim":
            payload = self.script.get("claim", {"granted": False, "why": "no approval on file"})
        elif name == "hestia_gate_escalation_open":
            payload = self.script.get("open", {"escalation_id": "abc123", "how_to_decide": "x"})
        else:
            payload = {}
        delay = self.script.get("delay_s")
        if delay:
            time.sleep(delay)
        # Wrapped in content[0].text, which is how the real daemon answers a tools/call.
        out = json.dumps({
            "jsonrpc": "2.0", "id": req.get("id", 1),
            "result": {"content": [{"type": "text", "text": json.dumps(payload)}]},
        }).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("mcp-session-id", "stub-session")
        self.send_header("Content-Length", str(len(out)))
        self.end_headers()
        self.wfile.write(out)


def run_with(script: dict, budget: float | None = None) -> tuple[str, str, dict, float]:
    """Point the hook at a stub daemon; return (verdict, detail, script incl. _calls, elapsed).

    `elapsed` times the HOOK CALL ONLY. Timing the whole helper measured teardown instead: a
    single-threaded HTTPServer.shutdown() blocks until the in-flight handler returns, so a stub
    sleeping 5s reported 5s even though the hook had already given up at 1s and hung up. The
    instrument has to be pinned to the same thing the claim is about.
    """
    _Stub.script = dict(script)
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Stub)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    old_budget = ptu.ESCALATION_TOTAL_BUDGET_S
    if budget is not None:
        ptu.ESCALATION_TOTAL_BUDGET_S = budget
    old_ep = os.environ.get("HESTIA_ENDPOINT")
    os.environ["HESTIA_ENDPOINT"] = f"http://127.0.0.1:{srv.server_port}/mcp"
    try:
        _t = time.monotonic()
        v, d = ptu.escalate_self_write("pre_tool_use.py", "Edit")
        return v, d, _Stub.script, time.monotonic() - _t
    finally:
        ptu.ESCALATION_TOTAL_BUDGET_S = old_budget
        if old_ep is None:
            os.environ.pop("HESTIA_ENDPOINT", None)
        else:
            os.environ["HESTIA_ENDPOINT"] = old_ep
        srv.shutdown()


GRANTED = {"granted": True, "escalation_id": "abc123", "decided_by": "dp",
           "decided_via": "local_cli"}

# --- the guard that this whole redesign exists to satisfy ----------------------------------
# kimi-code, reviewing #114: the hook waited 135s inside a harness that kills it at 5s, and a
# killed PreToolUse hook does not deny -- the tool call proceeds. Measured on Claude Code
# 2.1.220: identical deny hook, inside its timeout -> BLOCKED; sleeping past it -> EXECUTED.
#
# law_inject.py:39 already states this invariant in prose for its own budget and nothing
# enforced it. This reads the real number out of the real plugin.json, so tightening that
# timeout reddens this test instead of silently voiding the guarantee.
_manifest = json.loads(PLUGIN_JSON.read_text())
_pre_timeouts = [
    h.get("timeout")
    for grp in _manifest.get("hooks", {}).get("PreToolUse", [])
    for h in grp.get("hooks", [])
    if "pre_tool_use.py" in str(h.get("command", ""))
]
check("plugin.json declares a PreToolUse timeout we can check against",
      len(_pre_timeouts) == 1 and isinstance(_pre_timeouts[0], (int, float)), str(_pre_timeouts))
_harness = _pre_timeouts[0] if _pre_timeouts else 0
# Two RPCs worst case (claim, then open), each capped at ESCALATION_RPC_TIMEOUT_S, all of it
# inside the total budget -- and the whole path must still leave the hook time to emit its deny.
check("the_budget_fits_inside_the_harness_timeout",
      ptu.ESCALATION_TOTAL_BUDGET_S < _harness * 0.8,
      f"budget={ptu.ESCALATION_TOTAL_BUDGET_S}s vs harness timeout={_harness}s")
check("a single RPC cannot consume the whole budget",
      ptu.ESCALATION_RPC_TIMEOUT_S < ptu.ESCALATION_TOTAL_BUDGET_S,
      f"rpc={ptu.ESCALATION_RPC_TIMEOUT_S}s budget={ptu.ESCALATION_TOTAL_BUDGET_S}s")
check("the hook no longer has a multi-minute wall at all",
      not hasattr(ptu, "ESCALATION_WALL_S"),
      "ESCALATION_WALL_S still exists -- a hook that waits for a human fails OPEN")

# --- the one path that permits --------------------------------------------------------------
v, d, _, _e = run_with({"claim": GRANTED})
check("a granted claim permits the write", v == "approved", f"{v}: {d}")
check("the approval names who and by what channel", "dp" in d and "local_cli" in d, d)

# --- the first attempt: refuse, and ask ------------------------------------------------------
v, d, s, _e = run_with({})  # no grant, open succeeds
check("no grant refuses THIS call", v != "approved", f"{v}: {d}")
check("no grant opens an escalation to ask a human", "abc123" in d, d)
check("it claims BEFORE it opens -- an existing grant must never mint a new request",
      s["_calls"][0] == "hestia_gate_escalation_claim", str(s["_calls"]))
check("the refusal detail names the escalation, for the caller that was refused",
      "abc123" in d, d)

# --- every not-granted shape refuses, whatever the daemon calls it ---------------------------
for why, label in [
    ({"granted": False, "why": "denied by dp"}, "an explicit denial"),
    ({"granted": False, "why": "stale"}, "a stale grant"),
    ({"granted": False, "why": "already spent"}, "an already-spent grant"),
    ({"granted": False}, "a bare refusal with no reason"),
    ({}, "an empty answer"),
]:
    v, d, _, _e = run_with({"claim": why})
    check(f"{label} refuses", v != "approved", f"{v}: {d}")

# An old daemon that has never heard of claim answers {} -- it must not grant by failing to
# understand the question. (Covered above by "an empty answer"; this pins the truthiness rule.)
v, d, _, _e = run_with({"claim": {"granted": "true"}})
check("granted must be the BOOLEAN true, not a truthy string", v != "approved", f"{v}: {d}")

# --- the branch a member would attack ---------------------------------------------------------
# Only the daemon decides. There is no second field the hook could be talked into re-deriving
# "approved" from -- claim either hands over a grant or it does not.
v, d, _, _e = run_with({"claim": {"granted": False, "status": "approved", "permits_write": True,
                                 "why": "no approval on file"}})
check("approval-shaped noise around granted:false does NOT permit", v != "approved", f"{v}: {d}")

# --- the daemon is slow: the budget must end the call, not the harness -------------------------
v, d, _, _elapsed = run_with({"delay_s": 5.0}, budget=1.0)
check("a slow daemon is cut off by our own budget", v != "approved", f"{v}: {d}")
check("...and the hook returns well inside the harness timeout",
      _elapsed < _harness, f"took {_elapsed:.2f}s, harness kills at {_harness}s")

# --- unreachable daemon --------------------------------------------------------------------
_old = os.environ.get("HESTIA_ENDPOINT")
os.environ["HESTIA_ENDPOINT"] = "http://127.0.0.1:1/mcp"  # nothing listens on port 1
try:
    _t0 = time.monotonic()
    v, d = ptu.escalate_self_write("pre_tool_use.py", "Edit")
    _elapsed = time.monotonic() - _t0
finally:
    if _old is None:
        os.environ.pop("HESTIA_ENDPOINT", None)
    else:
        os.environ["HESTIA_ENDPOINT"] = _old
check("an unreachable daemon refuses rather than bypassing", v == "unreachable", f"{v}: {d}")
check("an unreachable daemon refuses FAST", _elapsed < _harness, f"took {_elapsed:.2f}s")

# --- attribution --------------------------------------------------------------------------
# Never guess a member id. #108 was exactly this defect one layer over: an unset variable
# produced a well-formed act attributed to a real member.
_old_p = os.environ.pop("HESTIA_MESH_PLUGIN", None)
_old_pid = os.environ.pop("HESTIA_PLUGIN_ID", None)
try:
    check("unset identity is 'unattributed', never a guessed member",
          ptu._escalation_plugin_id() == "unattributed", ptu._escalation_plugin_id())
finally:
    if _old_pid is not None:
        os.environ["HESTIA_PLUGIN_ID"] = _old_pid

os.environ["HESTIA_MESH_PLUGIN"] = "kimi-code"
check("a set identity is used as given", ptu._escalation_plugin_id() == "kimi-code")
if _old_p is None:
    os.environ.pop("HESTIA_MESH_PLUGIN", None)
else:
    os.environ["HESTIA_MESH_PLUGIN"] = _old_p

# --- the deny the CALLER sees ----------------------------------------------------------------
# A refusal is only worth the caller that hears it. The retry protocol is useless advice if it
# reaches only stderr and not the party that has to act on it.
import io
import contextlib
_buf = io.StringIO()
with contextlib.redirect_stderr(_buf):
    rc = ptu.deny_self_access("pre_tool_use.py", "Edit", "escalation abc123 opened")
_msg = _buf.getvalue()
check("the deny exits 2 (the only code the harness treats as a block)", rc == 2, str(rc))
check("the deny tells the caller to RETRY after approval", "RETRY" in _msg.upper(), _msg[:200])
check("the deny carries the escalation id through to the caller", "abc123" in _msg, _msg[:200])

# --- envelope handling --------------------------------------------------------------------
check("_dig reads a bare object", ptu._dig({"status": "approved"}, "status") == "approved")
check("_dig reads content[0].text JSON",
      ptu._dig({"content": [{"text": json.dumps({"status": "denied"})}]}, "status") == "denied")
check("_dig reads result.result.content[0].text -- the shape that broke the first version",
      ptu._dig({"result": {"result": {"content": [{"text": json.dumps({"granted": True})}]}}},
               "granted") is True)
check("_dig on a missing key is None, not a crash", ptu._dig({"a": 1}, "status") is None)

print()
if FAILS:
    print(f"ESCALATION TESTS FAILED: {len(FAILS)} of {len(RAN)}: {', '.join(FAILS)}")
    sys.exit(1)
print(f"all gate escalation checks passed ({len(RAN)} assertions)")
