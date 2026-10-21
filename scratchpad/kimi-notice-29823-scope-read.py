#!/usr/bin/env python3
"""Read scope request scope-a2b7f8f9d490 for review notice 29823."""
import importlib.util
import json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()
body, _ = hm.post({"jsonrpc": "2.0", "id": 7, "method": "resources/read",
                   "params": {"uri": "hestia://scope/scope-a2b7f8f9d490"}}, h)
for line in body.splitlines():
    if line.startswith("data: {"):
        env = json.loads(line[6:])
        print(json.dumps(env.get("result", env), indent=2))
        break

law = hm.rpc(h, "hestia_operating_law", {"session_id": s, "plugin_id": "kimi-code"})
print("law_hash:", law.get("law_hash") if isinstance(law, dict) else law)
