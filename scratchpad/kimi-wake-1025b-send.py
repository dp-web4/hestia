#!/usr/bin/env python3
"""Wake-1025b continuation: send the 21 notices the 1025 wake never reached.

PLAN[38:58] = 20 review_done (the exact 20 ids in this wake's i_owe) and
PLAN[58] = the 32113 lapse-time correction (kind=reply per the marker).
PLAN and the correction/op-id rules are imported from kimi-wake-1025-send.py
verbatim — no re-transcription. Receipts append to the same jsonl.

Usage: kimi-wake-1025b-send.py
"""
import json, time, importlib.util

def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
    return m

hm = load("/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py", "hm")
orig = load("/home/dp/ai-workspace/hestia/scratchpad/kimi-wake-1025-send.py", "orig")

ITEMS = orig.PLAN[38:59]
assert len(ITEMS) == 21, len(ITEMS)

h, s = hm.connect()
receipts = open("/home/dp/ai-workspace/hestia/scratchpad/kimi-wake-1025-receipts.jsonl", "a")
sent = 0
for nid, to, ptr in ITEMS:
    assert len(ptr.encode()) <= 512 and "\n" not in ptr and "\r" not in ptr, (nid, len(ptr.encode()))
    correction = ";correction-to-kimi-" in ptr
    out = hm.rpc(h, "hestia_member_notify", {
        "session_id": s, "to_plugin_id": to,
        "kind": "reply" if correction else "review_done",
        "pointer_uri": ptr, "in_reply_to": nid,
        "operation_id": (f"kimi-wake-1025-fix-{nid}" if correction
                         else f"kimi-wake-1025-rd-{nid}")})
    rec = {k: out.get(k) for k in
           ("queued_id", "binding_verified", "recipient_liveness",
            "witnessEntryHash", "replayed", "unbound_notice")}
    err = out.get("_hestia_error") or out.get("error")
    row = {"nid": nid, "to": to, "ok": not err, "receipt": rec, "error": err}
    receipts.write(json.dumps(row) + "\n"); receipts.flush()
    if err:
        print(f"STOP nid={nid}: {json.dumps(err)[:300]}")
        receipts.close()
        raise SystemExit(4)
    sent += 1
    print(f"ok nid={nid} qid={rec.get('queued_id')} bind={rec.get('binding_verified')} live={rec.get('recipient_liveness')} wit={str(rec.get('witnessEntryHash'))[:12]}")
    time.sleep(0.25)
receipts.close()
print(f"continuation: sent {sent}/{len(ITEMS)}")
