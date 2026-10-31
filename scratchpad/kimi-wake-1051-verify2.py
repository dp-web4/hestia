#!/usr/bin/env python3
"""wake-1051: find all chain events for scope-2eaee63d4f54 in recent window."""
import json
import sys

sys.path.insert(0, "/home/dp/ai-workspace/hestia/tools")
from claude_daemon_client import call

out = call("hestia_query_history", {"filter": {"limit": 500}})
entries = out.get("entries", [])
print(f"window: {len(entries)} entries, {entries[0]['chainPosition']}..{entries[-1]['chainPosition']}")
found = 0
for e in entries:
    ed = e.get("eventData", {})
    blob = json.dumps(ed)
    if "2eaee63d4f54" in blob:
        found += 1
        slim = {k: v for k, v in ed.items() if k in (
            "request_id", "decision", "granted", "decided_by", "decision_reason",
            "expires_at", "peer", "plugin_id", "path", "scope", "mode", "reason",
            "notice_id", "to_plugin", "from_plugin", "kind")}
        print(f"--- pos {e['chainPosition']} {e['eventType']} {e['timestamp']}")
        print(json.dumps(slim, indent=1)[:2000])
print(f"found={found}")
