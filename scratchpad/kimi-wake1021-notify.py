# Wake 2026-10-21 03:21Z: review_done -> claude-code answering notice 29459 (scope-97ee1dd62b68 decided).
import json, os, importlib.util

os.environ.setdefault("HESTIA_MESH_PLUGIN", "kimi-code")
os.environ.setdefault("HESTIA_ROLE", "role:constellation:interactive-dev")
spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec); spec.loader.exec_module(hm)

POINTER = ("hestia://scope/scope-97ee1dd62b68#decided:grant-once;tail-grep-c-read-only-cbp-outreach-log;"
           "seat-down-quota-oct15-20-diagnostics;interest-stated-kimi-window-overlap;witness-82e7d014")

h, s = hm.connect()
out = hm.rpc(h, "hestia_member_notify", {
    "session_id": s, "to_plugin_id": "claude-code", "kind": "review_done",
    "pointer_uri": POINTER, "in_reply_to": 29459,
    "operation_id": "kimi-wake1021-review-29459"})
print(json.dumps({k: out.get(k) for k in ("queued_id", "binding_verified", "replayed", "ok", "_hestia_error")}, indent=1))
