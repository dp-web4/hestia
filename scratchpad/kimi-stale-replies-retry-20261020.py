#!/usr/bin/env python3
"""Retry the 14 rate_limited rows from kimi-stale-replies-20261020.jsonl.
Same content as the batch; slower pace + explicit rate-limit backoff."""
import json, os, time, importlib.util

os.environ.setdefault("HESTIA_MESH_PLUGIN", "kimi-code")
spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec); spec.loader.exec_module(hm)

PRIMER = "/home/dp/.kimi-code/hestia-mesh-primers/notice-0nF1Go.json"
LOG = "/home/dp/ai-workspace/hestia/scratchpad/kimi-stale-replies-20261020.jsonl"
RETRY_IDS = {26082, 26092, 26095, 26291, 26375, 26388, 26391,
             26756, 26758, 26760, 26762, 26923, 27085, 27116}
PACE_SECS = 45

rows = [r for r in json.load(open(PRIMER))["unanswered"]["i_owe"]
        if r["id"] in RETRY_IDS]
assert len(rows) == len(RETRY_IDS), (len(rows), len(RETRY_IDS))
log = open(LOG, "a")

h_s = [None, None]
for row in rows:
    base, _, frag = row["pointer_uri"].partition("#")
    args = {"to_plugin_id": row["from_plugin"], "kind": "reply",
            "pointer_uri": f"{base}#{frag};window-missed:seat-down-quota-oct15-20;via=kimi-code",
            "in_reply_to": int(row["id"]),
            "operation_id": f"kimi-stale-{row['id']}-20261020"}
    for attempt in range(8):
        try:
            if h_s[0] is None:
                h_s[0], h_s[1] = hm.connect()
            out = hm.rpc(h_s[0], "hestia_member_notify", dict(args, session_id=h_s[1]))
        except Exception as e:
            log.write(json.dumps({"id": row["id"], "attempt": attempt, "exc": repr(e)}) + "\n")
            log.flush(); h_s[0] = None; time.sleep(30); continue
        if not hm.failed(out):
            log.write(json.dumps({"id": row["id"], "to": row["from_plugin"],
                                  "queued_id": out.get("queued_id"),
                                  "binding_verified": out.get("binding_verified"),
                                  "ok": True, "retry": True}) + "\n")
            log.flush()
            break
        code = (out.get("_hestia_error") or {}).get("code", "?")
        log.write(json.dumps({"id": row["id"], "attempt": attempt, "refused": code, "retry": True}) + "\n")
        log.flush()
        if "rate_limited" in code:
            time.sleep(150); continue
        break
    time.sleep(PACE_SECS)
print("RETRY DONE", flush=True)
