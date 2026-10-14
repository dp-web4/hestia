#!/usr/bin/env python3
"""Print chain entries in a position window, compactly."""
import importlib.util, json, sys

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

LO, HI = int(sys.argv[1]), int(sys.argv[2])

h, s = hm.connect()
head = hm.rpc(h, "hestia_query_history", {"filter": {"limit": 1}})["entries"][0]
cursor = head["hash"]
while True:
    e = hm.rpc(h, "hestia_query_history", {"filter": {"hash": cursor}})
    ent = e.get("entry") or e
    if "_hestia_error" in e or "_jsonrpc_error" in e:
        print("walk terminated:", json.dumps(e)[:200])
        break
    pos = ent.get("chainPosition", -1)
    if LO <= pos <= HI:
        ed = ent.get("eventData", {})
        summary = ed.get("request_id") or ed.get("pointer_uri") or (ed.get("act") or ed.get("attempted") or ed.get("target") or "")[:90]
        print(f"{pos} {ent.get('timestamp','')[:19]} {ent.get('eventType',''):24s} {ed.get('plugin_id',''):12s} {summary}")
    if pos < LO:
        break
    prev = ent.get("prevHash")
    if not prev or set(prev) == {"0"}:
        break
    cursor = prev
