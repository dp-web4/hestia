#!/usr/bin/env python3
"""Wake-1045: extract only scope_* events naming 93b1003f27d5."""
import importlib.util, json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()
d = hm.rpc(h, "hestia_query_history", {"session_id": s, "filter": {"limit": 500}})
for e in d.get("entries", []):
    if "93b1003f27d5" not in json.dumps(e):
        continue
    et = e.get("eventType", "")
    if et.startswith("scope") or et == "member_notice":
        ed = e["eventData"]
        if et == "member_notice" and ed.get("from_plugin_id") == "kimi-code":
            continue
        print(json.dumps({"pos": e["chainPosition"], "ts": e["timestamp"],
                          "type": et, "hash": e["hash"][:16], "data": ed}, indent=1))
        print("---")
