import json, importlib.util, time
spec = importlib.util.spec_from_file_location("hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec); spec.loader.exec_module(hm)
h, s = hm.connect()

IDS = ["scope-c2f5e14e92ea","scope-ca7399e629f3","scope-ae3ffbfb36a6","scope-2a5241c248d5",
       "scope-c595cb36acc1","scope-92d27ebbee3f","scope-2f2499417f36","scope-e46ee4e31f52",
       "scope-288392f2c33a","scope-7a35d7f7e712","scope-6a259d3ec696","scope-8a03a0bd2bba",
       "scope-9cce887f2166","scope-b853796a947b","scope-20d53a4871c1","scope-d23045e51a04",
       "scope-2c10fcdb19cf","scope-d0b093c2b6eb","scope-d099aa1d1974","scope-47a7328c42f1",
       "scope-ae0e61985fc0","scope-9bc145280b50"]
STOP_TS = "2026-11-01T00:00:00"
OUT = "/home/dp/ai-workspace/hestia/scratchpad/kimi-wake1103-walk22.out"

head = hm.rpc(h, "hestia_query_history", {"session_id": s, "filter": {"limit": 1}})
e0 = (head.get("entries") or [None])[0]
log = open(OUT, "w")
def emit(o): log.write(json.dumps(o) + "\n"); log.flush()
emit({"kind": "start", "head_pos": e0.get("chainPosition"), "head_ts": e0.get("timestamp")})
cur = e0.get("hash"); hits = 0; t0 = time.time()
for i in range(120000):
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
    if i % 5000 == 0:
        emit({"kind": "progress", "hop": i, "pos": e.get("chainPosition"), "ts": ts})
    if ts < STOP_TS:
        emit({"kind": "done", "hop": i, "pos": e.get("chainPosition"), "ts": ts, "hits": hits, "elapsed_s": round(time.time()-t0,1)}); break
    cur = e.get("prevHash", "")
    if set(cur) == {"0"}:
        emit({"kind": "genesis"}); break
log.close()
print("hits:", hits, "->", OUT)
