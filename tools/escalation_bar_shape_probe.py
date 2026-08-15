#!/usr/bin/env python3
"""Is `bar` ABSENT from the open record, or is my reader missing a nested key?

The census reported 306/511 opens with no `bar`. Before that number is published it has
to survive the instrument check: chain_walk's own docstring warns that the two gate_self
event types nest their fields under `data` inside `eventData` while everything else is
flat, so a flat reader silently drops exactly the fields it is asking about.

Dumps the raw key set of opens that DID and DID NOT yield a bar, so the difference is
visible as a shape rather than inferred from a count.
"""
from __future__ import annotations

import collections
import json
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from chain_walk import ChainWalker, payload  # noqa: E402

OPEN_ALIASES = ("gate_escalation_opened", "gate_escalation_open")

with_bar, without_bar = [], []
keysets = collections.Counter()

w = ChainWalker()
for e in w.walk(max_entries=40000):
    if e.get("eventType") not in OPEN_ALIASES:
        continue
    pl = payload(e)
    keysets[tuple(sorted(pl.keys()))] += 1
    (with_bar if pl.get("bar") else without_bar).append(e)

print(f"opens seen: {len(with_bar) + len(without_bar)}  "
      f"with bar: {len(with_bar)}  without: {len(without_bar)}\n")

print("=== distinct payload key sets (count, keys) ===")
for ks, n in keysets.most_common(8):
    print(f"{n:>5}  {list(ks)}")

for label, rows in (("WITHOUT bar", without_bar), ("WITH bar", with_bar)):
    print(f"\n=== raw specimen, {label} ===")
    if rows:
        print(json.dumps(rows[0], indent=2)[:1800])
