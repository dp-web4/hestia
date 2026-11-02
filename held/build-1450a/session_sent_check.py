#!/usr/bin/env python3
"""hestia #1450 phase 0 step A: the gate's policy-snapshot fetch sends hestia_scope_status the session hestia_connect
returned -- the same one it sends hestia_operating_law. Drives the real fetch_policy_snapshot against a recording fake
daemon. argv: <dir with mechanism_rev.py | ""> ("" = this worktree's own mechanism, the control). Not test-shaped: on
the base mechanism it fails, by design; at apply time it moves to tools/ as a test."""
import importlib.util
import os
import pathlib
import sys

wt = pathlib.Path(__file__).resolve().parents[2]
shared = wt / "plugins" / "_shared"
sys.path.insert(0, str(shared))
ov = sys.argv[1] if len(sys.argv) > 1 else ""
if ov:
    spec = importlib.util.spec_from_file_location("hestia_gate_mechanism", os.path.join(ov, "mechanism_rev.py"))
    mod = importlib.util.module_from_spec(spec)
    sys.modules["hestia_gate_mechanism"] = mod
    spec.loader.exec_module(mod)
import hestia_gate_mechanism as m  # noqa: E402
import hestia_gate_mechanism_test as mt  # noqa: E402

mt.m = m   # the test module's helpers drive whichever mechanism is loaded


class Recording(mt.FakeClient):
    def __init__(self):
        super().__init__(connect={"sessionId": "sess-7f3a"})
        self.calls = []

    def call_tool(self, name, args):
        self.calls.append((name, dict(args)))
        return super().call_tool(name, args)


ws = mt._fake_workspace()
old = os.environ.get("HESTIA_WORKSPACE")
os.environ["HESTIA_WORKSPACE"] = ws
try:
    fake = Recording()
    fake.extra = mt._std_stub(ws).extra
    snap = mt._fetch_with(fake)
finally:
    if old is None:
        os.environ.pop("HESTIA_WORKSPACE", None)
    else:
        os.environ["HESTIA_WORKSPACE"] = old

sent = {n: a for n, a in fake.calls}
bad = []
if not isinstance(snap, dict):
    bad.append(f"no snapshot: {snap!r}")
if sent.get("hestia_operating_law", {}).get("session_id") != "sess-7f3a":
    bad.append(f"operating_law did not get the session: {sent.get('hestia_operating_law')}")
if sent.get("hestia_scope_status", {}).get("session_id") != "sess-7f3a":
    bad.append(f"scope_status did not get the session: {sent.get('hestia_scope_status')}")
if sent.get("hestia_scope_status", {}).get("plugin_id") != "kimi-code":
    bad.append(f"scope_status lost its plugin_id: {sent.get('hestia_scope_status')}")

# CONTROLS (the independent source check on #1469, 2026-11-02): sending a session proves nothing about
# whether the daemon RESOLVED it. Step B serves an unresolvable or expired session as an unbound read
# (caller_bound: false, counted); a session resolving to ANOTHER member is refused with an error envelope.
# The gate must treat neither as authority: an unbound answer yields exactly the grants a bound one does
# (caller_bound widens nothing), and a refusal yields NO scope grants (narrows, never widens). Both still
# produce a snapshot, so a session that lapsed between connect and read is never a fleet-wide outage.
def _snap_for(scope_status):
    os.environ["HESTIA_WORKSPACE"] = ws
    try:
        f = mt._std_stub(ws)
        f.connect = {"sessionId": "sess-stale"}
        f.extra["hestia_scope_status"] = scope_status
        return mt._fetch_with(f)
    finally:
        if old is None:
            os.environ.pop("HESTIA_WORKSPACE", None)
        else:
            os.environ["HESTIA_WORKSPACE"] = old


grant_dir = os.path.join(ws, "hestia", "granted")
base = dict(mt._std_stub(ws).extra["hestia_scope_status"],
            live_grants=[{"path": grant_dir, "recursive": True}])
bound = _snap_for(dict(base, caller_bound=True, unbound_reads_since_start=0))
unbound = _snap_for(dict(base, caller_bound=False, unbound_reads_since_start=1))
refused = _snap_for({"_hestia_error": {"code": "hestia.scope_status_session_mismatch",
                                       "message": "the session you sent belongs to 'codex', not 'kimi-code'"}})
for label, s in (("bound", bound), ("unbound", unbound), ("refused", refused)):
    if not isinstance(s, dict):
        bad.append(f"{label}: no snapshot ({s!r}): a stale session must not become an outage")
if isinstance(bound, dict) and isinstance(unbound, dict):
    if (bound.get("scope_grants"), bound.get("in_scope")) != (unbound.get("scope_grants"), unbound.get("in_scope")):
        bad.append(f"caller_bound changed the grants: bound {bound.get('in_scope')} vs unbound {unbound.get('in_scope')}")
    if grant_dir not in (bound.get("scope_grants") or []):
        bad.append(f"control did not exercise a grant: {bound.get('scope_grants')}")
if isinstance(refused, dict) and refused.get("scope_grants"):
    bad.append(f"a refused scope read still carried grants: {refused.get('scope_grants')}")
print("FAIL:", bad) if bad else print("PASS - scope_status is sent the session operating_law is sent; "
                                      "an unbound answer widens nothing; a refusal carries no grants")
sys.exit(1 if bad else 0)
