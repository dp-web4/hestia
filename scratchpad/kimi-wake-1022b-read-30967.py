#!/usr/bin/env python3
"""Wake-1022b (notice 30967, cbp-being): read scope-f13bb5126e05 petition state."""
import importlib.util
import json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()

law = hm.rpc(h, "hestia_operating_law", {"session_id": s, "plugin_id": "kimi-code"})
print("law_hash:", law.get("law_hash") if isinstance(law, dict) else law)

# The asker is not necessarily cbp-being; query several known members' scope lists.
for pid in ("cbp-being", "claude-code", "codex", "gemini", "kimi-code"):
    try:
        out = hm.rpc(h, "hestia_scope_status", {"plugin_id": pid})
    except Exception as e:
        print(pid, "ERR", e)
        continue
    reqs = out.get("requests", []) if isinstance(out, dict) else []
    hits = [r for r in reqs if r.get("request_id") == "scope-f13bb5126e05"]
    if hits:
        print("FOUND under plugin_id", pid)
        print(json.dumps(hits[0], indent=1))
        break
else:
    print("not found in any queried member's scope list; dumping counts")
    for pid in ("cbp-being", "claude-code", "codex"):
        out = hm.rpc(h, "hestia_scope_status", {"plugin_id": pid})
        reqs = out.get("requests", []) if isinstance(out, dict) else []
        print(pid, "requests:", len(reqs))
