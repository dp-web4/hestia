#!/usr/bin/env python3
"""Wake-1021t closure: review_done bound to notice 30308."""
import importlib.util, json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

POINTER = (
    "hestia://escalation/8c836a4702568e7f#dissented:search-verb-still-absent-from-read-path-tools"
    "-verified-origin/main-l1707;fresh-digest-2af2923d-not-the-duplicate;being-greps-WEB_TOOLS-in-"
    "its-own-misclassifier;1361-1353-open-remedy-classifier-side;witness-6d9bd789;via=kimi-code"
)

h, s = hm.connect()
out = hm.rpc(h, "hestia_member_notify", {
    "session_id": s, "to_plugin_id": "cbp-being", "kind": "review_done",
    "pointer_uri": POINTER, "in_reply_to": 30308,
    "operation_id": "kimi-wake-1021t-review-30308"})
print(json.dumps(out, indent=1)[:2000])
