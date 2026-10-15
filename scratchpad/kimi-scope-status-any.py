import sys, json, importlib.util
spec = importlib.util.spec_from_file_location("hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec); spec.loader.exec_module(hm)
h, s = hm.connect()
args = {"session_id": s, "request_id": sys.argv[1]}
if len(sys.argv) > 2:
    args["plugin_id"] = sys.argv[2]
out = hm.rpc(h, "hestia_scope_status", args)
print(json.dumps(out, indent=1))
