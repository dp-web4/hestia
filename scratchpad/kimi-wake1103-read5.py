import json, importlib.util
spec = importlib.util.spec_from_file_location("hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec); spec.loader.exec_module(hm)
h, s = hm.connect()

# 1) resource reads for the four scope pointers + the escalation
for uri in ["hestia://scope/scope-5e29e5ad34e6", "hestia://scope/scope-fe1638af32f6",
            "hestia://scope/scope-13a40fa75754", "hestia://scope/scope-0af0bce9a0f8",
            "hestia://escalation/29f13b3bc3bb8d4c"]:
    body, _ = hm.post({"jsonrpc": "2.0", "id": 8, "method": "resources/read", "params": {"uri": uri}}, h)
    print("=== READ " + uri + " ===")
    print(body[:1200])
    print()

# 2) scope_status unfiltered (all plugins) — check the four ids against full map
out = hm.rpc(h, "hestia_scope_status", {"session_id": s})
reqs = out.get("requests", [])
print("=== scope_status all: count=" + str(len(reqs)) + " ===")
for rid in ["scope-5e29e5ad34e6", "scope-fe1638af32f6", "scope-13a40fa75754", "scope-0af0bce9a0f8"]:
    hit = [r for r in reqs if r.get("request_id") == rid]
    print(rid + " -> " + ("FOUND " + json.dumps(hit[0])[:400] if hit else "absent"))
