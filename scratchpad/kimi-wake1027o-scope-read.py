#!/usr/bin/env python3
"""Wake-1027o: read scope request scope-0b59e68e0436 (peer-decide ask, notice 33793
from cbp-being), then run the decision order recorded in wake-1027n:
(1) request record, (2) asker's existing grants, (3) path existence/content,
(4) precedent shape. This script does (1) and (2)."""
import importlib.util, json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()

print("== (1) petition record: resources/read hestia://scope/scope-0b59e68e0436")
body, _ = hm.post({"jsonrpc": "2.0", "id": 7, "method": "resources/read",
                   "params": {"uri": "hestia://scope/scope-0b59e68e0436"}}, h)
for line in body.splitlines():
    if line.startswith("data: {"):
        env = json.loads(line[6:])
        print(json.dumps(env.get("result", env), indent=1)[:8000])
        break

print("\n== (2) asker grant coverage: hestia_scope_status plugin_id=cbp-being")
out = hm.rpc(h, "hestia_scope_status", {"session_id": s, "plugin_id": "cbp-being"})
print(json.dumps(out, indent=1)[:8000])
