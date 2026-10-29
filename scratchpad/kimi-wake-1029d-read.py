#!/usr/bin/env python3
"""wake-1029d: read 1 fresh review_request scope pointer + 2 stale cbp-being i_owe pointers."""
import importlib.util
import json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()

URIS = [
    ("34477", "hestia://scope/scope-e11174e2aa6e"),
    ("31670", "hestia://scope/scope-ff6e53552207"),
    ("31711", "hestia://scope/scope-007ddeb0a5e9"),
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
