#!/usr/bin/env python3
"""wake-1029c: read 3 new review_request scope pointers + 1 stale cbp-being i_owe pointer."""
import importlib.util
import json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()

URIS = [
    ("34387", "hestia://scope/scope-5eb1688605dc"),
    ("34389", "hestia://scope/scope-0bee29d1b34c"),
    ("34423", "hestia://scope/scope-780638ccaa8b"),
    ("31600", "hestia://scope/scope-8350b0321e23"),
]

for nid, uri in URIS:
    body, _ = hm.post({"jsonrpc": "2.0", "id": 7, "method": "resources/read",
                       "params": {"uri": uri}}, h)
    print(f"===== notice {nid} {uri}")
    found = False
    for line in body.splitlines():
        if line.startswith("data: {"):
            env = json.loads(line[6:])
            print(json.dumps(env.get("result", env), indent=1))
            found = True
            break
    if not found:
        print(body[:2000])
