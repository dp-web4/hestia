#!/usr/bin/env python3
"""Wake-1023a: read scope-98cb3216c414 + scope-8219906e2d40 (notices 31490/31493, cbp-being)."""
import importlib.util
import json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()

TARGETS = ("scope-98cb3216c414", "scope-8219906e2d40")
found = {}
for pid in ("cbp-being", "kimi-code", "claude-code", "codex"):
    try:
        out = hm.rpc(h, "hestia_scope_status", {"plugin_id": pid})
    except Exception as e:
        print(pid, "ERR", e)
        continue
    reqs = out.get("requests", []) if isinstance(out, dict) else []
    for r in reqs:
        if r.get("request_id") in TARGETS:
            found.setdefault(r["request_id"], []).append((pid, r))

for t in TARGETS:
    print("=" * 20, t)
    if t not in found:
        print("NOT FOUND in any queried member's scope list")
    for pid, r in found[t]:
        print("under plugin_id:", pid)
        print(json.dumps(r, indent=1))
