#!/usr/bin/env python3
"""Read scope request scope-bca00a3b1993 for review notice 29835."""
import importlib.util
import json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()
body, _ = hm.post({"jsonrpc": "2.0", "id": 7, "method": "resources/read",
                   "params": {"uri": "hestia://scope/scope-bca00a3b1993"}}, h)
for line in body.splitlines():
    if line.startswith("data: {"):
        env = json.loads(line[6:])
        print(json.dumps(env.get("result", env), indent=2))
        break

status = hm.rpc(h, "hestia_scope_status", {"session_id": s, "plugin_id": "kimi-code",
                                           "request_id": "scope-bca00a3b1993"})
print("status:", json.dumps(status, indent=2) if isinstance(status, dict) else status)

law = hm.rpc(h, "hestia_operating_law", {"session_id": s, "plugin_id": "kimi-code"})
print("law_hash:", law.get("law_hash") if isinstance(law, dict) else law)
