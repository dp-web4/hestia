#!/usr/bin/env python3
"""Wake-1022u: what did claude-code do between the refusal (15:10:47Z) and chain tail (15:12:55Z)?"""
import importlib.util
import json
import time
from datetime import datetime

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()
hist = hm.rpc(h, "hestia_query_history", {"filter": {"limit": 500}})
entries = hist.get("entries", []) if isinstance(hist, dict) else []

def parse_ts(v):
    return datetime.fromisoformat(str(v).replace("Z", "+00:00")).timestamp()

t_refuse = parse_ts("2026-10-22T15:10:47+00:00")
for e in entries:
    ts = parse_ts(e.get("timestamp"))
    if ts < t_refuse - 1:
        continue
    ed = e.get("eventData") or {}
    if not isinstance(ed, dict):
        continue
    pid = ed.get("plugin_id", "?")
    et = e.get("eventType")
    tgt = str(ed.get("target") or ed.get("attempted") or ed.get("act") or ed.get("request_id") or "")[:170]
    print(f"{time.strftime('%H:%M:%S', time.gmtime(ts))} pos={e.get('chainPosition')} {et} {pid} :: {tgt}")
