#!/usr/bin/env python3
"""Wake: list daemon tools + status of scope-3507a042e262, scope-7a1b0b922334."""
import importlib.util, json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()

# tools/list raw (rpc helper may wrap; try direct)
try:
    tools = hm.rpc(h, "tools/list", {})
    names = [t.get("name") for t in tools.get("tools", [])]
    print("TOOLS:", json.dumps(sorted(names)))
except Exception as e:
    print("tools/list failed:", e)

for rid in ("scope-3507a042e262", "scope-7a1b0b922334"):
    out = hm.rpc(h, "hestia_scope_status", {"session_id": s, "request_id": rid})
    print(f"\n=== {rid} ===")
    print(json.dumps(out, indent=1)[:3000])
