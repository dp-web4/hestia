#!/usr/bin/env python3
"""Wake-1022r: verify before ack of disposition 31234 (scope-24331fb84c77).
1. My petition row: status + decision_reason.
2. Peers' corrective claim: hestia_scope_status plugin_id=cbp-being shows
   scope-d3b3450935d0 (and the dup scope-f32c8c7aa88d) — no fs search needed."""
import importlib.util, json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()
out = {"mine": None, "cbp": []}
r = hm.rpc(h, "hestia_scope_status", {"session_id": s, "plugin_id": "kimi-code"})
for row in r.get("requests", []):
    if "24331fb84c77" in row.get("request_id", ""):
        out["mine"] = row
r2 = hm.rpc(h, "hestia_scope_status", {"session_id": s, "plugin_id": "cbp-being"})
for row in r2.get("requests", []):
    if any(k in row.get("request_id", "") for k in ("d3b3450935d0", "f32c8c7aa88d")):
        out["cbp"].append(row)
print(json.dumps(out, indent=1))
