#!/usr/bin/env python3
"""Wake-1023g: read escalation 44a62fb228a9db18 (notice 31561, cbp-being corroborate-or-dissent)."""
import importlib.util, json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()
out = hm.rpc(h, "hestia_escalation_evidence", {
    "session_id": s,
    "escalation_id": "44a62fb228a9db18",
})
print(json.dumps(out, indent=1))
