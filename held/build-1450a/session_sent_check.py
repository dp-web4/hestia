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
print("FAIL:", bad) if bad else print("PASS - scope_status is sent the session operating_law is sent")
sys.exit(1 if bad else 0)
