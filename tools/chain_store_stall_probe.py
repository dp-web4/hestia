#!/usr/bin/env python3
"""Measure the daemon's chain-store stall from outside, without touching a petition.

Samples three calls every 100 ms: `hestia_query_history(limit=1)` (chain store, WRITE connection
mutex), `hestia_gate_pending_escalations` (state lock only, in-memory) and `GET /` (no lock).
A call that stalls on the first and not the others is waiting on the chain store — the same
mutex `gate_escalation_claimed` needs after the grant is already consumed. Measured 2026-09-01:
~7 s every ~21 s and ~0.7 s every ~2 s unloaded; the hook's claim budget is 1.5 s.

    python3 tools/chain_store_stall_probe.py [seconds]
"""
import json, sys, time, urllib.request
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from chain_walk import ChainWalker  # noqa: E402

def main(secs: float) -> None:
    w = ChainWalker()
    def pending():
        w._post({"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                 "params": {"name": "hestia_gate_pending_escalations", "arguments": {}}})
    def root():
        urllib.request.urlopen("http://127.0.0.1:7711/", timeout=30).read(64)
    t0 = time.monotonic(); rows = []
    while time.monotonic() < t0 + secs:
        r = [round(time.monotonic() - t0, 1)]
        for f in (lambda: w.window(limit=1), pending, root):
            t = time.monotonic()
            try: f()
            except Exception: pass
            r.append(round(time.monotonic() - t, 2))
        rows.append(r); time.sleep(0.1)
    print("offset chain_store state_lock root  (rows where any > 0.4 s)")
    for r in rows:
        if max(r[1:]) > 0.4: print(*r)
    print("n=%d max chain_store=%.2f state_lock=%.2f root=%.2f" % (
        len(rows), max(r[1] for r in rows), max(r[2] for r in rows), max(r[3] for r in rows)))

if __name__ == "__main__":
    main(float(sys.argv[1]) if len(sys.argv) > 1 else 60)
