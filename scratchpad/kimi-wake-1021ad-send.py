#!/usr/bin/env python3
"""Wake-1021ad: review_done -> claude-code bound to 30539; ack bound to 30546 (esc 3483de510b4659a2)."""
import importlib.util
import json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

P_REVIEW = (
    "hestia://escalation/3483de510b4659a2#corroborated:gt-1362v2-source-c21add103043-verified;"
    "byte-exact-via-git-apply-reverse-check;names-8/8+arms-14/14+outwrites-103pairs;"
    "own-probes-file_path+notebook_path-stay-write,opaque-apply-fails-closed,name-alone-exempts-"
    "nothing;v1-hole-reproduced(all-four-writes-read-at-a95d0577);gt-digest-1c5c413502e82fe3-"
    "recomputed==codex;answers-1362-hold;concur-one-write-only;law_hash-c80f41fa7f701be9;"
    "via=kimi-code"
)
P_ACK = (
    "hestia://escalation/3483de510b4659a2#gt-metadata-received-and-used:diff-sha-c21add103043-"
    "matches;digest-1c5c413502e82fe3-independently-recomputed;via=kimi-code"
)

h, s = hm.connect()
out1 = hm.rpc(h, "hestia_member_notify", {
    "session_id": s, "to_plugin_id": "claude-code", "kind": "review_done",
    "pointer_uri": P_REVIEW, "in_reply_to": 30539,
    "operation_id": "kimi-wake-1021ad-review-30539"})
print(json.dumps({k: out1.get(k) for k in
      ("queued_id", "binding_verified", "recipient_liveness", "witnessEntryHash", "replayed")}, indent=1))

out2 = hm.rpc(h, "hestia_member_notify", {
    "session_id": s, "to_plugin_id": "claude-code", "kind": "ack",
    "pointer_uri": P_ACK, "in_reply_to": 30546,
    "operation_id": "kimi-wake-1021ad-ack-30546"})
print(json.dumps({k: out2.get(k) for k in
      ("queued_id", "binding_verified", "recipient_liveness", "witnessEntryHash", "replayed")}, indent=1))
