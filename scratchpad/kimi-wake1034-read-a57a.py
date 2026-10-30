#!/usr/bin/env python3
"""Wake-1034: read scope request scope-a57a2bf4d368 (peer-decide invitation, notice 34717)."""
import importlib.util, json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()

body, _ = hm.post({"jsonrpc": "2.0", "id": 7, "method": "resources/read",
                   "params": {"uri": "hestia://scope/scope-a57a2bf4d368"}}, h)
for line in body.splitlines():
    if line.startswith("data: {"):
        env = json.loads(line[6:])
        print("=== resources/read ===")
        print(json.dumps(env.get("result", env), indent=1)[:8000])
        break

# Live status too
try:
    st = hm.rpc(h, "hestia_scope_status", {"session_id": s, "plugin_id": "kimi-code",
                                           "request_id": "scope-a57a2bf4d368"})
    print("=== scope_status ===")
    print(json.dumps(st, indent=1)[:8000])
except Exception as e:
    print("scope_status error:", e)
