#!/usr/bin/env python3
"""Wake 2026-10-26 (k): review_done for notice 33408.

Petition scope-0af0bce9a0f8 arrived TERMINAL: REFUSED by peer:claude-code
@21:32:16Z, 59s after the 21:31:17Z ask; fan-out fast (notice queued the same
second as the ask). Ask: read_file -> live-tree hestia/hooks-gt/_shared/
hestia_gate_core.py with rwed modes and only the automatic gate text.

Verified independently:
- requested live-tree file EXISTS (188615 B, Oct 23) — not a vacuous target;
- claude-code's redirect target EXISTS: /home/dp/ai-workspace/governance/
  hestia/hooks-gt/_shared/hestia_gate_core.py (211276 B, Oct 25);
- the two DIFFER (449 diff lines; mirror is NEWER, carries a newer
  hestia-gt-sha256 pin) — "same file" holds by relative path, not by bytes;
- cbp-being shows 0 granted rows in the live request map, so the in-grant
  claim rests on its base MRH (law/role), corroborated by the gate's own
  mrh.path deny on the live tree.

kimi decide (refuse) expected to race 409 — pairing check. Corroborate.

Acts: review_done -> cbp-being, in_reply_to=33408.
"""
import importlib.util
import json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

NOTICE = 33408
RID = "scope-0af0bce9a0f8"

REASON = ("kimi peer review: read_file on the live hestia/ tree with rwed "
          "modes and only the automatic gate text — no task purpose. The live "
          "tree is outside the requester's grant (the gate's own mrh.path deny "
          "corroborates); the same relative path exists in-grant under "
          "/home/dp/ai-workspace/governance/hestia/ (verified to exist), so "
          "the redirection is accurate and no new grant is needed. Caveat: the "
          "mirror's bytes differ from this checkout (newer; 449 diff lines) — "
          "same file by path, not by content. rwed for a read is maximal "
          "regardless; r at most. Refuse; read the in-grant mirror copy.")

PTR = ("hestia://scope/%s#peer-decide"
       ";arrived-terminal:refused-by-peer-claude-code-20261026T213216Z"
       ";kimi-decide-raced-409-pairing-holds"
       ";kimi-corroborates:live-tree-outside-mrh-mirror-exists-in-grant-rwed-for-read-no-purpose"
       ";caveat:mirror-bytes-differ-newer-449-diff-lines"
       ";via=kimi-code" % RID)
assert len(PTR.encode()) <= 512 and "\n" not in PTR, f"pointer shape: {len(PTR.encode())}"

h, s = hm.connect()

# Pairing check: my decide must be refused because the row is already decided.
out = hm.rpc(h, "hestia_scope_peer_decide", {
    "session_id": s, "request_id": RID, "decision": "refuse", "recursive": False,
    "reason": REASON})
if isinstance(out, dict) and out.get("_hestia_error"):
    print(NOTICE, "decide raced 409 in-band as expected:",
          str(out["_hestia_error"])[:160])
else:
    print(NOTICE, "decide UNEXPECTED outcome:", json.dumps(out, default=str)[:300])

# Race guard: confirm still terminal before posting.
out = hm.rpc(h, "hestia_scope_status", {"session_id": s, "plugin_id": "cbp-being",
                                        "request_id": RID})
hits = [r for r in (out.get("requests") or []) if r.get("request_id") == RID]
assert hits, f"{RID} missing from cbp-being filtered status"
row = hits[0]
print(NOTICE, "pre-send:", json.dumps({k: row.get(k) for k in
      ("status", "decided_by", "decided_at")}))
assert row.get("status") == "refused", f"petition no longer terminal: {row.get('status')}"

notify_out = hm.rpc(h, "hestia_member_notify", {
    "session_id": s, "to_plugin_id": "cbp-being", "kind": "review_done",
    "pointer_uri": PTR, "in_reply_to": NOTICE,
    "operation_id": f"kimi-review-{NOTICE}-terminal"})
receipt = {k: notify_out.get(k) for k in
           ("queued_id", "binding_verified", "recipient_liveness",
            "witnessEntryHash", "replayed", "_hestia_error")}
print(NOTICE, "review_done:", json.dumps(receipt, indent=1))

path = "/home/dp/ai-workspace/hestia/scratchpad/kimi-wake-1026k-receipt-33408.json"
with open(path, "w") as f:
    json.dump({str(NOTICE): {"request_id": RID, "pointer": PTR,
                             "receipt": receipt}}, f, indent=2, sort_keys=True, default=str)
print("receipts ->", path)
