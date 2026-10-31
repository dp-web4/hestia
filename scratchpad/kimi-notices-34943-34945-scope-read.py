#!/usr/bin/env python3
"""Read scope-909010e28035 and scope-fb1131e9e45f for review_requests 34943/34945 (from claude-code)."""
import importlib.util
import json
spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)
h, s = hm.connect()
for i, scope in enumerate(["scope-909010e28035", "scope-fb1131e9e45f"]):
    body, _ = hm.post({"jsonrpc": "2.0", "id": 100 + i, "method": "resources/read",
                       "params": {"uri": f"hestia://scope/{scope}"}}, h)
    print(f"===== {scope} =====")
    for line in body.splitlines():
        if line.startswith("data: {"):
            env = json.loads(line[6:])
            print(json.dumps(env.get("result", env), indent=2))
            break
