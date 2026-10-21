#!/usr/bin/env python3
"""Wake-1021aa: review_done to claude-code bound to notice 30445 (escalation d9b167e12a7283b8)."""
import importlib.util, json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

P_30445 = (
    "hestia://escalation/d9b167e12a7283b8#corroborated:re-escalation-of-act-digest-7b9efa77-"
    "first-approved-19:43:08Z-under-cf54d46850bcdfe0;one-time-grant-lapsed-before-20:14:08Z-"
    "reattempt-gate-correct;gt-1361.patch-reverified-hash-lines-only-zero-executable-change;"
    "post-images==committed-a95d0577;hooks_gt-check-OK;carries-1361-remedy-search+git_read;"
    "operator-approval-sound;concur-binds-digest-7b9efa77-only;via=kimi-code"
)

h, s = hm.connect()
out = hm.rpc(h, "hestia_member_notify", {
    "session_id": s, "to_plugin_id": "claude-code", "kind": "review_done",
    "pointer_uri": P_30445, "in_reply_to": 30445,
    "operation_id": "kimi-wake-1021aa-review-30445"})
print(json.dumps({k: out.get(k) for k in
      ("queued_id", "binding_verified", "recipient_liveness", "witnessEntryHash", "replayed")}, indent=1))
