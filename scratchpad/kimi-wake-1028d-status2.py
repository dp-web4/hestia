import json, importlib.util
spec = importlib.util.spec_from_file_location("hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec); spec.loader.exec_module(hm)
h, s = hm.connect()
want = {"scope-ba7f1fe7106c", "scope-6839185fc6f6"}
for pid in ("kimi-code", "cbp-being", "claude-code"):
    out = hm.rpc(h, "hestia_scope_status", {"session_id": s, "plugin_id": pid})
    reqs = out.get("requests", [])
    print(pid, "live-map count:", len(reqs))
    for r in reqs:
        rid = r.get("request_id")
        if rid in want:
            print(" HIT", json.dumps(r, indent=1)[:2500])
