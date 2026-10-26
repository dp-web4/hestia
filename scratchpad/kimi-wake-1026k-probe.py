#!/usr/bin/env python3
"""Wake 2026-10-26 (k): probe notice 33408 from cbp-being.

Read-only: dump the full scope request row for scope-0af0bce9a0f8 so the
review is done on evidence, not pointer strings.
"""
import importlib.util
import json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

RID = "scope-0af0bce9a0f8"

h, s = hm.connect()
out = hm.rpc(h, "hestia_scope_status", {"session_id": s, "plugin_id": "cbp-being"})
reqs = out.get("requests") or []
print("cbp-being rows:", len(reqs))
hits = [r for r in reqs if r.get("request_id") == RID]
print("=== %s | hit: %d" % (RID, len(hits)))
for row in hits:
    print(json.dumps(row, indent=2, sort_keys=True, default=str))
