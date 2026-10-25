#!/usr/bin/env python3
"""Wake-1025: walk the witness chain back from the settled entry of escalation
a9e31fdbc9c5bf8f, collecting every entry that names it (open/factors/settle)."""
import importlib.util, json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

EID = "a9e31fdbc9c5bf8f"
h, s = hm.connect()
cursor = "3459b19547be62841670ea87e6c9ee423bf9b0dc7fd1fe9b1ed9d48165538eb5"  # settled entry
hits, steps = [], 0
while cursor and steps < 400:
    out = hm.rpc(h, "hestia_query_history", {"session_id": s, "filter": {"hash": cursor}})
    ent = out.get("entry")
    if not ent:
        print("STOP", json.dumps(out)[:300]); break
    steps += 1
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
    print(json.dumps(ed, indent=1)[:2500])
