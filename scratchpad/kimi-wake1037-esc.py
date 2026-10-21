#!/usr/bin/env python3
"""Wake-1037: pull escalation f87dd9850f246bcc evidence + poll state."""
import importlib.util, json, sys

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()
for tool in ("hestia_escalation_evidence", "hestia_gate_escalation_poll", "hestia_gate_escalation_lookup"):
    try:
        out = hm.rpc(h, tool, {"session_id": s, "plugin_id": "kimi-code",
                               "escalation_id": "f87dd9850f246bcc"})
        print(f"===== {tool} =====")
        print(json.dumps(out, indent=1)[:4500])
        print()
    except Exception as e:
        print(f"===== {tool} EXC {e} =====")
