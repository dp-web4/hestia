#!/usr/bin/env python3
"""Wake 1025 (eSEU3W): collect chain events mentioning scope-d31b8f061291
and/or escalation 40ce2df6aba45389. Walks back from chain head."""
import importlib.util, json
spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec); spec.loader.exec_module(hm)
IDS = ("scope-d31b8f061291", "40ce2df6aba45389")
h, s = hm.connect()

out = hm.rpc(h, "hestia_query_history", {"session_id": s, "filter": {"limit": 1}})
ent = out.get("entries", [{}])[0] or out.get("entry")
cursor = ent.get("hash") or ent.get("chainHash")
print("head:", cursor, "pos", ent.get("chainPosition"), ent.get("timestamp"))

hits = {i: [] for i in IDS}
steps = 0
while cursor and steps < 4000:
    out = hm.rpc(h, "hestia_query_history", {"session_id": s, "filter": {"hash": cursor}})
    ent = out.get("entry")
    if not ent:
        break
    steps += 1
    blob = json.dumps(ent)
    for i in IDS:
        if i in blob:
            hits[i].append(ent)
    cursor = ent.get("prevHash")
print("walked", steps)
for i in IDS:
    print(f"\n########## {i}: {len(hits[i])} event(s) ##########")
    for ent in reversed(hits[i]):
        print("== ", ent.get("eventType"), ent.get("timestamp"), "chain", ent.get("chainPosition"))
        print(json.dumps(ent.get("eventData", {}), indent=1)[:2200])
