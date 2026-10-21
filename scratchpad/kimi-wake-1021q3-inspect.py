import json, importlib.util
spec = importlib.util.spec_from_file_location("hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec); spec.loader.exec_module(hm)
h, s = hm.connect()
law = hm.rpc(h, "hestia_operating_law", {"session_id": s})
print("LAW_HASH", law.get("law_hash") or law.get("hash") or list(law.keys()))
out = hm.rpc(h, "hestia_scope_status", {"session_id": s, "plugin_id": "claude-code"})
for r in out.get("requests", []):
    if r.get("request_id") == "scope-d955d2b3c1db":
        print(json.dumps(r, indent=1))
