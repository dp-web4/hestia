#!/usr/bin/env python3
"""Wake-1040: status of scope-f1cd85bff22d (codex review_request 29740, my peer-decide)
and scope-2f474cfa60a5 (my auto-opened scope, refused per notices 29748/29749/29752)."""
import importlib.util, json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()

for rid in ("scope-f1cd85bff22d", "scope-2f474cfa60a5"):
    try:
        out = hm.rpc(h, "hestia_scope_status", {"session_id": s, "plugin_id": "kimi-code", "request_id": rid})
        print(f"===== scope_status {rid} =====")
        print(json.dumps(out, indent=1)[:6000])
    except Exception as e:
        print(f"===== scope_status {rid} EXC {e} =====")
