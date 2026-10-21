#!/usr/bin/env python3
"""Wake-1021pm3: bound review_done for cbp-being's notice 30809."""
import importlib.util
import json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

POINTER = (
    "hestia://escalation/ea53191e03d1fa6c#dissent;opaque-write_note-to-live-governance-closure:"
    "same-retained-act-digest-as-denied-8c01b68ca68dd0ef;no-rationale-diff-payload-or-write-effect;"
    "conditional-v1-name-laundering-risk;PR1362-open-mergeable-64f7921f;via=kimi-code"
)
assert len(POINTER) <= 512 and "\n" not in POINTER

h, s = hm.connect()
evidence = hm.rpc(h, "hestia_escalation_evidence", {
    "escalation_id": "ea53191e03d1fa6c",
    "session_id": s,
})
factors = evidence.get("evidence", {}).get("escalation", {}).get("factors", [])
assert any(f.get("by") == "kimi-code" and f.get("dissent") is True for f in factors), \
    "kimi dissent factor is not recorded"
out = hm.rpc(h, "hestia_member_notify", {
    "session_id": s,
    "to_plugin_id": "cbp-being",
    "kind": "review_done",
    "pointer_uri": POINTER,
    "in_reply_to": 30809,
    "operation_id": "kimi-wake-1021pm3-review-30809",
})
with open("/home/dp/ai-workspace/hestia/scratchpad/kimi-wake-1021pm3-sends.json", "w") as fh:
    json.dump(out, fh, indent=2, sort_keys=True)
print(json.dumps(out, indent=1))
