#!/usr/bin/env python3
"""Wake-1025: continue the walk back to gate_escalation_opened for a9e31fdbc9c5bf8f,
plus any cbp-being write_note deny in the same window."""
import importlib.util, json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

EID = "a9e31fdbc9c5bf8f"
h, s = hm.connect()
cursor = None
# resume: find entry at/near chain 570380 by hash-walking from a known entry is slow;
# instead re-walk from the settled entry's prevHash and keep everything of interest.
cursor = "c438201a6292c2d2cf3baf6e6d7439f1441328cb135f608e78143fb1286edb4a"
hits, steps = [], 0
while cursor and steps < 1500:
    out = hm.rpc(h, "hestia_query_history", {"session_id": s, "filter": {"hash": cursor}})
    ent = out.get("entry")
    if not ent:
        print("STOP", json.dumps(out)[:300]); break
    steps += 1
    blob = json.dumps(ent)
    et = ent.get("eventType", "")
    ed = ent.get("eventData", {})
    keep = False
    if EID in blob:
        keep = True
        if et == "gate_escalation_opened":
            hits.append(ent); break
    elif et == "policy_decision" and ed.get("plugin_id") == "cbp-being" and "journal" in blob:
        keep = True
    elif et == "policy_allow" and ed.get("plugin_id") == "cbp-being" and "journal" in blob:
        keep = True
    if keep:
        hits.append(ent)
    cursor = ent.get("prevHash")
print(f"walked {steps}, hits {len(hits)}")
for ent in reversed(hits):
    ed = ent.get("eventData", {})
    print("=" * 20, ent.get("eventType"), ent.get("timestamp"), "chain", ent.get("chainPosition"))
    print(json.dumps(ed, indent=1)[:1800])
