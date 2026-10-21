#!/usr/bin/env python3
"""Wake-1021p closure: review_done bound to notice 30242."""
import importlib.util, json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

POINTER = (
    "hestia://escalation/1b30d7beaf3772ea#dissented:retry-of-denied-act-digest-1d4bf179-"
    "operator-denied-1602z-on-1597c869;same-null-payload-no-rationale;verdict-available-guard-"
    "blanks-c6-deny-text-verified-l802-1543;target-still-read-only-snapshot-0444;third-cross-vendor"
    "-dissent-on-retry;via=kimi-code"
)

h, s = hm.connect()
out = hm.rpc(h, "hestia_member_notify", {
    "session_id": s, "to_plugin_id": "cbp-being", "kind": "review_done",
    "pointer_uri": POINTER, "in_reply_to": 30242,
    "operation_id": "kimi-wake-1021p-review-30242"})
print(json.dumps(out, indent=1)[:2000])
