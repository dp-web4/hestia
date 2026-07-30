#!/usr/bin/env python3
"""Stage-2 escalation: the verdict path, against a stub daemon.

dp, 2026-07-29: "add escalation since it isn't a tested mechanism yet. do that in separate pr."
So the mechanism arrives with the tests that make its failure modes visible, and the ones that
matter are the REFUSALS -- an approval that works and a timeout that quietly allows would look
identical in a demo.

Runs under bare `python3` at module scope on purpose: CI executes these files directly (see
tools/ci_discovery.py), and a pytest-style file would be imported, define its functions, exit 0
and report green no matter what it asserts -- the exact shape tools/ci_selfexec_test.py refuses.

Every case stubs the daemon over real HTTP on a loopback port rather than monkeypatching the
client, so the envelope handling (`_dig`) is exercised the way the daemon actually answers.
"""
from __future__ import annotations

import importlib.util
import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HOOK = Path(__file__).resolve().parent / "pre_tool_use.py"

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
    """Minimal MCP-over-HTTP daemon. `script` decides what poll answers."""

    script: dict = {}

    def log_message(self, *_a):  # silence
        pass

    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0)
        try:
            req = json.loads(body or b"{}")
        except ValueError:
            req = {}
        name = (req.get("params") or {}).get("name", "")
        if name == "hestia_gate_escalation_open":
            payload = self.script.get("open", {"escalation_id": "abc123", "how_to_decide": "x"})
        elif name == "hestia_gate_escalation_poll":
            seq = self.script.get("poll_seq") or [self.script.get("poll", {})]
            i = min(self.script.setdefault("_i", 0), len(seq) - 1)
            self.script["_i"] = self.script["_i"] + 1
            payload = seq[i]
        else:
            payload = {}
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


def run_with(script: dict, wall: float = 6.0, poll: float = 0.2) -> tuple[str, str]:
    """Point the hook at a stub daemon and return escalate_self_write's verdict."""
    _Stub.script = dict(script)
    srv = HTTPServer(("127.0.0.1", 0), _Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    old_wall, old_poll = ptu.ESCALATION_WALL_S, ptu.ESCALATION_POLL_S
    ptu.ESCALATION_WALL_S, ptu.ESCALATION_POLL_S = wall, poll
    import os
    old_ep = os.environ.get("HESTIA_ENDPOINT")
    os.environ["HESTIA_ENDPOINT"] = f"http://127.0.0.1:{srv.server_port}/mcp"
    try:
        return ptu.escalate_self_write("pre_tool_use.py", "Edit")
    finally:
        ptu.ESCALATION_WALL_S, ptu.ESCALATION_POLL_S = old_wall, old_poll
        if old_ep is None:
            os.environ.pop("HESTIA_ENDPOINT", None)
        else:
            os.environ["HESTIA_ENDPOINT"] = old_ep
        srv.shutdown()


APPROVED = {"status": "approved", "permits_write": True, "decided_by": "dp",
            "decided_via": "local_cli"}

# --- the one path that permits -----------------------------------------------------------
v, d = run_with({"poll": APPROVED})
check("approved permits the write", v == "approved", f"{v}: {d}")
check("approved names who and by what channel", "dp" in d and "local_cli" in d, d)

# --- every other path refuses ------------------------------------------------------------
v, _ = run_with({"poll": {"status": "denied", "permits_write": False, "reason": "not now"}})
check("denied refuses", v == "denied", v)

v, _ = run_with({"poll": {"status": "expired", "permits_write": False}})
check("expired refuses", v == "expired", v)

v, _ = run_with({"poll": {"status": "pending", "permits_write": False}}, wall=1.2, poll=0.2)
check("no decision within the window refuses", v == "timeout", v)

# An old daemon that has never heard of these tools answers {} -- it must not be able to
# grant a write by failing to understand the question.
v, _ = run_with({"open": {}})
check("a daemon with no escalation_id refuses", v == "malformed", v)

# --- the branch a member would attack ----------------------------------------------------
# `status: approved` while the daemon's own boolean says no. Two places deciding what
# "approved" means is how they come to disagree, so the hook trusts permits_write.
v, _ = run_with({"poll": {"status": "approved", "permits_write": False}}, wall=1.2, poll=0.2)
check("status=approved without permits_write does NOT permit", v != "approved", v)

# permits_write true while the status says something else must also refuse.
v, _ = run_with({"poll": {"status": "pending", "permits_write": True}}, wall=1.2, poll=0.2)
check("permits_write without status=approved does NOT permit", v != "approved", v)

# --- unreachable daemon ------------------------------------------------------------------
import os as _os
_old = _os.environ.get("HESTIA_ENDPOINT")
_os.environ["HESTIA_ENDPOINT"] = "http://127.0.0.1:1/mcp"  # nothing listens on port 1
try:
    v, d = ptu.escalate_self_write("pre_tool_use.py", "Edit")
finally:
    if _old is None:
        _os.environ.pop("HESTIA_ENDPOINT", None)
    else:
        _os.environ["HESTIA_ENDPOINT"] = _old
check("an unreachable daemon refuses rather than bypassing", v == "unreachable", f"{v}: {d}")

# --- attribution --------------------------------------------------------------------------
# Never guess a member id. #108 was exactly this defect one layer over: an unset variable
# produced a well-formed act attributed to a real member.
_old_p = _os.environ.pop("HESTIA_MESH_PLUGIN", None)
try:
    check("unset identity is 'unattributed', never a guessed member",
          ptu._escalation_plugin_id() == "unattributed", ptu._escalation_plugin_id())
finally:
    if _old_p is not None:
        _os.environ["HESTIA_MESH_PLUGIN"] = _old_p

_os.environ["HESTIA_MESH_PLUGIN"] = "kimi-code"
check("a set identity is used as given", ptu._escalation_plugin_id() == "kimi-code")
if _old_p is None:
    _os.environ.pop("HESTIA_MESH_PLUGIN", None)
else:
    _os.environ["HESTIA_MESH_PLUGIN"] = _old_p

# --- envelope handling --------------------------------------------------------------------
check("_dig reads a bare object", ptu._dig({"status": "approved"}, "status") == "approved")
check("_dig reads content[0].text JSON",
      ptu._dig({"content": [{"text": json.dumps({"status": "denied"})}]}, "status") == "denied")
check("_dig on a missing key is None, not a crash", ptu._dig({"a": 1}, "status") is None)

print()
if FAILS:
    print(f"ESCALATION TESTS FAILED: {len(FAILS)} of {len(RAN)}: {', '.join(FAILS)}")
    sys.exit(1)
print(f"all gate escalation checks passed ({len(RAN)} assertions)")
