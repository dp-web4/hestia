#!/usr/bin/env python3
"""Wake-1022x: context for notice 31288 (scope-dc5fa6139686#peer-decide, claude-code).
1. Fresh scope_status read of the petition (race guard).
2. Recent chain entries around requested_at (1792690489 ~ 17:34:49Z) — what was
   claude-code doing when the gate denied the act?
"""
import importlib.util
import json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()

out = hm.rpc(h, "hestia_scope_status", {"plugin_id": "claude-code"})
hits = [r for r in out.get("requests", []) if r.get("request_id") == "scope-dc5fa6139686"]
print("petition:", json.dumps(hits[0] if hits else None, indent=1))

hist = hm.rpc(h, "hestia_query_history", {"filter": {"limit": 25}})
entries = hist.get("entries", hist if isinstance(hist, list) else [])
for e in entries:
    blob = json.dumps(e)
    if "claude-code" in blob or "dc5fa6139686" in blob:
        print(json.dumps(e)[:600])
