#!/usr/bin/env python3
"""wake-1028a: scan chain tail for anything mentioning scope-264b153c6389 (or the bare hash)."""
import json
import sys

sys.path.insert(0, "/home/dp/ai-workspace/hestia/tools")
from claude_daemon_client import call

NEEDLE = "264b153c6389"

out = call("hestia_query_history", {"filter": {"limit": 500}})
entries = out.get("entries", [])
print("tail entries:", len(entries))
hits = []
for e in entries:
    blob = json.dumps(e)
    if NEEDLE in blob:
        hits.append(e)
for e in hits:
    print("=" * 60)
    print("pos", e.get("chainPosition"), e.get("timestamp"), e.get("eventType"))
    print(json.dumps(e.get("eventData", {}), indent=1)[:2500])
if not hits:
    print("NO HITS in tail", len(entries))
