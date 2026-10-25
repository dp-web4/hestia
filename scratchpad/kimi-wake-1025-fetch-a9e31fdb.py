#!/usr/bin/env python3
"""Wake-1025: read escalation a9e31fdbc9c5bf8f via the hestia://escalation/ pointer resource
(chain-backed resolver, works after the live store has reaped the row)."""
import importlib.util, json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()
body, _ = hm.post({"jsonrpc": "2.0", "id": 9, "method": "resources/read",
                   "params": {"uri": "hestia://escalation/a9e31fdbc9c5bf8f"}}, h)
for line in body.splitlines():
    if not line.startswith("data: {"):
        continue
    env = json.loads(line[6:])
    print(json.dumps(env, indent=1))
