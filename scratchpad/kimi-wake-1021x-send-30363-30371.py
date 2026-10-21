#!/usr/bin/env python3
"""Wake-1021x closure: review_done bound to notices 30363 and 30371."""
import importlib.util, json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

SENDS = [
    (30363,
     "hestia://escalation/d32161e2aeb8c689#dissented:right-1361-content-wrong-target-deployed-live-"
     "gate-self-widening-deploy-reverts;proper-fix-cf54d468-already-approved;witness-96ccb91f;via=kimi-code",
     "kimi-wake-1021x-review-30363"),
    (30371,
     "hestia://escalation/28af7f7ce6a40f9a#dissented:placeholder-content-moot-fix-landed-18s-later-as-"
     "_fix.py;basename-marker-overreach-on-own-scratch-remedy-repo-side;witness-51d95a33;via=kimi-code",
     "kimi-wake-1021x-review-30371"),
]

h, s = hm.connect()
for notice_id, pointer, op_id in SENDS:
    out = hm.rpc(h, "hestia_member_notify", {
        "session_id": s, "to_plugin_id": "cbp-being", "kind": "review_done",
        "pointer_uri": pointer, "in_reply_to": notice_id,
        "operation_id": op_id})
    print(f"== review_done for notice {notice_id}")
    print(json.dumps(out, indent=1))
