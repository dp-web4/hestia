#!/usr/bin/env python3
"""Wake-1036: verify scope-b3cf8cdb88f5 ruling on the witness chain + cbp-being's morning activity."""
import importlib.util, json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()
head = hm.rpc(h, "hestia_query_history", {"filter": {"limit": 1}})["entries"][0]
print("head:", head["chainPosition"], head["timestamp"], head["eventType"])

hits, cbp = [], []
cursor = head["hash"]
walked = 0
while walked < 6000:
    e = hm.rpc(h, "hestia_query_history", {"filter": {"hash": cursor}})
    ent = e.get("entry") or e
    if "_hestia_error" in e or "_jsonrpc_error" in e:
        print("walk terminated:", json.dumps(e)[:200]); break
    pos = ent.get("chainPosition", -1)
    ts = ent.get("timestamp", "")
    ed = ent.get("eventData", {})
    blob = json.dumps(ent)
    if "b3cf8cdb88f5" in blob:
        hits.append(ent)
    if ts >= "2026-10-21T07:30" and ts <= "2026-10-21T08:15" and "cbp-being" in blob:
        cbp.append(ent)
    if ts < "2026-10-21T07:00":
        break
    prev = ent.get("prevHash")
    if not prev or set(prev) == {"0"}:
        break
    cursor = prev; walked += 1

print(f"walked={walked} hits_on_scope={len(hits)} cbp_window={len(cbp)}")
for ent in sorted(hits, key=lambda x: x.get("chainPosition", 0)):
    ed = ent.get("eventData", {})
    print(f"\n--- chain {ent.get('chainPosition')} {ent.get('timestamp','')[:23]} {ent.get('eventType')} hash={ent.get('hash','')[:16]}")
    print(json.dumps(ed, indent=1)[:1800])
print("\n=== cbp-being 07:30-08:15Z activity ===")
for ent in sorted(cbp, key=lambda x: x.get("chainPosition", 0)):
    ed = ent.get("eventData", {})
    tgt = ed.get("path") or ed.get("target") or ed.get("pointer_uri") or ed.get("act") or ""
    print(f"{ent.get('chainPosition')} {ent.get('timestamp','')[:19]} {ent.get('eventType',''):22s} {str(tgt)[:110]}")
