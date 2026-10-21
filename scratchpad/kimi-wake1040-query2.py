#!/usr/bin/env python3
import importlib.util, json
spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)
h, s = hm.connect()
out = hm.rpc(h, "hestia_scope_status", {"session_id": s, "plugin_id": "codex"})
reqs = out.get("requests", [])
for r in reqs:
    if r.get("request_id") == "scope-f1cd85bff22d":
        print(json.dumps(r, indent=1))
        break
else:
    print("NOT FOUND; codex requests:", [r.get("request_id") for r in reqs][:15])
