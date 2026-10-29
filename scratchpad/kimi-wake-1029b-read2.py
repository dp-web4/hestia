#!/usr/bin/env python3
"""wake-1029b: read the 2 resurfaced i_owe pointers (31551 scope, 31561 escalation)."""
import importlib.util
import json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()

URIS = [
    ("31551", "hestia://scope/scope-1371e88a5972"),
    ("31561", "hestia://escalation/44a62fb228a9db18"),
]

for nid, uri in URIS:
    body, _ = hm.post({"jsonrpc": "2.0", "id": 7, "method": "resources/read",
                       "params": {"uri": uri}}, h)
    print(f"===== notice {nid} {uri}")
    for line in body.splitlines():
        if line.startswith("data: {"):
            env = json.loads(line[6:])
            print(json.dumps(env.get("result", env), indent=1))
            break
