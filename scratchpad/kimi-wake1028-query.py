#!/usr/bin/env python3
"""Wake-1028: resolve the three pointers at issue (34078 new; 30834/30842 owed)."""
import importlib.util, json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()

for i, uri in enumerate([
    "hestia://scope/scope-3998fa643809",
    "hestia://scope/scope-8ca4d388d577",
    "hestia://escalation/7a44c3f80aa1d0ce",
]):
    body, _ = hm.post({"jsonrpc": "2.0", "id": 100 + i, "method": "resources/read",
                       "params": {"uri": uri}}, h)
    print(f"===== {uri} =====")
    for line in body.splitlines():
        if line.startswith("data: {"):
            env = json.loads(line[6:])
            print(json.dumps(env.get("result", env), indent=1)[:8000])
            break
    print()
