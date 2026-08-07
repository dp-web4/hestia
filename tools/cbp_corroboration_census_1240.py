#!/usr/bin/env python3
"""Has ANYONE ever corroborated a gate escalation? — the peer half of `sovereign_plus_peer`.

The bar census (cbp_bar_met_census_1207.py) counts factors on DECIDED escalations and
finds factors=1 on 193/193. But `corroborate` freezes at decision, so a corroboration
on an escalation that EXPIRED undecided would never appear in that population. This
walks for the event itself, over the whole chain, so "never" is a count and not an
inference from a filtered denominator.

Also counts `gate_escalation_refused` and how many opens carry `answers_deny`, since
both bear on whether the peer half was ever reachable.
"""
from __future__ import annotations

import sys
from collections import Counter

from chain_walk import ChainWalker, payload

MAX = int(sys.argv[1]) if len(sys.argv) > 1 else 200_000

types = Counter()
corrob = []
opened_bars = Counter()
answers_deny_present = 0
opened_n = 0

w = ChainWalker()
n = 0
for e in w.walk(max_entries=MAX):
    n += 1
    et = e.get("eventType")
    types[et] += 1
    if et == "gate_escalation_corroborated":
        corrob.append(payload(e))
    elif et == "gate_escalation_opened":
        opened_n += 1
        p = payload(e)
        opened_bars[p.get("bar")] += 1
        if p.get("answers_deny"):
            answers_deny_present += 1

print(f"chain entries walked         : {n}")
print(f"gate_escalation_opened       : {opened_n}")
print(f"  by stated bar              : {dict(opened_bars)}")
print(f"  carrying answers_deny      : {answers_deny_present}")
print(f"gate_escalation_corroborated : {len(corrob)}   <-- the peer half, ever")
print(f"gate_escalation_refused      : {types.get('gate_escalation_refused', 0)}")
for p in corrob[:20]:
    print("   ", {k: p.get(k) for k in
                  ("escalation_id", "corroborated_by", "bar_met_if_decided_now")})
