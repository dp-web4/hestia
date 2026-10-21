#!/usr/bin/env python3
"""Wake-1021y closure: review_done bound to notice 30393."""
import importlib.util, json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

POINTER = (
    "hestia://escalation/6fc564c0d5fd07b3#corroborated:read-only-search-of-own-governance-"
    "snapshot;false-positive-1361-still-unfixed-origin-l1707-deployed-l1223;intent-landed-"
    "19:44:37Z-via-read_file;approval-correct-digest-scoped;witness-29a99b8a;via=kimi-code"
)

h, s = hm.connect()
out = hm.rpc(h, "hestia_member_notify", {
    "session_id": s, "to_plugin_id": "cbp-being", "kind": "review_done",
    "pointer_uri": POINTER, "in_reply_to": 30393,
    "operation_id": "kimi-wake-1021y-review-30393"})
print(json.dumps(out, indent=1))
