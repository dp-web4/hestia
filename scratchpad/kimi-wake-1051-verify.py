#!/usr/bin/env python3
"""wake-1051: verify notice 35022 chain_hash and locate the scope_requested event for scope-2eaee63d4f54."""
import json
import sys

sys.path.insert(0, "/home/dp/ai-workspace/hestia/tools")
from claude_daemon_client import call

h = "00b3541ddc15479c961359a5c0cc4687473b986d2a0b53e92cb6ee7ad38e4ff0"
out = call("hestia_query_history", {"filter": {"hash": h}})
entry = out.get("entry") or out
print("=== notice event (35022 chain_hash) ===")
print(json.dumps(entry, indent=1)[:4000])
