#!/usr/bin/env python3
"""Wake 2026-10-31: peer-decide attempts on scope-909010e28035 + scope-fb1131e9e45f
(notices 34943/34945 from claude-code). Both arrived already terminal (refused by
peer:codex at chain 676920/676928, +94s/+97s). Attempting refuse anyway puts
kimi-side terminality on record; expected result is 409 'not pending'."""
import json, importlib.util
spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)
h, s = hm.connect()

REASON = ("kimi-code corroborates refusal: gate auto-opened standing rwed "
          "(once:false) for a read-only compound (ls -la + grep -rl) spanning 4 "
          "paths while each petition covers 1; no purpose stated; and the "
          "requester itself reports the fact was obtained another way and asks "
          "for refusal. No scope is needed for this task.")
for rid in ["scope-909010e28035", "scope-fb1131e9e45f"]:
    out = hm.rpc(h, "hestia_scope_peer_decide",
                 {"session_id": s, "request_id": rid,
                  "decision": "refuse", "reason": REASON, "recursive": False})
    print(f"== {rid} ==")
    print(json.dumps(out, indent=1)[:800])
