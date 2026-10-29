#!/usr/bin/env python3
"""wake-1029b: read 4 new claude-code scope pointers + 3 stale cbp-being i_owe pointers."""
import importlib.util
import json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()

URIS = [
    ("34367", "hestia://scope/scope-cf8a99a0a716"),
    ("34369", "hestia://scope/scope-96cd9212413d"),
    ("34371", "hestia://scope/scope-a4c9c1919400"),
    ("34373", "hestia://scope/scope-8241585a308b"),
    ("31490", "hestia://scope/scope-98cb3216c414"),
    ("31493", "hestia://scope/scope-8219906e2d40"),
    ("31504", "hestia://scope/scope-b86e2a212f22"),
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
