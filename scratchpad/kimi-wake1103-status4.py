import json, importlib.util
spec = importlib.util.spec_from_file_location("hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec); spec.loader.exec_module(hm)
h, s = hm.connect()
for rid in ["scope-5e29e5ad34e6", "scope-fe1638af32f6", "scope-13a40fa75754", "scope-0af0bce9a0f8"]:
    out = hm.rpc(h, "hestia_scope_status", {"session_id": s, "request_id": rid, "plugin_id": "cbp-being"})
    reqs = [r for r in out.get("requests", []) if r.get("request_id") == rid]
    print("=== " + rid + " ===")
    print(json.dumps(reqs[0] if reqs else {"not_found": True, "count": len(out.get("requests", [])), "err": out.get("_jsonrpc_error")}, indent=1))
