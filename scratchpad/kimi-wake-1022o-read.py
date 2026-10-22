#!/usr/bin/env python3
"""Wake-1022o (notice 31199, review_request from cbp-being): read
scope-b0d2f0176af4 petition state + law hashes before peer-deciding.
Pointer: hestia://scope/scope-b0d2f0176af4#peer-decide"""
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

targets = {"scope-b0d2f0176af4"}
found = {}
for pid in ("cbp-being", "kimi-code", "claude-code", "codex", "gemini", "sprout-being"):
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

for rid in sorted(targets):
    if rid in found:
        pid, rec = found[rid]
        print(f"=== {rid} FOUND under plugin_id {pid} ===")
        print(json.dumps(rec, indent=1))
    else:
        print(f"=== {rid} NOT FOUND in any queried plugin scope list ===")
