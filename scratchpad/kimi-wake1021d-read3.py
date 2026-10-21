#!/usr/bin/env python3
"""Wake-1021d: read the three pending review targets (notices 30061, 30070, 30078)."""
import importlib.util, json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

URIS = [
    "hestia://scope/scope-080fa3da6076",
    "hestia://escalation/8356ac78c8cb1b6c",
    "hestia://escalation/69c418faf108787a",
]

h, s = hm.connect()
for uri in URIS:
    print("=" * 20, uri)
    body, _ = hm.post({"jsonrpc": "2.0", "id": 7, "method": "resources/read",
                       "params": {"uri": uri}}, h)
    for line in body.splitlines():
        if line.startswith("data: {"):
            env = json.loads(line[6:])
            print(json.dumps(env.get("result", env), indent=1))
            break
