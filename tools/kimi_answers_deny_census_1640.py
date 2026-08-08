#!/usr/bin/env python3
"""Verify decision-0013's load-bearing number: `answers_deny` populated on
gate_escalation_opened — claimed "never — 0 of 314" (PR #283, dp 2026-08-07).

Independent re-measure at review time (kimi-code, answering notice 1640). Also counts
the `bar` field for cross-check against the in-code figure "bar on 4 of 365"
(handler.rs comment), and reports when answers_deny first appears if it has.

Uses the shared reader (chain_walk.py) — traps documented there apply.
"""
import sys
from collections import Counter

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from chain_walk import ChainWalker, payload  # noqa: E402

MAX = int(sys.argv[1]) if len(sys.argv) > 1 else 200_000

total = 0
with_answers_deny = 0
with_bar = 0
first_with_ad = None   # (chainPosition, opened_at-ish) — walking newest->oldest, so the LAST seen is the earliest
by_plugin = Counter()

w = ChainWalker()
for e in w.walk(max_entries=MAX):
    if e.get("eventType") != "gate_escalation_opened":
        continue
    total += 1
    p = payload(e)
    if p.get("answers_deny"):
        with_answers_deny += 1
        first_with_ad = (e.get("chainPosition"), p.get("escalation_id"), p.get("via"))
    if p.get("bar"):
        with_bar += 1
    by_plugin[p.get("plugin_id")] += 1

print(f"gate_escalation_opened total : {total}")
print(f"  carrying answers_deny      : {with_answers_deny}")
print(f"  carrying bar               : {with_bar}")
print(f"  earliest answers_deny row  : {first_with_ad}")
print("  by plugin_id:", dict(by_plugin.most_common(10)))
