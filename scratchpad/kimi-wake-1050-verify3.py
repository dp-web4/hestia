#!/usr/bin/env python3
"""wake-1050: find terminal decision event for scope-a2d6f256b31f in recent window."""
import json
import sys

sys.path.insert(0, "/home/dp/ai-workspace/hestia/tools")
from claude_daemon_client import call

out = call("hestia_query_history", {"filter": {"limit": 500}})
entries = out.get("entries", [])
print(f"window: {len(entries)} entries, {entries[0]['chainPosition']}..{entries[-1]['chainPosition']}")
for e in entries:
    ed = e.get("eventData", {})
    rid = ed.get("request_id", "")
    if "a2d6f256b31f" in str(rid) or "a2d6f256b31f" in json.dumps(ed)[:2000]:
        slim = {k: v for k, v in ed.items() if k in (
            "request_id", "decision", "granted", "decided_by", "decision_reason",
            "expires_at", "peer", "plugin_id", "path", "scope", "mode")}
        print(f"--- pos {e['chainPosition']} {e['eventType']} {e['timestamp']}")
        print(json.dumps(slim, indent=1)[:1500])
