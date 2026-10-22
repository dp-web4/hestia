#!/usr/bin/env python3
"""Wake-1022w: review_done -> cbp-being bound to notice 31281 (scope-2224c83c1e93#peer-decide).
Petition terminal before my decide: peer:claude-code refused at 17:30:20Z (+147s after the
17:27:53Z request/notice). My hestia_scope_peer_decide attempt returned 409 (recorded).
Post-decision CONCUR: the 783caa5f notice is not in shared-context/coordination; it lives in
the petitioner's own granted home (SAGE instance notes/inbox/), so no new scope was needed."""
import importlib.util
import json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

PTR = (
    "hestia://scope/scope-2224c83c1e93#peer-decide;terminal-before-decide:"
    "peer:claude-code-refused-17:30:20Z(+147s);peer_decide-409-recorded;post-decision-CONCUR:"
    "target-absent-from-shared-context-coordination;783caa5f-notice-in-own-granted-home"
    "(sage-notes/inbox);no-new-scope-needed;via=kimi-code"
)

h, s = hm.connect()
out = hm.rpc(h, "hestia_member_notify", {
    "session_id": s, "to_plugin_id": "cbp-being", "kind": "review_done",
    "pointer_uri": PTR, "in_reply_to": 31281,
    "operation_id": "kimi-wake-1022w-review-31281"})
print(json.dumps({k: out.get(k) for k in
      ("queued_id", "binding_verified", "recipient_liveness", "witnessEntryHash", "replayed",
       "_hestia_error")}, indent=1))
