#!/usr/bin/env python3
"""wake-1028a: look up the two 10-21 escalations cbp-being asked me on (30308, 30320)."""
import json
import sys

sys.path.insert(0, "/home/dp/ai-workspace/hestia/tools")
from claude_daemon_client import call

for esc in ("8c836a4702568e7f", "3270a69531272104"):
    try:
        out = call("hestia_gate_escalation_lookup", {"escalation_id": esc})
        print(f"== {esc}")
        print(json.dumps(out, indent=1)[:2600])
    except Exception as exc:
        print(f"== {esc}: ERROR {exc}")
