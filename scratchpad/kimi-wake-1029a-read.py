#!/usr/bin/env python3
"""wake-1029a: read the new notice's scope pointer + the 5 resurfaced i_owe pointers."""
import importlib.util
import json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()

URIS = [
    ("34307", "hestia://scope/scope-6dbd180a72fe"),
    ("31229", "hestia://scope/scope-d3b3450935d0"),
    ("31244", "hestia://scope/scope-b23080973614"),
    ("31252", "hestia://scope/scope-ebf13e56d4ce"),
    ("31281", "hestia://scope/scope-2224c83c1e93"),
    ("31304", "hestia://escalation/2073b86bd64e8cc4"),
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
