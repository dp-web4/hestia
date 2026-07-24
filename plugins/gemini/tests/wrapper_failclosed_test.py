#!/usr/bin/env python3
"""Isolate the top-level deny-on-exception wrapper in ../hooks/before_tool.py via fault injection.

Why a separate test: the repro's HOLE-3 case passes for TWO reasons now (tool_name normalisation
AND the wrapper), so it no longer proves the wrapper on its own. Here we inject a fault directly
into _gate() and assert main() converts it to exit 2 -- while a genuine verdict passes through
untouched.

This matters because gemini-cli reads **exit 1 as ALLOW + warning** (LIVE-VERIFIED on 0.52.0,
shared-context/forum/cbp-to-nomad-gemini-hook-contract-LIVE-VERIFIED-2026-07-22.md), and an
uncaught Python exception exits 1. Without the wrapper, a crashing fail-closed gate silently OPENS.

Usage: ./wrapper_failclosed_test.py [path/to/before_tool.py]
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
GATE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "..", "hooks", "before_tool.py")

spec = importlib.util.spec_from_file_location("before_tool", GATE)
bt = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bt)


def _raise(exc):
    def f():
        raise exc
    return f


CASES = [
    ("RuntimeError deep in the gate", _raise(RuntimeError("boom")), 2),
    ("KeyboardInterrupt mid-gate", _raise(KeyboardInterrupt()), 2),
    ("MemoryError mid-gate", _raise(MemoryError()), 2),
    ("SystemExit(2): the gate's own DENY passes through", lambda: sys.exit(2), 2),
    ("SystemExit(0): the gate's own ALLOW passes through", lambda: sys.exit(0), 0),
]

failures = 0
for label, fault, want in CASES:
    bt._gate = fault
    try:
        bt.main()
        got = "returned without exiting"
    except SystemExit as e:
        got = e.code
    ok = got == want
    failures += not ok
    print(f"{'PASS' if ok else 'FAIL'}  exit={got} want={want}  {label}")

print(f"\nfailures={failures}")
sys.exit(1 if failures else 0)
