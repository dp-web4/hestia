import sys, json, importlib.util
spec = importlib.util.spec_from_file_location("hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec); spec.loader.exec_module(hm)
h, s = hm.connect()
out = hm.rpc(h, "hestia_scope_status", {"plugin_id": "cbp-being"})
print("live_grants:", json.dumps(out.get("live_grants", []), indent=1))
