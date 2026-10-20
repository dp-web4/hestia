#!/usr/bin/env python3
"""Bind a terminal 'reply' to every stale peer-decide review_request in the
wake-1020 primer's i_owe fold. Pointer fragment carries the whole content
(window missed; seat down on quota 429, Oct 15-20). Paced under the
30-notices/10-min flood guard. Every send carries a stable operation_id so
uncertain responses retry safely. Log: scratchpad/kimi-stale-replies-20261020.jsonl
"""
import json, os, sys, time, importlib.util

os.environ.setdefault("HESTIA_MESH_PLUGIN", "kimi-code")
spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec); spec.loader.exec_module(hm)

PRIMER = "/home/dp/.kimi-code/hestia-mesh-primers/notice-0nF1Go.json"
LOG = "/home/dp/ai-workspace/hestia/scratchpad/kimi-stale-replies-20261020.jsonl"
PACE_SECS = 21
FLOOD_BACKOFF = 300

rows = json.load(open(PRIMER))["unanswered"]["i_owe"]
log = open(LOG, "a")

def note(rec):
    log.write(json.dumps(rec) + "\n"); log.flush()

def send_with_retries(h_s, row):
    to = row["from_plugin"]
    base, _, frag = row["pointer_uri"].partition("#")
    pointer = f"{base}#{frag};window-missed:seat-down-quota-oct15-20;via=kimi-code"
    args = {"to_plugin_id": to, "kind": "reply", "pointer_uri": pointer,
            "in_reply_to": int(row["id"]),
            "operation_id": f"kimi-stale-{row['id']}-20261020"}
    for attempt in range(4):
        try:
            if h_s[0] is None:
                h_s[0], h_s[1] = hm.connect()
            out = hm.rpc(h_s[0], "hestia_member_notify",
                         dict(args, session_id=h_s[1]))
        except Exception as e:
            note({"id": row["id"], "attempt": attempt, "exc": repr(e)})
            h_s[0] = None
            time.sleep(30)
            continue
        if not hm.failed(out):
            note({"id": row["id"], "to": to, "queued_id": out.get("queued_id"),
                  "binding_verified": out.get("binding_verified"), "ok": True})
            return True
        code = (out.get("_hestia_error") or {}).get("code", "?")
        note({"id": row["id"], "attempt": attempt, "refused": code})
        if "flood" in code:
            time.sleep(FLOOD_BACKOFF)
            continue
        return False  # non-flood refusal: do not retry
    return False

h_s = [None, None]
ok = bad = 0
for i, row in enumerate(rows):
    if row.get("kind") != "review_request":
        note({"id": row.get("id"), "skipped_kind": row.get("kind")}); continue
    if send_with_retries(h_s, row):
        ok += 1
    else:
        bad += 1
    if (i + 1) % 10 == 0:
        print(f"[{time.strftime('%H:%M:%S')}] {i+1}/{len(rows)} ok={ok} bad={bad}", flush=True)
    time.sleep(PACE_SECS)
print(f"DONE {len(rows)} rows ok={ok} bad={bad}", flush=True)
