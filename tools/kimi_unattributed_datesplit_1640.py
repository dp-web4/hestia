#!/usr/bin/env python3
"""Date-split companion to kimi_unattributed_unclaimable_census_1640.py.

For approved escalations opened under plugin_id 'unattributed': when were they
decided, and when were they claimed? The decision-0013 §4 note says approvals to
'unattributed' "proved unclaimable" on 2026-08-07 — if all 44 historical claims
pre-date the hook identity fix (#256, env-fallback -> PLUGIN_ID), the observed
unclaimability is the id-TRANSITION stranding old approvals, not an intrinsic
property of 'unattributed'.
"""
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from chain_walk import ChainWalker, payload  # noqa: E402

MAX = int(sys.argv[1]) if len(sys.argv) > 1 else 200_000

opened = {}
decided = {}   # esc_id -> (status, timestamp)
claimed = {}   # esc_id -> timestamp

w = ChainWalker()
for e in w.walk(max_entries=MAX):
    et = e.get("eventType")
    p = payload(e)
    ts = e.get("timestamp")
    if et == "gate_escalation_opened":
        opened[p.get("escalation_id")] = p.get("plugin_id")
    elif et == "gate_escalation_decided":
        decided[p.get("escalation_id")] = ((p.get("status") or "").lower(), ts)
    elif et == "gate_escalation_claimed":
        claimed[p.get("escalation_id")] = ts

rows = []
for esc_id, (st, dts) in decided.items():
    if "approv" not in st or opened.get(esc_id) != "unattributed":
        continue
    rows.append((dts, claimed.get(esc_id), esc_id))
rows.sort()

print(f"approved 'unattributed' escalations: {len(rows)}")
for dts, cts, esc_id in rows:
    print(f"  decided={dts}  claimed={cts or 'NEVER'}  {esc_id}")
