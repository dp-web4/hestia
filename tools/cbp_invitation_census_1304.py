#!/usr/bin/env python3
"""Did the INVITATION half of `sovereign_plus_peer` ever reach the record? — post-#226.

PR #226 (`9d3936d`, merged 2026-08-06) implemented dp's ruling that "two-bar is an
invitation to participate, not a blocker": `bar_met` for `SovereignPlusPeer` now reads
the sovereign conjunct alone, and the peer conjunct is retained *as evidence* via
`invited_peers` / `peer_participation()`.

The removal half is real. This censuses whether the EVIDENCE half exists on the chain,
because in the merged source `invited_peers` has no production writer (`open()` and
`rehydrate()` both set `Vec::new()`; the only assignment is in a test) and
`peer_participation()` has no production reader. If that is true on the chain too, then
what shipped is the blocker's removal with nothing standing where the invitation was.

Three counts, and the third is the one that matters:

  A. decided escalations: bar x bar_met  (does the #226 semantics show up yet?)
  B. corroborations, lifetime            (has any peer EVER been a factor?)
  C. every distinct key on a `gate_escalation_opened` / `_decided` payload
     -- an invitation that is issued must be NAMED somewhere. If no key names an
     invited peer, the record cannot distinguish "invited and absent" from "never
     asked", which is exactly the distinction #226 says it preserves.

Denominator discipline: A is over DECIDED escalations only; opened-but-undecided is
reported separately and never folded in. C is over payload keys, not values -- a key
present with an empty list still counts as present, because the claim under test is
whether the field reaches the chain at all.
"""
from __future__ import annotations

import sys
from collections import Counter

from chain_walk import ChainWalker, payload

MAX = int(sys.argv[1]) if len(sys.argv) > 1 else 400_000

opened: dict[str, dict] = {}
decided: dict[str, dict] = {}
claimed: set[str] = set()
corroborated: list[dict] = []
esc_types: Counter = Counter()

w = ChainWalker()
n = 0
for e in w.walk(max_entries=MAX):
    n += 1
    et = e.get("eventType") or ""
    if not et.startswith("gate_escalation"):
        continue
    esc_types[et] += 1
    p = payload(e) or {}
    eid = p.get("escalation_id") or p.get("id")
    if et == "gate_escalation_opened" and eid:
        opened.setdefault(eid, p)
    elif et == "gate_escalation_decided" and eid:
        decided.setdefault(eid, p)
    elif et == "gate_escalation_claimed" and eid:
        claimed.add(eid)
    elif et.startswith("gate_escalation_corroborat"):
        corroborated.append(p)

print(f"chain entries walked : {n}")
print(f"escalation events    : {dict(esc_types)}")
print(f"opened / decided / claimed : {len(opened)} / {len(decided)} / {len(claimed)}")
print(f"opened but NEVER decided   : {len(set(opened) - set(decided))}")
print()

print("=== A. decided escalations: bar x bar_met ===")
bars: Counter = Counter()
met: Counter = Counter()
absent_field: Counter = Counter()
for p in decided.values():
    bar = p.get("bar") or "(absent)"
    bars[bar] += 1
    bm = p.get("bar_met")
    if bm is None:
        absent_field[bar] += 1
    elif bm is True:
        met[bar] += 1
for bar, c in bars.most_common():
    print(f"  {bar:24s} n={c:5d}  bar_met=true: {met[bar]:4d}  field absent: {absent_field[bar]:4d}")
print()

print("=== B. peer participation, lifetime ===")
print(f"  corroboration events        : {len(corroborated)}")
fac: Counter = Counter()
chan: Counter = Counter()
for p in decided.values():
    fs = p.get("factors_present") or []
    fac[len(fs)] += 1
    for f in fs:
        if isinstance(f, dict):
            chan[f.get("channel") or "(none)"] += 1
print(f"  factor-set size on decided  : {dict(sorted(fac.items()))}")
print(f"  factor channels             : {dict(chan)}")
print()

print("=== C. does ANY key on the record name an invited peer? ===")
for label, pop in (("opened", opened), ("decided", decided)):
    keys: Counter = Counter()
    for p in pop.values():
        keys.update(p.keys())
    print(f"  {label} payload keys ({len(pop)} entries):")
    for k, c in keys.most_common():
        print(f"    {k:24s} {c}")
    hits = [k for k in keys if any(t in k.lower() for t in ("invit", "peer", "particip"))]
    print(f"    -> keys naming a peer/invitation: {hits or 'NONE'}")
print()

print("VERDICT: an invitation that is never named on the record cannot be audited,")
print("and 'invited and absent' is indistinguishable from 'nobody was ever asked'.")
