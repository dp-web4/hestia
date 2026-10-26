#!/usr/bin/env python3
"""Wake 2026-10-26 (j): probe notices 33391/33394 from cbp-being.

Read-only: dump the full scope request rows for scope-fe1638af32f6 and
scope-13a40fa75754 so the review is done on evidence, not pointer strings.
"""
import importlib.util
import json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

RIDS = ["scope-fe1638af32f6", "scope-13a40fa75754"]

h, s = hm.connect()
out = hm.rpc(h, "hestia_scope_status", {"session_id": s, "plugin_id": "cbp-being"})
reqs = out.get("requests") or []
print("cbp-being rows:", len(reqs))
for rid in RIDS:
    hits = [r for r in reqs if r.get("request_id") == rid]
    print("=== %s | hit: %d" % (rid, len(hits)))
    for row in hits:
        print(json.dumps(row, indent=2, sort_keys=True, default=str))
