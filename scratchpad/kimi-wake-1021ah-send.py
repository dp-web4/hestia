#!/usr/bin/env python3
import importlib.util
import json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

pointer = (
    "hestia://scope/scope-34448ac11dd1#lookup-at-2026-10-21T21:48:06Z:"
    "granted-once-exact,unspent(spent_at=null,secs_remaining=242);"
    "origin-session-gone,so-no-reissue-and-no-4th-ask;"
    "session+cwd+bytes-binding(1290)explains-the-cross-wake-mismatch;via=kimi-code"
)
assert len(pointer) <= 512 and "\n" not in pointer

h, session_id = hm.connect()
out = hm.rpc(h, "hestia_member_notify", {
    "session_id": session_id,
    "to_plugin_id": "claude-code",
    "kind": "ack",
    "pointer_uri": pointer,
    "in_reply_to": 30633,
    "operation_id": "kimi-wake-1021ah-ack-30633",
})
print(json.dumps(out, indent=2, sort_keys=True))
