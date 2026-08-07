#!/usr/bin/env python3
"""Stage-2 escalation: the verdict path and the BUDGET, against a stub daemon.

dp, 2026-07-29: "add escalation since it isn't a tested mechanism yet."

The first cut of this suite tested every verdict and still shipped a mechanism that could not
work: it waited 135s in a hook the harness kills at 5s, and a killed hook yields neither exit 2
nor a JSON deny -- so Claude Code runs the tool ANYWAY. The verdicts were all correct and the
thing failed OPEN. kimi-code caught it in review (PR #114).

So this suite now tests two things, and the second is the one that was missing: what the hook
DECIDES, and how long it TAKES to decide it. A verdict that arrives after the harness has given
up is not a verdict.

Runs under bare `python3` at module scope: CI executes these files directly (tools/ci_discovery.py),
and a pytest-style file would import, define its functions, exit 0 and report green no matter what
it asserts -- exactly what tools/ci_selfexec_test.py refuses.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HOOK = Path(__file__).resolve().parent / "pre_tool_use.py"
_spec = importlib.util.spec_from_file_location("ptu_under_test", HOOK)
ptu = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(ptu)

# The harness timeout this hook ships with, in plugin.json AND in the live settings.json. Every
# path through the hook must finish inside it with room for the ordinary policy call too.
HARNESS_TIMEOUT_S = 5.0
BUDGET_S = 3.0

FAILS: list[str] = []
RAN: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    RAN.append(name)
    print(f"  {'ok  ' if cond else 'FAIL'}  {name}" + (f"  -- {detail}" if not cond and detail else ""))
    if not cond:
        FAILS.append(name)


class _Stub(BaseHTTPRequestHandler):
    payload: dict = {}
    stall_s: float = 0.0

    def log_message(self, *_a):
        pass

    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0)
        try:
            req = json.loads(body or b"{}")
        except ValueError:
            req = {}
        if self.stall_s:
            time.sleep(self.stall_s)  # accepts the connection, never answers in time
        out = json.dumps({
            "jsonrpc": "2.0", "id": req.get("id", 1),
            "result": {"content": [{"type": "text", "text": json.dumps(self.payload)}]},
        }).encode()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("mcp-session-id", "stub")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)
        except Exception:  # client already gave up
            pass


def run_with(payload: dict, stall_s: float = 0.0) -> tuple[str, str, float]:
    _Stub.payload, _Stub.stall_s = dict(payload), stall_s
    srv = HTTPServer(("127.0.0.1", 0), _Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    old = os.environ.get("HESTIA_ENDPOINT")
    os.environ["HESTIA_ENDPOINT"] = f"http://127.0.0.1:{srv.server_port}/mcp"
    t0 = time.monotonic()
    try:
        v, d = ptu.request_self_write("pre_tool_use.py", "Edit")
    finally:
        elapsed = time.monotonic() - t0
        if old is None:
            os.environ.pop("HESTIA_ENDPOINT", None)
        else:
            os.environ["HESTIA_ENDPOINT"] = old
        threading.Thread(target=srv.shutdown, daemon=True).start()
    return v, d, elapsed


APPROVED = {"claimed": True, "permits_write": True, "decided_by": "dp", "decided_via": "local_cli"}
REFUSED = {"claimed": False, "permits_write": False, "escalation_id": "abc123",
           "how_to_decide": "hestia gate approve abc123", "retry_within_secs": 720}

# --- the one path that permits ------------------------------------------------------------
v, d, _ = run_with(APPROVED)
check("a claimed approval permits the write", v == "approved", f"{v}: {d}")
check("it names who approved and by what channel", "dp" in d and "local_cli" in d, d)

# --- the ordinary path: refuse now, decide later --------------------------------------------
v, d, _ = run_with(REFUSED)
check("no approval yet REFUSES", v == "escalated", f"{v}: {d}")
check("the refusal carries the escalation id", "abc123" in d, d)

# --- an un-upgraded daemon ------------------------------------------------------------------
# It answers {} to a tool it has never heard of. It must not permit a write by failing to
# understand the question -- and it must not imply paperwork exists that does not.
v, d, _ = run_with({})
check("a daemon with no escalation channel refuses", v == "no-channel", f"{v}: {d}")
check("and says NO escalation was opened", "NO escalation" in d, d)

# --- the branches a member would attack ------------------------------------------------------
v, _, _ = run_with({"claimed": True, "permits_write": False, "escalation_id": "x"})
check("claimed without permits_write does NOT permit", v != "approved", v)
v, _, _ = run_with({"claimed": False, "permits_write": True, "escalation_id": "x"})
check("permits_write without claimed does NOT permit", v != "approved", v)

# --- unreachable -----------------------------------------------------------------------------
old = os.environ.get("HESTIA_ENDPOINT")
os.environ["HESTIA_ENDPOINT"] = "http://127.0.0.1:1/mcp"
t0 = time.monotonic()
try:
    v, d = ptu.request_self_write("pre_tool_use.py", "Edit")
finally:
    unreachable_elapsed = time.monotonic() - t0
    if old is None:
        os.environ.pop("HESTIA_ENDPOINT", None)
    else:
        os.environ["HESTIA_ENDPOINT"] = old
check("an unreachable daemon refuses rather than bypassing", v == "unreachable", f"{v}: {d}")

# --- THE BUDGET: the defect this suite previously could not see -------------------------------
# A verdict that arrives after the harness has SIGKILLed the hook is not a verdict -- the tool
# runs anyway. So every path has to finish inside the shipped timeout, and the slow paths are
# the ones that matter.
_, _, t_ok = run_with(APPROVED)
_, _, t_refuse = run_with(REFUSED)
_, _, t_stall = run_with(REFUSED, stall_s=10.0)  # accepts, then never answers in time

check(f"approved path fits the budget ({t_ok:.2f}s < {BUDGET_S}s)", t_ok < BUDGET_S, f"{t_ok:.2f}s")
check(f"refusal path fits the budget ({t_refuse:.2f}s < {BUDGET_S}s)", t_refuse < BUDGET_S, f"{t_refuse:.2f}s")
check(f"a STALLED daemon still fits the budget ({t_stall:.2f}s < {BUDGET_S}s)",
      t_stall < BUDGET_S, f"{t_stall:.2f}s -- a hook that outruns its harness timeout is KILLED, "
                          f"and a killed hook does not block the tool")
check(f"unreachable fits the budget ({unreachable_elapsed:.2f}s < {BUDGET_S}s)",
      unreachable_elapsed < BUDGET_S, f"{unreachable_elapsed:.2f}s")
check("the whole hook budget stays under the shipped harness timeout",
      BUDGET_S < HARNESS_TIMEOUT_S, f"{BUDGET_S} vs {HARNESS_TIMEOUT_S}")

# --- no in-hook wait may be reintroduced -------------------------------------------------------
# A guard on the defect itself rather than only on its symptom: if someone adds a wait loop back,
# this fails even if every verdict above still passes.
src = HOOK.read_text()
check("the hook does not sleep while waiting for a human",
      "ESCALATION_WALL_S" not in src and "while time.monotonic() < wall" not in src,
      "an in-hook wait for a human fails OPEN under the harness timeout")

# --- attribution --------------------------------------------------------------------------------
_old_p = os.environ.pop("HESTIA_MESH_PLUGIN", None)
_old_q = os.environ.pop("HESTIA_PLUGIN_ID", None)
try:
    check("unset identity falls back to this file's own PLUGIN_ID (#244), never 'unattributed'",
          ptu._escalation_plugin_id() == ptu.PLUGIN_ID, ptu._escalation_plugin_id())
finally:
    if _old_p is not None:
        os.environ["HESTIA_MESH_PLUGIN"] = _old_p
    if _old_q is not None:
        os.environ["HESTIA_PLUGIN_ID"] = _old_q
os.environ["HESTIA_MESH_PLUGIN"] = "kimi-code"
check("a set identity is used as given", ptu._escalation_plugin_id() == "kimi-code")
if _old_p is None:
    os.environ.pop("HESTIA_MESH_PLUGIN", None)
else:
    os.environ["HESTIA_MESH_PLUGIN"] = _old_p

# --- the claim threads a session when one connects (asker_basis: "session") ------------
# kimi-code, 2026-08-07, claiming the 1530 remainder: the claim path used to send a bare
# initialize with no hestia_connect, so every auto-opened escalation landed
# `asker_basis: "asserted"` and the invitation RECORDED peers but woke nobody. The hook
# now connects first and threads `session_id` — the daemon refuses a claim whose
# plugin_id disagrees with the session's, so the two MUST be one value, asserted here.
class _SessionStub(BaseHTTPRequestHandler):
    seen: list = []

    def log_message(self, *_a):
        pass

    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length", 0)) or 0)
        try:
            req = json.loads(body or b"{}")
        except ValueError:
            req = {}
        _SessionStub.seen.append(req)
        params = req.get("params") or {}
        if params.get("name") == "hestia_connect":
            payload = {"sessionId": "sess-test-1529"}
        else:
            payload = dict(REFUSED)
        out = json.dumps({
            "jsonrpc": "2.0", "id": req.get("id", 1),
            "result": {"content": [{"type": "text", "text": json.dumps(payload)}]},
        }).encode()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("mcp-session-id", "stub")
            self.send_header("Content-Length", str(len(out)))
            self.end_headers()
            self.wfile.write(out)
        except Exception:
            pass


_SessionStub.seen = []
_srv = HTTPServer(("127.0.0.1", 0), _SessionStub)
threading.Thread(target=_srv.serve_forever, daemon=True).start()
_old_ep2 = os.environ.pop("HESTIA_ENDPOINT", None)
os.environ["HESTIA_ENDPOINT"] = f"http://127.0.0.1:{_srv.server_port}/mcp"
try:
    _v, _ = ptu.request_self_write("pre_tool_use.py", "Edit")
    _calls = [r for r in _SessionStub.seen if (r.get("params") or {}).get("name")]
    _connect = [r for r in _calls if r["params"]["name"] == "hestia_connect"]
    _claim = [r for r in _calls if r["params"]["name"] == "hestia_gate_escalation_claim"]
    check("a session was connected before the claim", len(_connect) == 1,
          f"{len(_connect)} connects in {len(_calls)} tool calls")
    check("the claim went out", len(_claim) == 1)
    if _claim:
        check("the claim threads the session it connected",
              _claim[0]["params"]["arguments"].get("session_id") == "sess-test-1529",
              json.dumps(_claim[0]["params"]["arguments"])[:200])
    if _connect and _claim:
        check("connect and claim assert ONE plugin_id (the asker-mismatch binding)",
              _connect[0]["params"]["arguments"].get("plugin_id")
              == _claim[0]["params"]["arguments"].get("plugin_id"),
              f"{_connect[0]['params']['arguments'].get('plugin_id')} vs "
              f"{_claim[0]['params']['arguments'].get('plugin_id')}")
    check("the verdict path is unchanged by threading", _v == "escalated", _v)
finally:
    threading.Thread(target=_srv.shutdown, daemon=True).start()
    if _old_ep2 is None:
        os.environ.pop("HESTIA_ENDPOINT", None)
    else:
        os.environ["HESTIA_ENDPOINT"] = _old_ep2

# The existing _Stub answers every call with the same payload — so `hestia_connect` above
# got APPROVED/REFUSED-shaped answers with no sessionId, and the claim still proceeded
# (all verdict checks up top). That IS the degrade test: no session -> asserted basis,
# never a dark channel.

# --- envelope handling ----------------------------------------------------------------------------
check("_dig reads a bare object", ptu._dig({"claimed": True}, "claimed") is True)
check("_dig reaches into result.result.content[0].text (the real envelope)",
      ptu._dig({"result": {"content": [{"text": json.dumps({"claimed": True})}]}}, "claimed") is True)
check("_dig on a missing key is None, not a crash", ptu._dig({"a": 1}, "claimed") is None)

# --- the record names the ACT, not the rule that fired (5.2, notice 1474 §2/§3) --------------------
# The deny message and the escalation text printed the MARKER (the pattern that matched)
# where they promised the resource the call would reach. A human rules on those strings;
# the verdict was never the defective part. Red-first: the resource=/key= kwargs do not
# exist yet, and the old message prints the marker as the destination.
import contextlib
import io

_old_ep = os.environ.pop("HESTIA_ENDPOINT", None)
os.environ["HESTIA_ENDPOINT"] = "http://127.0.0.1:1/mcp"  # dead: witness fails fast, refusal stands
try:
    # A PATH-key match: the message must name the file the call would reach, with the
    # marker as the REASON it matched.
    buf = io.StringIO()
    try:
        with contextlib.redirect_stderr(buf):
            rc = ptu.deny_self_access("plugins/claude-code/hooks", "Write",
                                      resource="/x/hooks/pre_tool_use.py", key="file_path")
        msg = buf.getvalue()
        check("deny still returns 2", rc == 2, f"rc={rc}")
        check("the deny names the resource the call would reach",
              "/x/hooks/pre_tool_use.py" in msg, msg[:160])
        check("the marker is reported as the REASON, not the place",
              "plugins/claude-code/hooks" in msg and "marker" in msg, msg[:160])
    except TypeError as e:
        check("deny names the resource, not the marker", False,
              f"deny_self_access has no resource/key yet — the marker IS the reported "
              f"destination today ({e})")

    # A TEXT-key match with an ordinary destination (the FP8 shape): the message must
    # name the destination AND say the match is payload content, not the destination.
    buf = io.StringIO()
    try:
        with contextlib.redirect_stderr(buf):
            ptu.deny_self_access("plugins/claude-code/hooks", "Edit",
                                 resource="see hooks/pre_tool_use.py for the mechanism",
                                 key="new_string", dest="/tmp/forum-post.md")
        msg = buf.getvalue()
        check("a payload match names the call's destination", "/tmp/forum-post.md" in msg,
              msg[:160])
        check("a payload match says it is payload, not a destination",
              "payload" in msg, msg[:160])
    except TypeError as e:
        check("a payload match names the destination and says so", False, str(e))

    # The escalation text is the other human-facing string on this path: same property.
    _Stub.payload = dict(REFUSED)
    _Stub.stall_s = 0.0  # the budget probe above left 10s behind; a stall reads as "unreachable"
    srv = HTTPServer(("127.0.0.1", 0), _Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    os.environ["HESTIA_ENDPOINT"] = f"http://127.0.0.1:{srv.server_port}/mcp"
    buf = io.StringIO()
    try:
        with contextlib.redirect_stderr(buf):
            ptu.request_self_write("plugins/claude-code/hooks", "Write",
                                   resource="/x/hooks/pre_tool_use.py", key="file_path")
        msg = buf.getvalue()
        check("the escalation record names the resource, not the rule",
              "/x/hooks/pre_tool_use.py" in msg, msg[:200])
    except TypeError as e:
        check("the escalation record names the resource, not the rule", False, str(e))
    finally:
        threading.Thread(target=srv.shutdown, daemon=True).start()
finally:
    if _old_ep is None:
        os.environ.pop("HESTIA_ENDPOINT", None)
    else:
        os.environ["HESTIA_ENDPOINT"] = _old_ep

print()
if FAILS:
    print(f"ESCALATION TESTS FAILED: {len(FAILS)} of {len(RAN)}: {', '.join(FAILS)}")
    sys.exit(1)
print(f"all gate escalation checks passed ({len(RAN)} assertions)")
