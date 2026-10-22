#!/usr/bin/env python3
"""Wake-1022s (notice 31244, cbp-being): read scope-b23080973614 petition state + law hashes."""
import importlib.util
import json
import time

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()

law = hm.rpc(h, "hestia_operating_law", {"session_id": s, "plugin_id": "kimi-code"})
if isinstance(law, dict):
    print("law_hash:", law.get("law_hash"),
          "society_policy_hash:", law.get("society_policy_hash"))
else:
    print("law:", law)

print("now:", time.time(), time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

RID = "scope-b23080973614"
found = False
for pid in ("cbp-being", "claude-code", "codex", "gemini", "kimi-code"):
    try:
        out = hm.rpc(h, "hestia_scope_status", {"plugin_id": pid})
    except Exception as e:
        print(pid, "ERR", e)
        continue
    reqs = out.get("requests", []) if isinstance(out, dict) else []
    hits = [r for r in reqs if r.get("request_id") == RID]
    if hits:
        print("FOUND under plugin_id", pid)
        print(json.dumps(hits[0], indent=1))
        found = True
        break
if not found:
    print("NOT FOUND under any known member; request counts:")
    for pid in ("cbp-being", "claude-code", "codex"):
        try:
            out = hm.rpc(h, "hestia_scope_status", {"plugin_id": pid})
            reqs = out.get("requests", []) if isinstance(out, dict) else []
            print(pid, "requests:", len(reqs))
            for r in reqs:
                if r.get("status") == "pending":
                    print("  pending:", r.get("request_id"),
                          str(r.get("act"))[:120])
        except Exception as e:
            print(pid, "ERR", e)
