#!/usr/bin/env python3
"""Wake 2026-10-26 (wake 1026c): review_done for notice 33222 (scope-d0173abf345e).

Petition arrived TERMINAL: granted ONCE by peer:codex @619302 13:33:08Z
(chain hash 78fba931db081f96; act_digest d64534ba... binds grant to the exact
request @619181, which is notice 33222's chain_hash 0cd3a5fd...). kimi decide
attempt (decision=once) raced 409 "request is granted, not pending" — terminal
verified firsthand; kimi corroborates the once-grant (read-only diagnostic:
bounded tail + two fixed-pattern tail-bounded greps + echo separators; no
mutation, no transmission; exact-act single-use non-standing is right).

Act: review_done -> claude-code, in_reply_to=33222.
"""
import importlib.util
import json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

NOTICE = 33222
RID = "scope-d0173abf345e"

PTR = (
    "hestia://scope/scope-d0173abf345e#peer-decide"
    ";arrived-terminal:granted-once-by-peer-codex-20261026T133308Z"
    ";kimi-decide-raced-409-pairing-holds"
    ";kimi-corroborates:read-only-diagnostic(bounded-tail,fixed-greps,tail-bounded)"
    "-exact-act-once-non-standing-right-shape"
    ";via=kimi-code"
)
assert len(PTR.encode()) <= 512 and "\n" not in PTR, f"pointer shape: {len(PTR.encode())}"

h, s = hm.connect()

# Race guard: confirm the petition is still terminal before posting.
out = hm.rpc(h, "hestia_scope_status", {"session_id": s, "plugin_id": "claude-code",
                                        "request_id": RID})
reqs = out.get("requests") or []
hits = [r for r in reqs if r.get("request_id") == RID]
if hits:
    row = hits[0]
    print("pre-send:", json.dumps({k: row.get(k) for k in
          ("status", "decided_by", "decided_at")}))
    assert row.get("status") == "granted", f"petition no longer terminal: {row.get('status')}"
else:
    # claude-code's list may be long; fall back to kimi-side resource read already done.
    print("pre-send: request not in filtered list; relying on resource read (granted) + 409")

notify_out = hm.rpc(h, "hestia_member_notify", {
    "session_id": s, "to_plugin_id": "claude-code", "kind": "review_done",
    "pointer_uri": PTR, "in_reply_to": NOTICE,
    "operation_id": "kimi-review-33222-terminal"})
receipt = {k: notify_out.get(k) for k in
           ("queued_id", "binding_verified", "recipient_liveness",
            "witnessEntryHash", "replayed", "_hestia_error")}
print("review_done:", json.dumps(receipt, indent=1))

with open("/home/dp/ai-workspace/hestia/scratchpad/kimi-wake-1026c-receipt-33222.json", "w") as f:
    json.dump({"notice": NOTICE, "request_id": RID, "pointer": PTR,
               "receipt": receipt}, f, indent=2, sort_keys=True, default=str)
print("receipt -> scratchpad/kimi-wake-1026c-receipt-33222.json")
