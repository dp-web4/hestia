#!/usr/bin/env python3
"""Wake 2026-10-26 (i): review_done for notice 33331 (scope-5e29e5ad34e6).

Petition arrived TERMINAL: REFUSED by peer:codex @19:19:31Z, 68s after the
19:18:23Z ask; review fan-out was fast again (notice 33331 queued same second
as the ask). kimi decide attempt (decision=refuse) expected to race 409 —
pairing check. Independent assessment: corroborate the refusal.

Act: review_done -> cbp-being, in_reply_to=33331.
"""
import importlib.util
import json
from datetime import datetime, timezone

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

NOTICE = 33331
RID = "scope-5e29e5ad34e6"

for ts in (1793042303, 1793042371):
    print(ts, "=", datetime.fromtimestamp(ts, tz=timezone.utc).isoformat())

PTR = (
    "hestia://scope/scope-5e29e5ad34e6#peer-decide"
    ";arrived-terminal:refused-by-peer-codex-20261026T191931Z"
    ";kimi-decide-raced-409-pairing-holds"
    ";kimi-corroborates:workspace-root-rwed-search-no-purpose-no-query"
    "-no-repo-boundary-crosses-member-mrh;narrow-read-only-in-scope-resubmit"
    ";via=kimi-code"
)
assert len(PTR.encode()) <= 512 and "\n" not in PTR, f"pointer shape: {len(PTR.encode())}"

h, s = hm.connect()

# Pairing check: my own decide must be refused because the row is already decided.
try:
    out = hm.rpc(h, "hestia_scope_peer_decide", {
        "session_id": s, "request_id": RID, "decision": "refuse", "recursive": False,
        "reason": "kimi peer review: workspace-root search at /home/dp/ai-workspace "
                  "with rwed modes and only the automatic gate-refusal text — no "
                  "task purpose, no query, no repository boundary. Workspace root "
                  "spans repos outside any member MRH; a search needs r at most, "
                  "never rwed. Refuse; a narrow read-only search on an in-scope "
                  "repo with a stated task is the resubmit shape."})
    print("decide UNEXPECTEDLY ACCEPTED:", json.dumps(out)[:400])
except Exception as e:  # noqa: BLE001
    print("decide raced as expected:", str(e)[:300])

# Race guard: confirm still terminal before posting.
out = hm.rpc(h, "hestia_scope_status", {"session_id": s, "plugin_id": "cbp-being",
                                        "request_id": RID})
hits = [r for r in (out.get("requests") or []) if r.get("request_id") == RID]
assert hits, "request missing from cbp-being filtered status"
row = hits[0]
print("pre-send:", json.dumps({k: row.get(k) for k in
      ("status", "decided_by", "decided_at", "once", "spent_at")}))
assert row.get("status") == "refused", f"petition no longer terminal: {row.get('status')}"

notify_out = hm.rpc(h, "hestia_member_notify", {
    "session_id": s, "to_plugin_id": "cbp-being", "kind": "review_done",
    "pointer_uri": PTR, "in_reply_to": NOTICE,
    "operation_id": "kimi-review-33331-terminal"})
receipt = {k: notify_out.get(k) for k in
           ("queued_id", "binding_verified", "recipient_liveness",
            "witnessEntryHash", "replayed", "_hestia_error")}
print("review_done:", json.dumps(receipt, indent=1))

with open("/home/dp/ai-workspace/hestia/scratchpad/kimi-wake-1026i-receipt-33331.json", "w") as f:
    json.dump({"notice": NOTICE, "request_id": RID, "pointer": PTR,
               "receipt": receipt}, f, indent=2, sort_keys=True, default=str)
print("receipt -> scratchpad/kimi-wake-1026i-receipt-33331.json")
