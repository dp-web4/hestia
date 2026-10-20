#!/usr/bin/env python3
"""Batch v2: bind terminal 'reply' to every row in kimi-iowe-census-20261020.json
(the full live i_owe census, not the primer snapshot). All targets are transient
(scope/escalation windows long closed). Same operation-id scheme as v1 so rows
already sent dedupe at the daemon (replayed=true). Handles member_notify_rate_limited
explicitly. Appends to scratchpad/kimi-stale-replies-20261020.jsonl.
"""
import json, os, time, importlib.util

os.environ.setdefault("HESTIA_MESH_PLUGIN", "kimi-code")
spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec); spec.loader.exec_module(hm)

CENSUS = "/home/dp/ai-workspace/hestia/scratchpad/kimi-iowe-census-20261020.json"
LOG = "/home/dp/ai-workspace/hestia/scratchpad/kimi-stale-replies-20261020.jsonl"
PACE_SECS = 25
RATE_BACKOFF = 150

rows = json.load(open(CENSUS))["i_owe"]
log = open(LOG, "a")

def note(rec):
    log.write(json.dumps(rec) + "\n"); log.flush()

h_s = [None, None]
ok = bad = 0
for i, row in enumerate(rows):
    base, _, frag = row["pointer_uri"].partition("#")
    args = {"to_plugin_id": row["from_plugin"], "kind": "reply",
            "pointer_uri": f"{base}#{frag};window-missed:seat-down-quota-oct15-20;via=kimi-code",
            "in_reply_to": int(row["id"]),
            "operation_id": f"kimi-stale-{row['id']}-20261020"}
    done = False
    for attempt in range(9):
        try:
            if h_s[0] is None:
                h_s[0], h_s[1] = hm.connect()
            out = hm.rpc(h_s[0], "hestia_member_notify", dict(args, session_id=h_s[1]))
        except Exception as e:
            note({"id": row["id"], "attempt": attempt, "exc": repr(e), "v": 2})
            h_s[0] = None; time.sleep(30); continue
        if not hm.failed(out):
            note({"id": row["id"], "to": row["from_plugin"], "queued_id": out.get("queued_id"),
                  "binding_verified": out.get("binding_verified"),
                  "replayed": out.get("replayed"), "ok": True, "v": 2})
            ok += 1; done = True; break
        code = (out.get("_hestia_error") or {}).get("code", "?")
        note({"id": row["id"], "attempt": attempt, "refused": code, "v": 2})
        if "rate_limited" in code:
            time.sleep(RATE_BACKOFF); continue
        break
    if not done:
        bad += 1
    if (i + 1) % 10 == 0:
        print(f"[{time.strftime('%H:%M:%S')}] {i+1}/{len(rows)} ok={ok} bad={bad}", flush=True)
    time.sleep(PACE_SECS)
print(f"V2 DONE {len(rows)} rows ok={ok} bad={bad}", flush=True)
