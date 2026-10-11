#!/usr/bin/env python3
"""Fault-inject the gemini shim's `main` and assert every failure becomes exit 2.

gemini-cli reads **exit 1 as ALLOW + warning** (LIVE-VERIFIED on 0.52.0,
shared-context/forum/cbp-to-nomad-gemini-hook-contract-LIVE-VERIFIED-2026-07-22.md), and an
uncaught Python exception exits 1. So a shim that lets an exception escape silently OPENS.

Since one-gate stage C the shim is the certified template: `main` reads the event, loads the
common gate, translates, asks `decide`, and renders through `emit`; every step's BaseException is
caught and turned into `_emergency_block` (exit 2, stderr). This injects a fault at each step and
asserts that, while a genuine verdict passes through untouched: a policy deny returns 0 with the
decision on stdout (the runner's policy channel; what that means to the runner is asserted in
channel_contract_test.py, against the real parser).

Usage: ./wrapper_failclosed_test.py [path/to/before_tool.py]
Staging seam (unset in the repo and in CI): HESTIA_CONTRACT_SHIMS ({"gemini": path}).
"""
import importlib.util
import io
import json
import os
import sys
import tempfile
from types import SimpleNamespace

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = (sys.argv[1] if len(sys.argv) > 1
        else json.loads(os.environ.get("HESTIA_CONTRACT_SHIMS") or "{}").get("gemini")
        or os.path.join(HERE, "..", "hooks", "before_tool.py"))

with tempfile.TemporaryDirectory() as _home:
    os.environ["HESTIA_HOME"] = _home       # import never fails; the projection error is reset below
    spec = importlib.util.spec_from_file_location("before_tool_under_test", GATE)
    bt = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(bt)

EVENT = {"hook_event_name": "BeforeTool", "tool_name": "read_file",
         "tool_input": {"absolute_path": "/x"}, "cwd": "/"}


def fake_gate(decide):
    def make_event(**kw):
        return SimpleNamespace(**kw)
    return SimpleNamespace(
        GateEvent=make_event, GateProfile=lambda **kw: SimpleNamespace(**kw),
        harness_bound=lambda *a, **k: None, decide=decide,
        render=lambda d: "hestia: deny [x] - y")


def _raise(exc):
    def f(*_a, **_k):
        raise exc
    return f


def run(gate=None, load=None, read=None):
    bt._PROJECTION_ERROR = None
    bt.read_harness_event = read or (lambda: dict(EVENT))
    bt._load_gate = load or (lambda: gate)
    real_out, real_err = sys.stdout, sys.stderr
    sys.stderr = io.StringIO()
    try:
        return bt.main(), sys.stderr.getvalue()
    except SystemExit as e:              # the template never exits inside main; a shim that does
        return f"SystemExit({e.code})", sys.stderr.getvalue()
    except BaseException as e:           # noqa: BLE001 — an escape IS the defect being tested
        return f"escaped {type(e).__name__}", sys.stderr.getvalue()
    finally:
        sys.stdout, sys.stderr = real_out, real_err


POLICY_DENY = SimpleNamespace(blocks=True, verdict_available=True, anomaly=False)
CASES = [
    ("RuntimeError inside decide", dict(gate=fake_gate(_raise(RuntimeError("boom")))), 2),
    ("KeyboardInterrupt inside decide", dict(gate=fake_gate(_raise(KeyboardInterrupt()))), 2),
    ("MemoryError inside decide", dict(gate=fake_gate(_raise(MemoryError()))), 2),
    ("SystemExit(0) inside decide is not an allow", dict(gate=fake_gate(_raise(SystemExit(0)))), 2),
    ("the gate cannot be loaded", dict(load=_raise(ImportError("gone"))), 2),
    ("the event cannot be read", dict(read=_raise(ValueError("not json"))), 2),
]

failures = 0
for label, kw, want in CASES:
    got, err = run(**kw)
    ok = got == want and "Traceback" not in err
    failures += not ok
    print(f"{'PASS' if ok else 'FAIL'}  exit={got} want={want}  {label}")

# A genuine POLICY verdict passes through untouched: exit 0, the decision object on fd 1.
r, w = os.pipe()
saved = os.dup(1)
os.dup2(w, 1)
try:
    got, _err = run(gate=fake_gate(lambda *a, **k: POLICY_DENY))
finally:
    os.dup2(saved, 1)
    os.close(w)
out = os.read(r, 65536).decode()
os.close(r)
ok = got == 0 and json.loads(out or "{}").get("decision") == "deny"
failures += not ok
print(f"{'PASS' if ok else 'FAIL'}  exit={got} stdout={out!r}  a policy deny takes the clean channel")

print(f"\nfailures={failures}")
sys.exit(1 if failures else 0)
