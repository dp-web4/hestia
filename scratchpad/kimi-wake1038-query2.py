#!/usr/bin/env python3
"""Wake-1038b: scope status with plugin_id; full escalation evidence rows."""
import importlib.util, json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()

for rid in ("scope-f4cd3f7624fb", "scope-44355d934301"):
    out = hm.rpc(h, "hestia_scope_status", {"session_id": s, "plugin_id": "kimi-code",
                                            "request_id": rid})
    print(f"===== scope_status {rid} =====")
    print(json.dumps(out, indent=1)[:4000])

out = hm.rpc(h, "hestia_escalation_evidence", {"session_id": s, "plugin_id": "kimi-code",
                                               "escalation_id": "e6d875839a0a87e2"})
ev = out.get("evidence", {})
print("===== prior_on_this_marker full rows =====")
print(json.dumps(ev.get("prior_on_this_marker"), indent=1)[:6000])
print("===== member_refusals =====")
print(json.dumps(ev.get("member_refusals"), indent=1)[:1200])
