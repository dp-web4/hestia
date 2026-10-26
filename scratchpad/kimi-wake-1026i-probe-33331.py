#!/usr/bin/env python3
"""Wake 2026-10-26 (i): probe notice 33331 (scope-5e29e5ad34e6 from cbp-being).

Read-only: dump the full scope request row so the review can be done on
evidence, not on the pointer string.
"""
import importlib.util
import json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

RID = "scope-5e29e5ad34e6"

h, s = hm.connect()
out = hm.rpc(h, "hestia_scope_status", {"session_id": s, "plugin_id": "cbp-being"})
reqs = out.get("requests") or []
hits = [r for r in reqs if r.get("request_id") == RID]
print("cbp-being rows:", len(reqs), "| hit:", len(hits))
if hits:
    print(json.dumps(hits[0], indent=2, sort_keys=True, default=str))
else:
    # fall back: unfiltered, in case the asker seat differs
    out2 = hm.rpc(h, "hestia_scope_status", {"session_id": s})
    reqs2 = out2.get("requests") or []
    hits2 = [r for r in reqs2 if r.get("request_id") == RID]
    print("unfiltered rows:", len(reqs2), "| hit:", len(hits2))
    for r in hits2:
        print(json.dumps(r, indent=2, sort_keys=True, default=str))
