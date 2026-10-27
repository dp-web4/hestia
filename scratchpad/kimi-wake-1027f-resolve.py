#!/usr/bin/env python3
"""Resolve the three pointers in play for wake-1027f:

1. hestia://escalation/acd6a25ffd91d644  (notice 33569, review_request from claude-code)
2. hestia://scope/scope-051054346456     (notice 29127, i_owe review_request from cbp-being)
3. hestia://scope/scope-d46d6da535da     (notices 33593/33595/33597 cluster)
plus hestia_scope_status for kimi-code (was d46d6da535da mine? a disposition
is minted to the petitioner the record names) and cbp-being (petition context).
"""
import importlib.util
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "tools"))
from claude_daemon_client import call  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)
h, s = hm.connect()

URIS = [
    ("33569 escalation", "hestia://escalation/acd6a25ffd91d644"),
    ("29127 scope", "hestia://scope/scope-051054346456"),
    ("d46d cluster scope", "hestia://scope/scope-d46d6da535da"),
]
for label, uri in URIS:
    print(f"===== {label}: {uri}")
    body, _ = hm.post({"jsonrpc": "2.0", "id": 7, "method": "resources/read",
                       "params": {"uri": uri}}, h)
    for line in body.splitlines():
        if line.startswith("data: {"):
            env = json.loads(line[6:])
            print(json.dumps(env.get("result", env), indent=2)[:4000])
            break
    print()

for pid in ("kimi-code", "cbp-being"):
    print(f"===== hestia_scope_status plugin_id={pid}")
    try:
        st = call("hestia_scope_status", {"plugin_id": pid})
    except Exception as e:
        print(f"  call failed: {e}")
        continue
    reqs = st.get("requests", []) if isinstance(st, dict) else []
    print(f"  requests held: {len(reqs)}")
    for r in reqs:
        rid = r.get("request_id", "?")
        if rid in ("scope-051054346456", "scope-d46d6da535da", "scope-d4838745c6df"):
            print(f"  --- {rid}")
            for k in ("status", "path", "reason", "decided_by", "decided_at",
                      "decision_reason", "origin", "act", "grant_path", "recursive"):
                v = r.get(k)
                if v is not None:
                    print(f"    {k}: {str(v)[:400]}")
