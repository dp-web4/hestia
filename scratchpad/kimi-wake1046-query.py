#!/usr/bin/env python3
"""Wake-1046: inspect the three cbp-being petitions from notices 34896/34899/34902."""
import importlib.util, json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()

for rid in ["scope-0bbe6e4be55a", "scope-4a95f370881c", "scope-aab8ec45db8d"]:
    print(f"########## {rid} ##########")
    body, _ = hm.post({"jsonrpc": "2.0", "id": 7, "method": "resources/read",
                       "params": {"uri": f"hestia://scope/{rid}"}}, h)
    for line in body.splitlines():
        if line.startswith("data: {"):
            env = json.loads(line[6:])
            print("=== resource read ===")
            print(json.dumps(env.get("result", env), indent=1)[:6000])
            break
    st = hm.rpc(h, "hestia_scope_status", {"session_id": s, "request_id": rid})
    print("=== scope_status ===")
    print(json.dumps(st, indent=1)[:6000])
