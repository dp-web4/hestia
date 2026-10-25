#!/usr/bin/env python3
"""Wake-1025: longer walk back from settled entry; report timestamps each 200 hops
and collect every entry naming escalation a9e31fdbc9c5bf8f."""
import importlib.util, json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

EID = "a9e31fdbc9c5bf8f"
h, s = hm.connect()
cursor = "c438201a6292c2d2cf3baf6e6d7439f1441328cb135f608e78143fb1286edb4a"  # prevHash of settled entry
hits, steps = [], 0
while cursor and steps < 3000:
    out = hm.rpc(h, "hestia_query_history", {"session_id": s, "filter": {"hash": cursor}})
    ent = out.get("entry")
    if not ent:
        print("STOP", json.dumps(out)[:300]); break
    steps += 1
    if steps % 500 == 0:
        print(f"...{steps} hops, at {ent.get('timestamp')} pos {ent.get('chainPosition')}", flush=True)
    blob = json.dumps(ent)
    if EID in blob:
        hits.append(ent)
        if ent.get("eventType") == "gate_escalation_opened":
            break
    cursor = ent.get("prevHash")
print(f"walked {steps} entries, {len(hits)} hits")
for ent in reversed(hits):
    ed = ent.get("eventData", {})
    print("=" * 20, ent.get("eventType"), ent.get("timestamp"), "chain", ent.get("chainPosition"))
    print(json.dumps(ed, indent=1)[:3000])
