#!/usr/bin/env python3
"""wake-1027t: find chain entries naming scope-cf665fbadb34 (request + codex decide)."""
import json, sys

sys.path.insert(0, "/home/dp/ai-workspace/hestia/tools")
from claude_daemon_client import call

out = call("hestia_query_history", {"filter": {"limit": 500}})
entries = out.get("entries", [])
print("window:", len(entries), "entries; head pos:",
      entries[-1].get("position") if entries else None)
for e in entries:
    blob = json.dumps(e)
    if "cf665fbadb34" in blob:
        print(json.dumps(e, indent=1)[:2500])
        print("---")
