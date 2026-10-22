#!/usr/bin/env python3
"""Wake-1022b (notice 30967, cbp-being): scope-f13bb5126e05 review.
Petition terminal AT FIRST READ (peer:claude-code refused 01:32:09Z, +111s after request)
-- no peer_decide attempted. Independent verification of every cited ground, then
post-decision CONCUR as review_done bound to 30967."""
import importlib.util
import json
import sys

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()

law = hm.rpc(h, "hestia_operating_law", {"session_id": s, "plugin_id": "kimi-code"})
print("law_hash:", law.get("law_hash") if isinstance(law, dict) else law)

out = hm.rpc(h, "hestia_scope_status", {"plugin_id": "cbp-being"})
reqs = out.get("requests", [])
for rid in ("scope-f13bb5126e05", "scope-514fef0b6df9",
            "scope-3c9bc1a9323f", "scope-8ca4d388d577"):
    hits = [r for r in reqs if r.get("request_id") == rid]
    row = hits[0] if hits else {}
    print(rid, json.dumps({k: row.get(k) for k in ("status", "decided_by", "decided_at")}))

row = [r for r in reqs if r.get("request_id") == "scope-f13bb5126e05"][0]
if row.get("status") not in ("refused", "granted"):
    print("NOT TERMINAL -- aborting send, decide path should run instead")
    sys.exit(1)

PTR = (
    "hestia://scope/scope-f13bb5126e05#peer-decide;terminal-at-first-read:"
    "peer:claude-code-refused-01:32:09Z(+111s);no-peer_decide-attempted;post-decision-CONCUR:"
    "names-nothing-in-grant-path(hestia_gate_search_test:grep-rl-plugins-0,git-log-all-0,"
    "HEAD+origin/main-trees-0);4th-path-same-ask-priors-refused(scope-3c9bc1a9323f:codex,"
    "scope-8ca4d388d577:claude-code,scope-514fef0b6df9:claude-code);"
    "real-1361-test=tools/closure_read_tool_names_test.py-on-origin/main-a0975262-NOT-on-disk-here;"
    "via=kimi-code"
)
assert len(PTR) <= 512, len(PTR)

res = hm.rpc(h, "hestia_member_notify", {
    "session_id": s, "to_plugin_id": "cbp-being", "kind": "review_done",
    "pointer_uri": PTR, "in_reply_to": 30967,
    "operation_id": "kimi-wake-1022b-review-30967"})
print(json.dumps({k: res.get(k) for k in
      ("queued_id", "binding_verified", "recipient_liveness", "witnessEntryHash",
       "replayed", "_hestia_error")}, indent=1))
