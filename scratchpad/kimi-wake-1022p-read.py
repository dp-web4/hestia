#!/usr/bin/env python3
"""Wake-1022p (notice 31219, review_request from claude-code): read
scope-0a748fa870b1 petition state + law hashes + recent peer-decide
precedent before deciding.
Pointer: hestia://scope/scope-0a748fa870b1#peer-decide"""
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
    for k in law:
        if k not in ("law_hash", "society_policy_hash"):
            v = json.dumps(law[k])
            print(f"law[{k}]:", v[:600])
else:
    print("law:", law)

print("now:", time.time(), time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

target = "scope-0a748fa870b1"
recent_decided = []
found = None
for pid in ("claude-code", "cbp-being", "kimi-code", "codex", "gemini", "sprout-being"):
    try:
        out = hm.rpc(h, "hestia_scope_status", {"plugin_id": pid})
    except Exception as e:
        print(pid, "ERR", e)
        continue
    reqs = out.get("requests", []) if isinstance(out, dict) else []
    for r in reqs:
        rid = r.get("request_id")
        if rid == target and found is None:
            found = (pid, r)
        if r.get("status") in ("approved", "refused") and r.get("decided_by"):
            recent_decided.append((pid, rid, r.get("status"), r.get("decided_by"),
                                   (r.get("act") or "")[:110]))

if found:
    pid, rec = found
    print(f"=== {target} FOUND under plugin_id {pid} ===")
    print(json.dumps(rec, indent=1))
else:
    print(f"=== {target} NOT FOUND in any queried plugin scope list ===")

print("=== recent decided rows (precedent scan) ===")
for row in recent_decided[:25]:
    print(row)
