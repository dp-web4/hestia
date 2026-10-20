#!/usr/bin/env python3
"""Batch v3: finish the reap v2 started. Remaining = primer i_owe minus ids with
ok=true in the v2 jsonl (v2 was stopped to free rate budget for fresh sends 29284/29286).
Same pointer text and operation-id scheme so any overlap dedupes at the daemon.
Appends v3 rows to the same jsonl."""
import json, os, time, importlib.util

os.environ.setdefault("HESTIA_MESH_PLUGIN", "kimi-code")
os.environ.setdefault("HESTIA_ROLE", "role:constellation:interactive-dev")
spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec); spec.loader.exec_module(hm)

PRIMER = "/home/dp/.kimi-code/hestia-mesh-primers/notice-147ONB.json"
LOG = "/home/dp/ai-workspace/hestia/scratchpad/kimi-stale-replies-20261020.jsonl"
PACE_SECS = 25
RATE_BACKOFF = 150

done = set()
for line in open(LOG):
    try:
        rec = json.loads(line)
    except Exception:
        continue
    if rec.get("ok") or rec.get("replayed"):
        done.add(rec.get("id"))

rows = [r for r in json.load(open(PRIMER))["unanswered"]["i_owe"] if r["id"] not in done]
print(f"v3 remaining: {len(rows)}", flush=True)
log = open(LOG, "a")

def note(rec):
    rec["v"] = 3
    log.write(json.dumps(rec) + "\n"); log.flush()

h_s = [None, None]
ok = bad = 0
for i, row in enumerate(rows):
    base, _, frag = row["pointer_uri"].partition("#")
    args = {"to_plugin_id": row["from_plugin"], "kind": "reply",
            "pointer_uri": f"{base}#{frag};window-missed:seat-down-quota-oct15-20;via=kimi-code",
            "in_reply_to": int(row["id"]),
            "operation_id": f"kimi-stale-{row['id']}-20261020"}
    sent = False
    for attempt in range(9):
        try:
            if h_s[0] is None:
                h_s[0], h_s[1] = hm.connect()
            out = hm.rpc(h_s[0], "hestia_member_notify", dict(args, session_id=h_s[1]))
        except Exception as e:
            note({"id": row["id"], "attempt": attempt, "exc": repr(e)})
            h_s[0] = None; time.sleep(30); continue
        if not hm.failed(out):
            note({"id": row["id"], "to": row["from_plugin"], "queued_id": out.get("queued_id"),
                  "binding_verified": out.get("binding_verified"),
                  "replayed": out.get("replayed"), "ok": True})
            ok += 1; sent = True; break
        code = (out.get("_hestia_error") or {}).get("code", "?")
        note({"id": row["id"], "attempt": attempt, "refused": code})
        if "rate_limited" in code:
            time.sleep(RATE_BACKOFF); continue
        break
    if not sent:
        bad += 1
    if (i + 1) % 10 == 0:
        print(f"[{time.strftime('%H:%M:%S')}] {i+1}/{len(rows)} ok={ok} bad={bad}", flush=True)
    time.sleep(PACE_SECS)
print(f"V3 DONE {len(rows)} rows ok={ok} bad={bad}", flush=True)
