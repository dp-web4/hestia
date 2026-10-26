#!/usr/bin/env python3
"""Wake 1026: resolve scope-ce6c124b6112 (notice 32986) — resource read + scope status."""
import importlib.util, json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

RID = "scope-ce6c124b6112"
h, s = hm.connect()

print("=== resources/read hestia://scope/%s ===" % RID)
body, _ = hm.post({"jsonrpc": "2.0", "id": 3, "method": "resources/read",
                   "params": {"uri": f"hestia://scope/{RID}"}}, h)
for line in body.splitlines():
    if line.startswith("data: {"):
        env = json.loads(line[6:])
        try:
            for c in env["result"]["contents"]:
                print(c.get("text", "")[:4000])
        except (KeyError, TypeError):
            print("ERROR", json.dumps(env)[:1500])

print("=== hestia_scope_status ===")
out = hm.rpc(h, "hestia_scope_status", {"session_id": s, "request_id": RID,
                                        "plugin_id": "kimi-code"})
print(json.dumps(out, indent=1)[:4000])
