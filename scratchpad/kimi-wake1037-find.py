#!/usr/bin/env python3
"""Wake-1037: locate scope-3507a042e262, scope-7a1b0b922334, escalation f87dd9850f246bcc
on the witness chain; print every entry mentioning any of them."""
import importlib.util, json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

NEEDLES = ("3507a042e262", "7a1b0b922334", "f87dd9850f246bcc")

h, s = hm.connect()
head = hm.rpc(h, "hestia_query_history", {"filter": {"limit": 1}})["entries"][0]
print("head:", head["chainPosition"], head["timestamp"], head["eventType"])

hits = {n: [] for n in NEEDLES}
cursor = head["hash"]
walked = 0
while walked < 8000:
    e = hm.rpc(h, "hestia_query_history", {"filter": {"hash": cursor}})
    ent = e.get("entry") or e
    if "_hestia_error" in e or "_jsonrpc_error" in e:
        print("walk terminated:", json.dumps(e)[:200]); break
    ts = ent.get("timestamp", "")
    blob = json.dumps(ent)
    for n in NEEDLES:
        if n in blob:
            hits[n].append(ent)
    if ts < "2026-10-21T07:30":
        break
    prev = ent.get("prevHash")
    if not prev or set(prev) == {"0"}:
        break
    cursor = prev; walked += 1

print(f"walked={walked}")
for n in NEEDLES:
    print(f"\n######## {n}: {len(hits[n])} entries ########")
    for ent in sorted(hits[n], key=lambda x: x.get("chainPosition", 0)):
        ed = ent.get("eventData", {})
        print(f"--- chain {ent.get('chainPosition')} {ent.get('timestamp','')[:23]} {ent.get('eventType')} hash={ent.get('hash','')[:16]}")
        print(json.dumps(ed, indent=1)[:2600])
