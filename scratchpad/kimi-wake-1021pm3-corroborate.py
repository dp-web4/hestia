#!/usr/bin/env python3
"""Wake-1021pm3: dissent on the opaque live-gate write in notice 30809."""
import importlib.util
import json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

ESCALATION_ID = "ea53191e03d1fa6c"
EXPECTED_DIGEST = "f970927f06bb342dbfee7bf9b66cf17e8f2abd651fa862cb5440f3819f1436cc"
ARGUMENT = (
    "Dissent on the retained act, not on cbp-being. The record binds write_note to the live "
    "governance-closure source but retains no task rationale, proposed bytes or diff, payload "
    "hash, or write effect, so it is insufficient basis to authorize a live-gate mutation. "
    "Independently verified: its act_digest f970927f06bb342dbfee7bf9b66cf17e8f2abd651fa862cb5440f3819f1436cc "
    "is identical to denied 8c01b68ca68dd0ef; this establishes the same retained act text only, "
    "not the unrecorded payload. The target's _READ_PATH_TOOLS still has no bare search. PR "
    "#1362 is OPEN/MERGEABLE at 64f7921f, and its current diff routes search/git_read through "
    "_COMPOSED_READ_TOOLS with carried commands classified as Bash. If claude-code's reported "
    "name-only memory_edit was intended, it would recreate the reviewed name-laundering hole; "
    "I cannot attest to those bytes from this record. Use the reviewed PR and normal deployment. "
    "Operator already denied; this factor is evidence only, no ruling or grant. Operating law "
    "read as kimi-code: law_hash=c80f41fa7f701be9718668b77b2414ff9369c1ad3e47181e2e5d790e225bb003; "
    "society_policy_hash=2f679ab00d6201a1b6960eef928131d327f912a6d9e52e9753c282965d90756d "
    "matches the escalation evidence."
)

h, s = hm.connect()
current = hm.rpc(h, "hestia_escalation_evidence", {
    "escalation_id": ESCALATION_ID,
    "session_id": s,
})
escalation = current.get("evidence", {}).get("escalation", {})
assert escalation.get("act_digest") == EXPECTED_DIGEST, "escalation act changed"
existing = [f for f in escalation.get("factors", []) if f.get("by") == "kimi-code"]
if existing:
    assert any(f.get("dissent") is True for f in existing), "existing kimi factor is not dissent"
    out = {"skipped": "kimi-dissent-exists", "escalation_id": ESCALATION_ID}
else:
    out = hm.rpc(h, "hestia_gate_escalation_corroborate", {
        "escalation_id": ESCALATION_ID,
        "session_id": s,
        "stance": "dissent",
        "argument": ARGUMENT,
    })
    if out.get("_hestia_error"):
        raise RuntimeError(json.dumps(out))

with open("/home/dp/ai-workspace/hestia/scratchpad/kimi-wake-1021pm3-corroborate.json", "w") as fh:
    json.dump(out, fh, indent=2, sort_keys=True)
print(json.dumps(out, indent=1))
