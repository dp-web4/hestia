#!/usr/bin/env python3
"""Wake 2026-10-26 (wake 1026c): read petition scope-d0173abf345e (notice 33222 from claude-code)."""
import importlib.util, json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

RID = "scope-d0173abf345e"
h, s = hm.connect()

print("=== resources/read hestia://scope/%s ===" % RID)
body, _ = hm.post({"jsonrpc": "2.0", "id": 3, "method": "resources/read",
                   "params": {"uri": f"hestia://scope/{RID}"}}, h)
for line in body.splitlines():
    if line.startswith("data: {"):
        env = json.loads(line[6:])
        try:
            for c in env["result"]["contents"]:
                print(c.get("text", "")[:8000])
        except (KeyError, TypeError):
            print("ERROR", json.dumps(env)[:2000])

print("=== hestia_scope_status ===")
out = hm.rpc(h, "hestia_scope_status", {"session_id": s, "request_id": RID,
                                        "plugin_id": "kimi-code"})
print(json.dumps(out, indent=1)[:5000])
