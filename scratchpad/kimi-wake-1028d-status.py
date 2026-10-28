import json, importlib.util
spec = importlib.util.spec_from_file_location("hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec); spec.loader.exec_module(hm)
h, s = hm.connect()
for pid in ("kimi-code", "cbp-being", "claude-code"):
    out = hm.rpc(h, "hestia_scope_status", {"session_id": s, "plugin_id": pid})
    reqs = out.get("requests", [])
    hit = [r for r in reqs if r.get("request_id") == "scope-892b5af200c4"]
    print(pid, "count:", len(reqs), "hit:", json.dumps(hit[0], indent=1)[:4000] if hit else "NO")
