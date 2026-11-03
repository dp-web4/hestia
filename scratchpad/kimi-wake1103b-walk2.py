import json, importlib.util, time
spec = importlib.util.spec_from_file_location("hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec); spec.loader.exec_module(hm)
h, s = hm.connect()

IDS = ["scope-ae4165e166b5", "scope-8934275e4e6f"]
STOP_TS = "2026-11-03T17:30:00"
OUT = "/home/dp/ai-workspace/hestia/scratchpad/kimi-wake1103b-walk2b.out"

head = hm.rpc(h, "hestia_query_history", {"session_id": s, "filter": {"limit": 1}})
e0 = (head.get("entries") or [None])[0]
log = open(OUT, "w")
def emit(o): log.write(json.dumps(o) + "\n"); log.flush()
emit({"kind": "start", "head_pos": e0.get("chainPosition"), "head_ts": e0.get("timestamp")})
cur = e0.get("hash"); hits = 0; t0 = time.time()
for i in range(20000):
    r = hm.rpc(h, "hestia_query_history", {"session_id": s, "filter": {"hash": cur}})
    e = r.get("entry")
    if not e:
        emit({"kind": "stop", "hop": i, "reason": json.dumps(r)[:200]}); break
    ts = e.get("timestamp", "")
    et = e.get("eventType", "")
    js = json.dumps(e.get("eventData", {}))
    if et.startswith("scope_"):
        for rid in IDS:
            if rid in js:
                hits += 1
                emit({"kind": "hit", "id": rid, "pos": e.get("chainPosition"), "event": et, "ts": ts, "data": e.get("eventData")})
    if ts < STOP_TS:
        emit({"kind": "done", "hop": i, "pos": e.get("chainPosition"), "ts": ts, "hits": hits, "elapsed_s": round(time.time()-t0,1)}); break
    cur = e.get("prevHash", "")
    if set(cur) == {"0"}:
        emit({"kind": "genesis"}); break
log.close()
print("hits:", hits, "->", OUT)
