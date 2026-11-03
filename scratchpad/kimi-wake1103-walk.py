import json, importlib.util
spec = importlib.util.spec_from_file_location("hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec); spec.loader.exec_module(hm)
h, s = hm.connect()

def by_hash(hx):
    return hm.rpc(h, "hestia_query_history", {"session_id": s, "filter": {"hash": hx}})

cur = "3823765001fff400e2bca1e109e271fb3f062de47a298dc796335a3d26b0decd"  # settled entry
seen = []
for i in range(60):
    r = by_hash(cur)
    e = r.get("entry") or {}
    if not e:
        print("stop:", json.dumps(r)[:300]); break
    seen.append(e)
    js = json.dumps(e)
    if "29f13b3bc3bb8d4c" in js or "escalation" in e.get("eventType", "") or e.get("eventType") in ("gate_decision",):
        print("=== pos", e.get("chainPosition"), e.get("eventType"), e.get("timestamp"))
        print(json.dumps(e.get("eventData", {}), indent=1)[:1500])
    cur = e.get("prevHash", "")
    if set(cur) == {"0"}:
        print("genesis"); break
print("walked", len(seen), "positions", seen[-1].get("chainPosition"), "->", seen[0].get("chainPosition"))
