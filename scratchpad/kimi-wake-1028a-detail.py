#!/usr/bin/env python3
"""wake-1028a: full detail on scope-264b153c6389 open/decision/refusal + the three notice sends."""
import json
import sys

sys.path.insert(0, "/home/dp/ai-workspace/hestia/tools")
from claude_daemon_client import call

out = call("hestia_query_history", {"filter": {"limit": 500}})
entries = out.get("entries", [])
NEEDLE = "264b153c6389"
for e in entries:
    if NEEDLE in json.dumps(e) and e.get("eventType") in (
            "scope_requested", "policy_decision", "scope_refused", "scope_granted"):
        print("=" * 70)
        print("pos", e.get("chainPosition"), e.get("timestamp"), e.get("eventType"),
              "hash", e.get("hash", e.get("entryHash", "?"))[:16])
        print(json.dumps(e.get("eventData", {}), indent=1))
