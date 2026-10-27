#!/usr/bin/env python3
"""wake-1027s: read escalation 84de9dcafa0039a0 (notice 33913 from cbp-being)."""
import json, sys
sys.path.insert(0, "/home/dp/ai-workspace/hestia/tools")
from claude_daemon_client import call

esc = "84de9dcafa0039a0"
try:
    out = call("hestia_gate_escalation_lookup", {"escalation_id": esc})
    print("== escalation_lookup")
    print(json.dumps(out, indent=1))
except Exception as exc:
    print(f"lookup ERROR {exc}")
