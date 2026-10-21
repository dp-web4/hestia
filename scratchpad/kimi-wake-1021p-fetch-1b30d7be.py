#!/usr/bin/env python3
"""Wake: read escalation 1b30d7beaf3772ea (notice 30242, cbp-being corroborate-or-dissent)."""
import importlib.util, json, sys

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()
out = hm.rpc(h, "hestia_escalation_evidence", {
    "session_id": s,
    "escalation_id": "1b30d7beaf3772ea",
})
print(json.dumps(out, indent=1))
