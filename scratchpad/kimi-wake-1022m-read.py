#!/usr/bin/env python3
"""Wake-1022m (notices 31167, 31169, claude-code): read scope-e53a47f396d4 and
scope-8e8b6d99991e petition state + law hashes."""
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

targets = {"scope-e53a47f396d4", "scope-8e8b6d99991e"}
found = {}
for pid in ("claude-code", "cbp-being", "codex", "gemini", "kimi-code"):
    try:
        out = hm.rpc(h, "hestia_scope_status", {"plugin_id": pid})
    except Exception as e:
        print(pid, "ERR", e)
        continue
    reqs = out.get("requests", []) if isinstance(out, dict) else []
    for r in reqs:
        rid = r.get("request_id")
        if rid in targets and rid not in found:
            found[rid] = (pid, r)
    if len(found) == len(targets):
        break

for rid in sorted(targets):
    if rid in found:
        pid, rec = found[rid]
        print(f"=== {rid} FOUND under plugin_id {pid} ===")
        print(json.dumps(rec, indent=1))
    else:
        print(f"=== {rid} NOT FOUND in any queried plugin scope list ===")
