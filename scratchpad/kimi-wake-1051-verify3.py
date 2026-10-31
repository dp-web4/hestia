#!/usr/bin/env python3
"""wake-1051: full scope_refused event (677920) + review_done notice (677923) + request mode check."""
import json
import sys

sys.path.insert(0, "/home/dp/ai-workspace/hestia/tools")
from claude_daemon_client import call

# refusal event full
out = call("hestia_query_history", {"filter": {"limit": 500}})
entries = out.get("entries", [])
for e in entries:
    if e["chainPosition"] == 677920:
        print("=== 677920 scope_refused FULL ===")
        print(json.dumps(e, indent=1)[:3000])
    if e["chainPosition"] == 677923:
        print("=== 677923 member_notice review_done FULL ===")
        print(json.dumps(e, indent=1)[:2500])
    if e["chainPosition"] == 677842:
        ed = e.get("eventData", {})
        print("=== 677842 scope_requested mode/scope fields ===")
        for k in ("mode", "modes", "scope", "recursive", "window", "ttl", "duration"):
            if k in ed:
                print(f"{k}: {json.dumps(ed[k])}")
