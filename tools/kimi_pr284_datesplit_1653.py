#!/usr/bin/env python3
"""Date-bucketed follow-up: when did approved/claimed rows accumulate?
Tests whether PRD's '44 of 90' denominator matches a date-scoped census."""
import json
import sys
from collections import Counter

sys.path.insert(0, "/mnt/c/exe/projects/ai-agents/hestia/tools")
from chain_walk import ChainWalker, payload

w = ChainWalker()

approved_by_day = Counter()
claimed_by_day = Counter()
claimed_unattr_by_day = Counter()
decided_by_day = Counter()
first_decided = None
last_decided = None

for e in w.walk(max_entries=200_000):
    et = e.get("eventType")
    if et not in ("gate_escalation_decided", "gate_escalation_claimed"):
        continue
    ts = e.get("timestamp") or e.get("ts") or ""
    day = str(ts)[:10]
    p = payload(e)
    if et == "gate_escalation_decided":
        decided_by_day[day] += 1
        if p.get("status") == "approved":
            approved_by_day[day] += 1
    else:
        claimed_by_day[day] += 1
        if p.get("plugin_id") == "unattributed":
            claimed_unattr_by_day[day] += 1

# cumulative approved through each day
cum = 0
cum_rows = []
for day in sorted(set(approved_by_day) | set(decided_by_day)):
    cum += approved_by_day.get(day, 0)
    cum_rows.append((day, decided_by_day.get(day, 0), approved_by_day.get(day, 0), cum,
                     claimed_by_day.get(day, 0), claimed_unattr_by_day.get(day, 0)))

print("day        decided approved cum_approved claimed claimed_unattr")
for r in cum_rows:
    print(f"{r[0]}  {r[1]:>7} {r[2]:>8} {r[3]:>12} {r[4]:>7} {r[5]:>15}")
