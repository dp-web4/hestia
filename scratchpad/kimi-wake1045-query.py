#!/usr/bin/env python3
"""Wake-1045: inspect scope request scope-93b1003f27d5 (peer-decide invitation, notice 34870)."""
import importlib.util, json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()

# 1. Resource read: hestia://scope/{request_id} resolves the request + decision record.
body, _ = hm.post({"jsonrpc": "2.0", "id": 7, "method": "resources/read",
                   "params": {"uri": "hestia://scope/scope-93b1003f27d5"}}, h)
for line in body.splitlines():
    if line.startswith("data: {"):
        env = json.loads(line[6:])
        print("=== resource read ===")
        print(json.dumps(env.get("result", env), indent=1)[:8000])
        break

# 2. Scope status tool view.
st = hm.rpc(h, "hestia_scope_status", {"session_id": s, "request_id": "scope-93b1003f27d5"})
print("=== scope_status ===")
print(json.dumps(st, indent=1)[:8000])
