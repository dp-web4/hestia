#!/usr/bin/env python3
"""Wake-1022u: dump tail-500 chain entries mentioning the target dir name, with timestamps."""
import importlib.util
import json
import time
from datetime import datetime


def parse_ts(v):
    if isinstance(v, (int, float)):
        return float(v)
    return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()
hist = hm.rpc(h, "hestia_query_history", {"filter": {"limit": 500}})
entries = hist.get("entries", []) if isinstance(hist, dict) else []
print("entries:", len(entries))
if entries:
    e0, e1 = entries[0], entries[-1]
    print("first keys:", sorted(e0.keys()))
    for lbl, e in (("first", e0), ("last", e1)):
        ts = parse_ts(e.get("timestamp"))
        print(lbl, "ts:", e.get("timestamp"), time.strftime("%H:%M:%S", time.gmtime(ts)),
              "pos:", e.get("chainPosition"), "event:", e.get("eventType"))

TARGET = "auto-cbp-being-scope-search-2026-10-22-080842-bf1ea7f1"
for e in entries:
    blob = json.dumps(e, default=str)
    if TARGET in blob:
        ts = parse_ts(e.get("timestamp"))
        print("=" * 100)
        print(time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts)),
              "pos:", e.get("chainPosition"),
              "event:", e.get("eventType"),
              "plugin:", (e.get("eventData") or {}).get("plugin_id") if isinstance(e.get("eventData"), dict) else None)
        print(blob[:2400])
