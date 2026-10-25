#!/usr/bin/env python3
import importlib.util, json
spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec); spec.loader.exec_module(hm)
EID = "a9e31fdbc9c5bf8f"
h, s = hm.connect()
cursor = "c438201a6292c2d2cf3baf6e6d7439f1441328cb135f608e78143fb1286edb4a"
steps = 0
found_open = False
denies = []
while cursor and steps < 2500 and not found_open:
    out = hm.rpc(h, "hestia_query_history", {"session_id": s, "filter": {"hash": cursor}})
    ent = out.get("entry")
    if not ent: break
    steps += 1
    et = ent.get("eventType", ""); ed = ent.get("eventData", {})
    blob = json.dumps(ent)
    if et == "gate_escalation_opened" and EID in blob:
        print("OPENED at chain", ent.get("chainPosition"), ent.get("timestamp"))
        print(json.dumps(ed, indent=1)[:2500]); found_open = True
    elif et == "policy_decision" and ed.get("plugin_id") == "cbp-being" and "write" in blob and "journal" in blob and ed.get("decision") == "deny":
        denies.append(ent)
    cursor = ent.get("prevHash")
print("walked", steps)
for ent in reversed(denies):
    ed = ent.get("eventData", {})
    print("== DENY", ent.get("timestamp"), "chain", ent.get("chainPosition"))
    print(" attempted:", ed.get("attempted", "")[:300])
    print(" reason:", ed.get("reason", "")[:400])
