#!/usr/bin/env python3
"""Wake 1026: verify scope-ce6c124b6112 chain — notice chain_hash, terminal event, gap."""
import importlib.util, json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

RID = "scope-ce6c124b6112"
NOTICE_HASH = "6382349d9890070b27da6927ea43ed46323a8269f8dde1af9d13b601fa0866d3"
h, s = hm.connect()

def qh(filt):
    return hm.rpc(h, "hestia_query_history", {"session_id": s, "filter": filt})

print("=== notice chain_hash entry ===")
out = qh({"hash": NOTICE_HASH})
ent = out.get("entry") or {}
print(json.dumps({k: ent.get(k) for k in ("hash", "eventType", "timestamp", "chainPosition")}, indent=1))
print(json.dumps(ent.get("eventData", {}), indent=1)[:2000])
req_pos = ent.get("chainPosition") or 0

print("=== newest-first window (limit 500) ===")
out = qh({"limit": 500})
ents = out.get("entries") or []
print(f"window: {len(ents)} entries, head pos {ents[0].get('chainPosition') if ents else '?'}, "
      f"oldest {ents[-1].get('chainPosition') if ents else '?'}, request at {req_pos}")
hits = [e for e in ents if RID in json.dumps(e)]
print(f"hits naming {RID}: {len(hits)}")
for e in reversed(hits):
    print("=" * 16, e.get("eventType"), e.get("timestamp"), "pos", e.get("chainPosition"))
    print(json.dumps(e.get("eventData", {}), indent=1)[:2200])
