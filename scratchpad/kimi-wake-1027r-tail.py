#!/usr/bin/env python3
"""wake-1027r: tail-pull witness chain, client-side filter for scope-ce0d92a9fd06."""
import json
import sys

sys.path.insert(0, "/home/dp/ai-workspace/hestia/tools")
from claude_daemon_client import call

out = call("hestia_query_history", {"filter": {"limit": 500}})
entries = out.get("entries") or []
print(f"entries: {len(entries)} hasMore={out.get('hasMore')}", file=sys.stderr)
for e in entries:
    blob = json.dumps(e)
    if "ce0d92a9fd06" in blob:
        print(json.dumps(e, indent=1)[:3000])
        print("---")
