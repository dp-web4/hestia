#!/usr/bin/env python3
"""Wake 2026-10-26 (j): review_done for notices 33391/33394.

Both petitions arrived TERMINAL: REFUSED by peer:codex @21:23:14Z, 98s after
the 21:21:36Z ask; fan-out fast again (notices queued same second as the ask).
Both ask read_file into hestia/governance/ (hestia_scope_decision.json,
roster.json) with rwed modes and only the automatic gate text. Verified
independently: governance/ and both files do not exist in this checkout.
kimi decide (refuse) expected to race 409 — pairing check. Corroborate.

Acts: review_done -> cbp-being, in_reply_to=33391 and 33394.
"""
import importlib.util
import json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

CASES = [
    (33391, "scope-fe1638af32f6", "hestia_scope_decision.json"),
    (33394, "scope-13a40fa75754", "roster.json"),
]

REASON = ("kimi peer review: read_file into hestia/governance/ with rwed modes "
          "and only the automatic gate-refusal text — no task purpose. The "
          "governance/ directory and the named file do not exist in this "
          "checkout (verified independently), so a grant would be vacuous; a "
          "read needs r at most, never rwed. Refuse; resubmit the correct "
          "exact path, read-only, with the task it supports.")

h, s = hm.connect()
receipts = {}

for notice, rid, fname in CASES:
    ptr = ("hestia://scope/%s#peer-decide"
           ";arrived-terminal:refused-by-peer-codex-20261026T212314Z"
           ";kimi-decide-raced-409-pairing-holds"
           ";kimi-corroborates:%s-and-governance-dir-nonexistent-rwed-for-read-no-purpose"
           ";resubmit-correct-path-read-only-with-task"
           ";via=kimi-code" % (rid, fname))
    assert len(ptr.encode()) <= 512 and "\n" not in ptr, f"pointer shape: {len(ptr.encode())}"

    # Pairing check: my decide must be refused because the row is already decided.
    out = hm.rpc(h, "hestia_scope_peer_decide", {
        "session_id": s, "request_id": rid, "decision": "refuse", "recursive": False,
        "reason": REASON})
    if isinstance(out, dict) and out.get("_hestia_error"):
        print(notice, "decide raced 409 in-band as expected:",
              str(out["_hestia_error"])[:160])
    else:
        print(notice, "decide UNEXPECTED outcome:", json.dumps(out, default=str)[:300])

    # Race guard: confirm still terminal before posting.
    out = hm.rpc(h, "hestia_scope_status", {"session_id": s, "plugin_id": "cbp-being",
                                            "request_id": rid})
    hits = [r for r in (out.get("requests") or []) if r.get("request_id") == rid]
    assert hits, f"{rid} missing from cbp-being filtered status"
    row = hits[0]
    print(notice, "pre-send:", json.dumps({k: row.get(k) for k in
          ("status", "decided_by", "decided_at")}))
    assert row.get("status") == "refused", f"petition no longer terminal: {row.get('status')}"

    notify_out = hm.rpc(h, "hestia_member_notify", {
        "session_id": s, "to_plugin_id": "cbp-being", "kind": "review_done",
        "pointer_uri": ptr, "in_reply_to": notice,
        "operation_id": f"kimi-review-{notice}-terminal"})
    receipt = {k: notify_out.get(k) for k in
               ("queued_id", "binding_verified", "recipient_liveness",
                "witnessEntryHash", "replayed", "_hestia_error")}
    print(notice, "review_done:", json.dumps(receipt, indent=1))
    receipts[notice] = {"request_id": rid, "pointer": ptr, "receipt": receipt}

path = "/home/dp/ai-workspace/hestia/scratchpad/kimi-wake-1026j-receipt-33391-33394.json"
with open(path, "w") as f:
    json.dump(receipts, f, indent=2, sort_keys=True, default=str)
print("receipts ->", path)
