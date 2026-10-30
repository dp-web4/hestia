#!/usr/bin/env python3
"""Wake-1034: find chain entries for scope-a57a2bf4d368 (request + decision)."""
import json, sys

sys.path.insert(0, "/home/dp/ai-workspace/hestia/tools")
from claude_daemon_client import call

out = call("hestia_query_history", {"filter": {"limit": 500}})
entries = out.get("entries", [])
print(f"window: {len(entries)} entries; head pos {entries[-1].get('position') if entries else '?'}")
hits = [e for e in entries if "a57a2bf4d368" in json.dumps(e)]
for e in hits:
    print(json.dumps(e, indent=1)[:3000])
    print("---")
if not hits:
    print("NO HITS in tail 500")
