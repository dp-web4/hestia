import json, importlib.util, time
spec = importlib.util.spec_from_file_location("hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec); spec.loader.exec_module(hm)
h, s = hm.connect()

STOP_TS = "2026-11-03T18:30:00"
head = hm.rpc(h, "hestia_query_history", {"session_id": s, "filter": {"limit": 1}})
e0 = (head.get("entries") or [None])[0]
print("head", e0.get("chainPosition"), e0.get("timestamp"))
cur = e0.get("hash"); t0 = time.time()
for i in range(20000):
    r = hm.rpc(h, "hestia_query_history", {"session_id": s, "filter": {"hash": cur}})
    e = r.get("entry")
    if not e:
        print("stop", json.dumps(r)[:200]); break
    ts = e.get("timestamp", "")
    et = e.get("eventType", "")
    if et == "member_notice":
        d = e.get("eventData", {})
        print(e.get("chainPosition"), ts[11:19], d.get("from_plugin_id") or d.get("from"), "->",
              d.get("to_plugin_id") or d.get("to"), d.get("kind"),
              "irt=", d.get("in_reply_to"), "nid=", d.get("notice_id") or d.get("id"))
    if ts < STOP_TS:
        print("done", i, "elapsed", round(time.time()-t0,1)); break
    cur = e.get("prevHash", "")
