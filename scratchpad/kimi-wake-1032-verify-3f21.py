#!/usr/bin/env python3
"""Wake 1032: verify scope-3f21b90a6904 (notice 33005) — chain_hash, full event trail, status."""
import importlib.util, json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

RID = "scope-3f21b90a6904"
NOTICE_HASH = "8037f71d28520664055a2c8d411253d49ef6aca8ae936d8c7a6ba2e0bd25851e"
h, s = hm.connect()

def qh(filt):
    return hm.rpc(h, "hestia_query_history", {"session_id": s, "filter": filt})

print("=== notice chain_hash entry ===")
out = qh({"hash": NOTICE_HASH})
ent = out.get("entry") or {}
print(json.dumps({k: ent.get(k) for k in ("hash", "eventType", "timestamp", "chainPosition")}, indent=1))
print(json.dumps(ent.get("eventData", {}), indent=1)[:2500])
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
    print(json.dumps(e.get("eventData", {}), indent=1)[:2500])

print("=== resources/read hestia://scope/%s ===" % RID)
body, _ = hm.post({"jsonrpc": "2.0", "id": 3, "method": "resources/read",
                   "params": {"uri": f"hestia://scope/{RID}"}}, h)
for line in body.splitlines():
    if line.startswith("data: {"):
        env = json.loads(line[6:])
        try:
            for c in env["result"]["contents"]:
                print(c.get("text", "")[:4000])
        except (KeyError, TypeError):
            print("ERROR", json.dumps(env)[:1500])

print("=== hestia_scope_status ===")
out = hm.rpc(h, "hestia_scope_status", {"session_id": s, "request_id": RID,
                                        "plugin_id": "kimi-code"})
print(json.dumps(out, indent=1)[:4000])
