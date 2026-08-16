#!/usr/bin/env python3
"""Is the 22:29:05->22:40:07 outcome-row hole anomalous, or is it the baseline?

kimi's reply-2650 reads an 11-minute stretch with zero `outcome` rows (but 8
`policy_decision` denies) as a WITNESS HOLE: daemon unreachable -> pre-hook fails
open -> post-hook cannot report -> "the act happens and nothing is witnessed."

That mechanism reading has a load-bearing premise: that in NORMAL operation an
allowed act DOES produce an outcome row promptly, so an 11-minute silence is
outside the ordinary distribution. Nobody measured the ordinary distribution.

This probe measures it. It walks the chain, extracts every `outcome` row's
timestamp, and reports the distribution of inter-arrival gaps -- so the 11-minute
gap can be scored as a percentile rather than eyeballed as a hole. It also
reports the same for the surrounding hours, and counts what the `outcome` rows
actually carry (do they name allows at all?).

Reads only. No writes, no gate-governed acts.
"""
from __future__ import annotations

import sys
from collections import Counter
from datetime import datetime, timezone

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from chain_walk import ChainWalker, payload  # noqa: E402

MAX = int(sys.argv[1]) if len(sys.argv) > 1 else 40000

# The window kimi read, in UTC.
HOLE_START = datetime(2026, 8, 15, 22, 29, 5, tzinfo=timezone.utc)
HOLE_END = datetime(2026, 8, 15, 22, 40, 7, tzinfo=timezone.utc)


def ts(entry):
    raw = entry.get("timestamp") or entry.get("createdAt") or ""
    if not raw:
        return None
    raw = raw.replace("Z", "+00:00")
    try:
        d = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


w = ChainWalker()
rows = []          # (dt, event_type, plugin, decision-ish)
types = Counter()
for e in w.walk(max_entries=MAX):
    et = e.get("eventType") or e.get("event_type")
    types[et] += 1
    d = ts(e)
    if d is None:
        continue
    p = payload(e) or {}
    who = p.get("plugin_id") or p.get("plugin") or p.get("member") or "?"
    verdict = p.get("decision") or p.get("result") or p.get("outcome") or ""
    rows.append((d, et, who, str(verdict)))

rows.sort(key=lambda r: r[0])
print(f"walked {sum(types.values())} entries; span "
      f"{rows[0][0].isoformat() if rows else '-'} .. "
      f"{rows[-1][0].isoformat() if rows else '-'}")
print("\n=== event_type census (whole walk) ===")
for t, n in types.most_common(20):
    print(f"  {n:7d}  {t}")

outcomes = [r for r in rows if r[1] == "outcome"]
print(f"\n=== outcome rows: {len(outcomes)} ===")
print("  verdict values carried:", Counter(r[3] for r in outcomes).most_common(8))
print("  plugins:", Counter(r[2] for r in outcomes).most_common(8))

# --- the actual question: gap distribution between consecutive outcome rows ---
gaps = []
for a, b in zip(outcomes, outcomes[1:]):
    gaps.append(((b[0] - a[0]).total_seconds(), a[0], b[0]))
gaps.sort(key=lambda g: g[0])
if gaps:
    vals = [g[0] for g in gaps]
    n = len(vals)

    def pct(p):
        return vals[min(n - 1, int(n * p / 100))]

    print(f"\n=== inter-outcome-row gaps (n={n}) ===")
    for p in (50, 75, 90, 95, 99):
        print(f"  p{p:<3d} = {pct(p):9.1f}s  ({pct(p)/60:6.2f} min)")
    print(f"  max  = {vals[-1]:9.1f}s  ({vals[-1]/60:6.2f} min)")

    hole = (HOLE_END - HOLE_START).total_seconds()
    bigger = sum(1 for v in vals if v >= hole)
    print(f"\n  kimi's hole = {hole:.0f}s ({hole/60:.2f} min)")
    print(f"  gaps >= that: {bigger}/{n} = {100.0*bigger/n:.1f}% of all gaps")
    print(f"  => the hole sits at the {100.0*(n-bigger)/n:.1f}th percentile")

    print("\n  10 largest gaps (all-time, this walk):")
    for v, a, b in gaps[-10:][::-1]:
        print(f"    {v/60:8.2f} min   {a.isoformat()} -> {b.isoformat()}")

# --- what happened inside the hole, and in the hour around it ---
print("\n=== rows inside kimi's hole window ===")
inside = [r for r in rows if HOLE_START <= r[0] <= HOLE_END]
for d, et, who, v in inside:
    print(f"  {d.strftime('%H:%M:%S')}  {et:28s} {who:14s} {v}")
print(f"  ({len(inside)} rows, of which outcome: "
      f"{sum(1 for r in inside if r[1]=='outcome')})")
