#!/usr/bin/env python3
"""Wake-1023g: consult operating law, record law_hash for the 44a62fb2 review."""
import importlib.util, json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()
out = hm.rpc(h, "hestia_operating_law", {"session_id": s})
print(json.dumps({k: v for k, v in out.items() if k != "law"}, indent=1))
print("rules:", len(out.get("law", [])))
