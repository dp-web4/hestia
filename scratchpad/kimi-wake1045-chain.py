#!/usr/bin/env python3
"""Wake-1045: find chain entries for scope-93b1003f27d5 (requested + refusal)."""
import importlib.util, json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()
d = hm.rpc(h, "hestia_query_history", {"session_id": s, "filter": {"limit": 500}})
entries = d.get("entries", [])
print(f"window: {len(entries)} entries")
for e in entries:
    blob = json.dumps(e)
    if "93b1003f27d5" in blob:
        print(json.dumps(e, indent=1))
        print("---")
