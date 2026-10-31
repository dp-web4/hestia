#!/usr/bin/env python3
"""wake-1050: verify notice 34997 chain_hash and full scope record for scope-a2d6f256b31f."""
import json
import sys

sys.path.insert(0, "/home/dp/ai-workspace/hestia/tools")
from claude_daemon_client import call

h = "f4fbafcb4346cd1d0d9a2a9ee3b3e66f5f10d6cbaea838e3586759494c83e609"
out = call("hestia_query_history", {"filter": {"hash": h}})
entry = out.get("entry") or out
print("=== notice event ===")
print(json.dumps(entry, indent=1)[:2500])
