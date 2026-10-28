import json, sys
sys.path.insert(0, "/home/dp/ai-workspace/hestia/tools")
from claude_daemon_client import call
for esc in ("7555d99bc158d821", "7b827655bf55f4f3"):
    try:
        out = call("hestia_gate_escalation_lookup", {"escalation_id": esc})
        print(f"== {esc}")
        print(json.dumps(out, indent=1)[:3500])
    except Exception as exc:
        print(f"== {esc}: ERROR {exc}")
