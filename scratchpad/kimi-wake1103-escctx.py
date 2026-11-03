import json, importlib.util
spec = importlib.util.spec_from_file_location("hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec); spec.loader.exec_module(hm)
h, s = hm.connect()
# window around the settled (692455) and claimed (692554) positions to find the opened entry + refusal context
out = hm.rpc(h, "hestia_query_history", {"session_id": s, "filter": {"limit": 500, "tool_name": "gate"}})
entries = out.get("entries", [])
hits = [e for e in entries if "29f13b3bc3bb8d4c" in json.dumps(e)]
print("gate-window entries:", len(entries), "hits:", len(hits))
for e in hits:
    print(json.dumps(e, indent=1)[:2000])
    print("---")
