import json, importlib.util, sys, time
spec = importlib.util.spec_from_file_location("hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec); spec.loader.exec_module(hm)
h, s = hm.connect()

IDS = ["scope-5e29e5ad34e6", "scope-fe1638af32f6", "scope-13a40fa75754", "scope-0af0bce9a0f8"]
STOP_TS = "2026-10-25T00:00:00"   # one day before earliest petition (2026-10-26T19:18Z)
MAX_HOPS = 260000
OUT = "/home/dp/ai-workspace/hestia/scratchpad/kimi-wake1103-walk4.out"

head = hm.rpc(h, "hestia_query_history", {"session_id": s, "filter": {"limit": 1}})
e0 = (head.get("entries") or [None])[0]
if not e0:
    print(json.dumps({"error": "no head", "raw": head})); sys.exit(1)

log = open(OUT, "w")
def emit(obj):
    log.write(json.dumps(obj) + "\n"); log.flush()

emit({"kind": "start", "head_pos": e0.get("chainPosition"), "head_ts": e0.get("timestamp"), "head_hash": e0.get("hash")})
cur = e0.get("hash")
hits = []
t0 = time.time()
for i in range(MAX_HOPS):
    r = hm.rpc(h, "hestia_query_history", {"session_id": s, "filter": {"hash": cur}})
    e = r.get("entry")
    if not e:
        emit({"kind": "stop", "hop": i, "reason": json.dumps(r)[:300]}); break
    ts = e.get("timestamp", "")
    js = json.dumps(e.get("eventData", {}))
    for rid in IDS:
        if rid in js:
            hits.append(e)
            emit({"kind": "hit", "id": rid, "pos": e.get("chainPosition"), "event": e.get("eventType"), "ts": ts, "data": e.get("eventData")})
    if i % 10000 == 0:
        emit({"kind": "progress", "hop": i, "pos": e.get("chainPosition"), "ts": ts, "elapsed_s": round(time.time() - t0, 1)})
    if ts < STOP_TS:
        emit({"kind": "done", "hop": i, "pos": e.get("chainPosition"), "ts": ts, "hits": len(hits), "elapsed_s": round(time.time() - t0, 1)}); break
    cur = e.get("prevHash", "")
    if set(cur) == {"0"}:
        emit({"kind": "genesis", "hop": i}); break
else:
    emit({"kind": "cap", "hops": MAX_HOPS, "hits": len(hits)})
log.close()
print("hits:", len(hits), "->", OUT)
