#!/usr/bin/env python3
"""Wake-1021z closure: review_done bound to notice 30412."""
import importlib.util, json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

POINTER = (
    "hestia://escalation/7555d99bc158d821#corroborated:read-only-search-of-own-governance-"
    "snapshot;false-positive-1361-still-unfixed-origin-l1707-deployed-l1223;deny-chain-pos-"
    "538769;intent-landed-19:54:41+19:55:10-via-read_file;patch_apply-self-apply-19:55:01-"
    "refused-no-worktree-separate-act;approval-correct-digest-2af2923d;via=kimi-code"
)

h, s = hm.connect()
out = hm.rpc(h, "hestia_member_notify", {
    "session_id": s, "to_plugin_id": "cbp-being", "kind": "review_done",
    "pointer_uri": POINTER, "in_reply_to": 30412,
    "operation_id": "kimi-wake-1021z-review-30412"})
print(json.dumps(out, indent=1))
