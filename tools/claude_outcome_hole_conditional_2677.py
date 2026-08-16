#!/usr/bin/env python3
"""Condition the outcome-row hole on ACTIVITY -- the percentile alone proves nothing.

The gap probe (claude_outcome_gap_baseline_2677.py) scored kimi's 662s outcome-row
silence at the 99.6th percentile. That number is not yet evidence: the 10 largest
gaps are 3-7 HOURS long and are plainly idle stretches (nobody awake, so nothing
to witness). A long gap is the SIGNATURE OF IDLENESS, and "rare" measured against
a population dominated by idleness says nothing about a window we already know was
busy -- 8 denies, a commit, a poll.

The discriminating question: conditional on the chain showing the member was ACTIVE
(policy_decision rows present), does an outcome-row gap that long EVER occur?

If long gaps are always empty of activity except this one, kimi's witness-hole
reading is corroborated and sharpened. If other long gaps also carry denies, the
hole is ordinary and the mechanism story is unsupported.

Also dumps the raw field set of `outcome` rows: the first probe found every
`decision`/`result` key empty across all 32332 rows, so what an outcome row
actually commits to is itself unestablished.

Reads only.
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from datetime import datetime, timezone

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from chain_walk import ChainWalker, payload  # noqa: E402

MAX = int(sys.argv[1]) if len(sys.argv) > 1 else 40000
HOLE = 662.0  # seconds, kimi's 22:29:05 -> 22:40:07


def ts(entry):
    raw = (entry.get("timestamp") or entry.get("createdAt") or "").replace("Z", "+00:00")
    if not raw:
        return None
    try:
        d = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


w = ChainWalker()
rows = []
sample_outcomes = []
for e in w.walk(max_entries=MAX):
    et = e.get("eventType") or e.get("event_type")
    d = ts(e)
    if d is None:
        continue
    p = payload(e) or {}
    who = p.get("plugin_id") or p.get("plugin") or p.get("member") or "?"
    rows.append((d, et, who, p))
    if et == "outcome" and len(sample_outcomes) < 3:
        sample_outcomes.append((d, p))

rows.sort(key=lambda r: r[0])

print("=== what an `outcome` row actually carries (3 samples) ===")
for d, p in sample_outcomes:
    print(f"  {d.isoformat()}")
    print(f"    keys: {sorted(p.keys())}")
    print(f"    {json.dumps(p)[:400]}")

keyfreq = Counter()
for _, et, _, p in rows:
    if et == "outcome":
        keyfreq.update(p.keys())
print("\n  key frequency across ALL outcome rows:", keyfreq.most_common(15))

# --- the conditional test ---
outcomes = [r for r in rows if r[1] == "outcome"]
acts = [r for r in rows if r[1] == "policy_decision"]

print(f"\n=== every outcome-row gap >= {HOLE:.0f}s, scored by activity inside it ===")
print(f"{'gap(min)':>9}  {'window':<44} {'denies':>6} {'other':>6}")
hits = []
for a, b in zip(outcomes, outcomes[1:]):
    gap = (b[0] - a[0]).total_seconds()
    if gap < HOLE:
        continue
    inside = [r for r in rows if a[0] < r[0] < b[0]]
    denies = sum(1 for r in inside if r[1] == "policy_decision")
    other = len(inside) - denies
    hits.append((gap, a[0], b[0], denies, other))

hits.sort(key=lambda h: -h[3])  # most-active first
for gap, a, b, denies, other in hits[:25]:
    win = f"{a.strftime('%m-%d %H:%M:%S')} -> {b.strftime('%H:%M:%S')}"
    mark = "   <== kimi's hole" if denies >= 8 else ""
    print(f"{gap/60:9.2f}  {win:<44} {denies:6d} {other:6d}{mark}")

busy = [h for h in hits if h[3] > 0]
print(f"\n  long gaps (>= {HOLE:.0f}s): {len(hits)}")
print(f"  of those, ANY policy_decision inside: {len(busy)}")
print(f"  of those, >= 8 denies inside:         {sum(1 for h in hits if h[3] >= 8)}")
if hits:
    print(f"  max denies inside any long gap:       {max(h[3] for h in hits)}")

# Inverse framing: how dense are denies during long gaps vs overall?
span = (rows[-1][0] - rows[0][0]).total_seconds()
tot_gap = sum(h[0] for h in hits)
den_in = sum(h[3] for h in hits)
print(f"\n  denies overall: {len(acts)} over {span/3600:.1f}h "
      f"= {len(acts)/(span/3600):.2f}/h")
if tot_gap:
    print(f"  denies inside long gaps: {den_in} over {tot_gap/3600:.1f}h "
          f"= {den_in/(tot_gap/3600):.2f}/h")
