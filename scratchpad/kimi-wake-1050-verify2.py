#!/usr/bin/env python3
"""wake-1050: full notice entry metadata + locate scope open/decision events."""
import json
import sys

sys.path.insert(0, "/home/dp/ai-workspace/hestia/tools")
from claude_daemon_client import call

h = "f4fbafcb4346cd1d0d9a2a9ee3b3e66f5f10d6cbaea838e3586759494c83e609"
out = call("hestia_query_history", {"filter": {"hash": h}})
entry = out.get("entry") or out
meta = {k: v for k, v in entry.items() if k != "eventData"}
print("=== notice meta ===")
print(json.dumps(meta, indent=1))
ed = entry.get("eventData", {})
print("=== eventData keys ===", list(ed.keys()))
for k, v in ed.items():
    if k != "act":
        print(f"{k}: {json.dumps(v)[:300]}")
