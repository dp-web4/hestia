#!/usr/bin/env python3
"""Is the bar-less open shape a VINTAGE, or is it still being minted?

A count of "177 opens carry no bar" is true of two populations that call for opposite
remedies: rows written by an opener that has since been fixed (nothing to do, the number
is history), and rows an opener is still writing today (live defect). The date the shape
LAST appeared is what separates them, so report the per-day series rather than the total.
"""
from __future__ import annotations

import collections
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from chain_walk import ChainWalker, payload  # noqa: E402

OPEN_ALIASES = ("gate_escalation_opened", "gate_escalation_open")

series = collections.defaultdict(lambda: collections.Counter())
last_seen = {}
plugin_by_shape = collections.defaultdict(collections.Counter)
via_by_shape = collections.defaultdict(collections.Counter)

w = ChainWalker()
for e in w.walk(max_entries=200000):
    if e.get("eventType") not in OPEN_ALIASES:
        continue
    pl = payload(e)
    shape = "with-bar" if pl.get("bar") else "NO-bar"
    day = (e.get("timestamp") or "?")[:10]
    series[day][shape] += 1
    # newest-first walk, so the first sighting is the most recent
    last_seen.setdefault(shape, e.get("timestamp"))
    plugin_by_shape[shape][pl.get("plugin_id") or "?"] += 1
    via_by_shape[shape][pl.get("opened_via") or "-"] += 1

print("day          with-bar   NO-bar")
for day in sorted(series):
    r = series[day]
    print(f"{day}   {r['with-bar']:>6}   {r['NO-bar']:>6}")

print("\nmost recent sighting of each shape:")
for shape, ts in last_seen.items():
    print(f"  {shape:<10} {ts}")

for shape in ("with-bar", "NO-bar"):
    print(f"\n{shape} — plugin_id:")
    for p, n in plugin_by_shape[shape].most_common(6):
        print(f"    {n:>5}  {p}")
    print(f"{shape} — opened_via:")
    for v, n in via_by_shape[shape].most_common(6):
        print(f"    {n:>5}  {v}")
