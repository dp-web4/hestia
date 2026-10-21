#!/usr/bin/env python3
"""Wake-1038: status of scope-f4cd3f7624fb (ruled), scope-44355d934301 (peer-decide ask),
and escalation e6d875839a0a87e2 (corroborate-or-dissent ask)."""
import importlib.util, json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()

for rid in ("scope-f4cd3f7624fb", "scope-44355d934301"):
    try:
        out = hm.rpc(h, "hestia_scope_status", {"session_id": s, "request_id": rid})
        print(f"===== scope_status {rid} =====")
        print(json.dumps(out, indent=1)[:4000])
    except Exception as e:
        print(f"===== scope_status {rid} EXC {e} =====")

for tool in ("hestia_escalation_evidence", "hestia_gate_escalation_poll", "hestia_gate_escalation_lookup"):
    try:
        out = hm.rpc(h, tool, {"session_id": s, "plugin_id": "kimi-code",
                               "escalation_id": "e6d875839a0a87e2"})
        print(f"===== {tool} e6d875839a0a87e2 =====")
        print(json.dumps(out, indent=1)[:4500])
    except Exception as e:
        print(f"===== {tool} EXC {e} =====")
