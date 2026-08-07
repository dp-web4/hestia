#!/usr/bin/env python3
"""Has the `sovereign_plus_peer` bar EVER been met? — census for notice 1207.

kimi's re-1198 pinned one escalation (bd3993b56ce49cff): bar `sovereign_plus_peer`,
decided solo by the operator 228s after opening, `bar_met: false`, `permits_write:
false`. They filed the law question ("may a sovereign decide a two-party bar alone?")
as above their seat.

It is measurable, and the measurable form is stronger than the law question. The gate's
own `is_claimable` (core/src/server/gate_escalation.rs:352-358) requires `bar_met()`.
So for every escalation whose bar was NOT met, the approval authorised nothing: the
member was told "approved" and the write still did not proceed. The question is whether
that is one incident or the population.

Counts, over the whole chain:
  A. every `gate_escalation_decided`: bar, bar_met, decided_by, decided_via
  B. decision LATENCY (decided_at - opened_at), joined via escalation id
  C. how many decided escalations were ever CLAIMED (i.e. actually permitted a write)

Denominator discipline: the population is decided escalations, not all escalations.
Opened-but-never-decided rows are reported separately, never folded into a rate.
"""
from __future__ import annotations

import sys
from collections import Counter, defaultdict

from chain_walk import ChainWalker, payload

MAX = int(sys.argv[1]) if len(sys.argv) > 1 else 200_000

opened: dict[str, dict] = {}
decided: dict[str, dict] = {}
claimed: set[str] = set()
seen_types: Counter = Counter()

w = ChainWalker()
n = 0
for e in w.walk(max_entries=MAX):
    n += 1
    et = e.get("eventType")
    seen_types[et] += 1
    if et not in ("gate_escalation_opened", "gate_escalation_decided",
                  "gate_escalation_claimed"):
        continue
    p = payload(e)
    eid = p.get("escalation_id") or p.get("id")
    if not eid:
        continue
    if et == "gate_escalation_opened":
        opened.setdefault(eid, p)
    elif et == "gate_escalation_decided":
        decided.setdefault(eid, p)
    else:
        claimed.add(eid)

print(f"chain entries walked      : {n}")
print(f"gate_escalation_opened    : {len(opened)}")
print(f"gate_escalation_decided   : {len(decided)}")
print(f"gate_escalation_claimed   : {len(claimed)}")
print()

# ---- A. the bar, and whether it was met -----------------------------------------
print("=== A. decided escalations: bar x bar_met ===")
bars = Counter()
met_true = Counter()
missing_field = Counter()
for eid, p in decided.items():
    bar = p.get("bar") or "(absent)"
    bars[bar] += 1
    bm = p.get("bar_met")
    if bm is None:
        missing_field[bar] += 1
    elif bm is True:
        met_true[bar] += 1
for bar, c in bars.most_common():
    print(f"  {bar:24s} n={c:5d}  bar_met=true: {met_true[bar]:4d}  "
          f"field absent: {missing_field[bar]:4d}")
print()

print("=== A2. decided_by x decided_via ===")
for k, c in Counter(
    (p.get("decided_by") or "(none)", p.get("decided_via") or "(none)")
    for p in decided.values()
).most_common(15):
    print(f"  {k[0]:20s} via {k[1]:22s} n={c}")
print()

print("=== A3. factor-set size on decided escalations ===")
fsz = Counter()
chans = Counter()
for p in decided.values():
    fs = p.get("factors") or p.get("factors_present") or []
    fsz[len(fs) if isinstance(fs, list) else "(non-list)"] += 1
    if isinstance(fs, list):
        for f in fs:
            if isinstance(f, dict):
                chans[f.get("channel") or "(none)"] += 1
for k, c in sorted(fsz.items(), key=lambda x: str(x[0])):
    print(f"  factors={k}: {c}")
print(f"  channels across all factors: {dict(chans)}")
print()

# ---- B. latency ------------------------------------------------------------------
# The decided row carries `secs_into_window` — the daemon's own latency, so this is a
# read of a recorded field, not a subtraction I derived from two clocks.
print("=== B. decision latency, from the decided row's own `secs_into_window` ===")
lat = sorted((p["secs_into_window"], eid) for eid, p in decided.items()
             if isinstance(p.get("secs_into_window"), (int, float)))
missing_lat = len(decided) - len(lat)
print(f"  rows carrying the field: {len(lat)}   absent: {missing_lat}")
if lat:
    vals = [x[0] for x in lat]
    def pct(q):
        return vals[min(len(vals) - 1, int(q * (len(vals) - 1)))]
    print(f"  min={vals[0]}s  p50={pct(.5)}s  p90={pct(.9)}s  max={vals[-1]}s")
    print(f"  decided within 300s: {sum(1 for v in vals if v <= 300)}/{len(vals)}")
    print(f"  fastest 8: {[(v, e[:8]) for v, e in lat[:8]]}")
# Latency split by bar: the peer has to arrive INSIDE this window or never.
print("  by bar:")
by_bar = defaultdict(list)
for eid, p in decided.items():
    if isinstance(p.get("secs_into_window"), (int, float)):
        by_bar[p.get("bar") or "(absent)"].append(p["secs_into_window"])
for bar, vs in sorted(by_bar.items()):
    vs.sort()
    print(f"    {bar:24s} n={len(vs):4d} min={vs[0]:6d}s "
          f"p50={vs[len(vs)//2]:6d}s max={vs[-1]:7d}s")
print()

# ---- B2. which writes get which bar ----------------------------------------------
# Matters because if the HIGHER bar is the unsatisfiable one, then the most sensitive
# class of governance write is the class that can never be approved at all.
print("=== B2. bar x marker (what target draws which bar) ===")
bar_marker = defaultdict(Counter)
for p in decided.values():
    bar_marker[p.get("bar") or "(absent)"][p.get("marker") or "(none)"] += 1
for bar, mk in sorted(bar_marker.items()):
    print(f"  {bar}:")
    for m, c in mk.most_common(6):
        print(f"     {c:5d}  {m}")
print()

# ---- C. did any approval ever permit a write? -------------------------------------
print("=== C. approvals that could actually authorise a write ===")
approved = {eid: p for eid, p in decided.items()
            if str(p.get("status", "")).lower() in ("approved", "approve")}
print(f"  status=approved            : {len(approved)}")
armed = {eid for eid, p in approved.items() if p.get("bar_met") is True}
print(f"  ... AND bar_met=true       : {len(armed)}")
print(f"  ... AND later claimed      : {len(armed & claimed)}")
print(f"  claimed rows w/ unmet bar  : {len(claimed - armed)}")
print()
print("An approval with bar_met=false is recorded as 'approved' and permits nothing:")
print("is_claimable() = status==Approved && bar_met() && !consumed && in-window.")
