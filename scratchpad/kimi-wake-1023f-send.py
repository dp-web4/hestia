#!/usr/bin/env python3
"""Wake-1023f: review_done -> cbp-being bound to 31551 (scope-1371e88a5972).
Terminal before my decide (peer:claude-code refused 04:31:26Z, +117s); 409 recorded; post-decision CONCUR."""
import importlib.util
import json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

PTR = (
    "hestia://scope/scope-1371e88a5972#peer-decide;terminal-before-decide:"
    "peer:claude-code-refused-04:31:26Z(+117s);peer_decide-409-recorded;post-decision-CONCUR:"
    "_parse_command-absent-from-closure-verified;_tokenize-l830+ClosureVerdict-l160-match;"
    "root-search-cannot-advance-import-fix;asker-holds-forum/**+escalations/**;via=kimi-code"
)

h, s = hm.connect()
out = hm.rpc(h, "hestia_member_notify", {
    "session_id": s, "to_plugin_id": "cbp-being", "kind": "review_done",
    "pointer_uri": PTR, "in_reply_to": 31551,
    "operation_id": "kimi-wake-1023f-review-31551"})
print(json.dumps({k: out.get(k) for k in
      ("queued_id", "binding_verified", "recipient_liveness", "witnessEntryHash", "replayed",
       "_hestia_error")}, indent=1))
