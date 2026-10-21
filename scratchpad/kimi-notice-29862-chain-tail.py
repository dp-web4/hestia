#!/usr/bin/env python3
"""Find the policy_decision / escalation entries for cbp-being near 10:34:33Z."""
import importlib.util
import json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()
out = hm.rpc(h, "hestia_query_history", {"session_id": s, "plugin_id": "kimi-code",
                                         "filter": {"limit": 500}})
for e in out.get("entries", []):
    d = e.get("eventData", {})
    blob = json.dumps(d)
    if "cbp-being" not in blob and "179cd0c97b52325a" not in blob:
        continue
    et = e.get("eventType")
    if et in ("policy_decision", "gate_escalation_opened", "gate_escalation",
              "escalation", "member_notice") or "179cd0c97b52325a" in blob:
        print("=" * 100)
        print(e.get("chainPosition"), e.get("timestamp"), et, e.get("hash")[:16])
        print(json.dumps(d, indent=1)[:6000])
