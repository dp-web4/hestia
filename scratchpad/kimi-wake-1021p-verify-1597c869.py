#!/usr/bin/env python3
"""Wake 1021p: read prior escalation 1597c8699fc0e168 to confirm digest + ruling."""
import importlib.util, json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()
out = hm.rpc(h, "hestia_escalation_evidence", {
    "session_id": s,
    "escalation_id": "1597c8699fc0e168",
})
esc = out.get("evidence", {}).get("escalation", {})
print(json.dumps({
    "found": out.get("found"),
    "id": esc.get("id"),
    "status": esc.get("status"),
    "bar_met": esc.get("bar_met"),
    "act_digest": esc.get("act_digest"),
    "tool_name": esc.get("tool_name"),
    "stated_reason": esc.get("stated_reason"),
    "payload_sha256": esc.get("payload_sha256"),
    "factors": [{"by": f.get("by"), "dissent": f.get("dissent"),
                 "at": f.get("at"),
                 "argument": (f.get("argument") or "")[:300]} for f in esc.get("factors", [])],
}, indent=1))
