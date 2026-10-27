#!/usr/bin/env python3
"""Read the rulings on my three scope petitions named by dispositions 33529-33531.

Dispositions say 'the petition you filed has been RULED'; the ruling lives at the
hestia://scope/<request_id> pointer. hestia_scope_status is the member-side read
(read-only, unwitnessed per handler.rs:23915). The map is memory-only, so a request
evicted by a daemon restart reads UNKNOWN, not refused -- reported, not asserted.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
from claude_daemon_client import call  # noqa: E402

WANT = {
    "scope-e1c67df2616a": 33529,
    "scope-e084deaa6fe6": 33530,
    "scope-e4bc3f6f016b": 33531,
}

st = call("hestia_scope_status", {"plugin_id": "kimi-code"})
reqs = {r["request_id"]: r for r in st.get("requests", [])}
print(f"requests held for kimi-code: {len(reqs)}")
for rid, notice in WANT.items():
    r = reqs.get(rid)
    if r is None:
        print(f"\n{rid} (notice {notice}): NOT IN LIVE MAP -- unknown, not refused")
        continue
    print(f"\n{rid} (notice {notice}):")
    for k in ("status", "path", "reason", "decided_by", "decided_at",
              "decision_reason", "origin", "act", "grant_path", "recursive"):
        v = r.get(k)
        if v is not None:
            s = str(v)
            print(f"  {k}: {s[:400]}")
