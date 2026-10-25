#!/usr/bin/env python3
"""Wake-1025 deep chain scan: collect every chain event naming one of the
59 unanswered review_request targets (48 scopes + 11 escalations).

Writes scratchpad/kimi-wake-1025-targets.json: {target_id: [events...]}
Read-only.
"""
import sys, json, os
sys.path.insert(0, "/home/dp/ai-workspace/hestia/scratchpad/codex-review-18933/tools")
from chain_walk import ChainWalker, payload

PRIMER = "/home/dp/.kimi-code/hestia-mesh-primers/notice-82tPAc.json"
data = json.load(open(PRIMER))
owe = data["unanswered"]["i_owe"]

scopes, escs = {}, {}
for n in owe:
    ptr = n["pointer_uri"]
    if ptr.startswith("hestia://scope/"):
        rid = ptr.split("/")[3].split("#")[0]
        scopes[rid] = n["id"]
    elif ptr.startswith("hestia://escalation/"):
        eid = ptr.split("/")[3].split("#")[0]
        escs[eid] = n["id"]

targets = set(scopes) | set(escs)
print(f"targets: {len(scopes)} scopes, {len(escs)} escalations", file=sys.stderr)

# oldest notice queued 2026-10-23T15:26Z; walk until timestamps drop below that with margin
STOP_TS = "2026-10-23T14:00:00"
found = {t: [] for t in targets}
w = ChainWalker()
scanned = 0
for e in w.walk(max_entries=120_000):
    scanned += 1
    ts = e.get("timestamp") or ""
    et = e.get("eventType") or ""
    if scanned % 5000 == 0:
        print(f"  scanned {scanned} at {ts}", file=sys.stderr)
    if ts and ts < STOP_TS:
        print(f"reached stop ts {ts} after {scanned}", file=sys.stderr)
        break
    if not et.startswith(("scope_", "gate_escalation", "gate_decision")):
        continue
    d = payload(e)
    blob = json.dumps(d)
    for t in list(targets):
        # match bare id and scope- prefixed
        if t in blob:
            found[t].append({
                "pos": e.get("position"), "ts": ts, "eventType": et,
                "hash": e.get("hash"), "data": d,
            })

out = "/home/dp/ai-workspace/hestia/scratchpad/kimi-wake-1025-targets.json"
json.dump({"scanned": scanned, "scopes": scopes, "escalations": escs,
           "events": {k: v for k, v in found.items()}}, open(out, "w"), indent=1)
missing = [t for t, ev in found.items() if not ev]
print(f"scanned={scanned}; targets with zero events: {len(missing)}", file=sys.stderr)
for t in missing:
    print("  NO-EVENTS:", t, file=sys.stderr)
print("wrote", out, file=sys.stderr)
