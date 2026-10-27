#!/usr/bin/env python3
"""Wake 1027g: read cbp-being's scope request scope-2342908da164 (notice 33616 asks
kimi-code to peer-decide it). hestia_scope_status is the member-side read (read-only,
unwitnessed). Memory-only map: an evicted request reads UNKNOWN, not refused.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
from claude_daemon_client import call  # noqa: E402

TARGET = "scope-2342908da164"

st = call("hestia_scope_status", {"plugin_id": "cbp-being"})
reqs = {r["request_id"]: r for r in st.get("requests", [])}
print(f"requests held for cbp-being: {len(reqs)}")
r = reqs.get(TARGET)
if r is None:
    print(f"\n{TARGET}: NOT IN LIVE MAP -- unknown, not refused")
    # show what IS held, so a wrong id is distinguishable from an evicted one
    for rid, rr in sorted(reqs.items(), key=lambda kv: kv[1].get("requested_at") or 0):
        print(f"  held: {rid} status={rr.get('status')} path={rr.get('path')}")
else:
    print(f"\n{TARGET}:")
    for k in ("status", "path", "reason", "origin", "act", "grant_path", "recursive",
              "requested_at", "expires_at", "secs_remaining", "decided_by", "decided_at",
              "decision_reason", "once", "spent_at"):
        v = r.get(k)
        if v is not None:
            print(f"  {k}: {str(v)[:600]}")
