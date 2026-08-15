#!/usr/bin/env python3
"""Does a single_approver open invite anyone?

The post-cutover census says 31 of 39 undecided escalations carry bar=single_approver,
which `bar_met()` satisfies on a PeerMember factor ALONE — any live peer could clear them
without the sovereign. Peers demonstrably can do this (6 peer decisions in the same 7
days), so the backlog is not a capability gap. The candidate explanation is that the
invitation is gated on the OTHER bar, so these rows ask nobody.

Measured here rather than read off the source, because "the code says it invites" and "the
chain shows an invitation" have disagreed on this exact path before (#241 patched the
opener nobody called). Reports, per bar, how many opens carried a non-empty invited_peers /
invitation_withheld, over the post-cutover era only.
"""
from __future__ import annotations

import collections
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from chain_walk import ChainWalker, payload  # noqa: E402

CUTOVER = "2026-08-08"  # first day the bar-less opener stopped minting

stats = collections.defaultdict(lambda: collections.Counter())
basis = collections.defaultdict(collections.Counter)

w = ChainWalker()
for e in w.walk(max_entries=200000):
    if e.get("eventType") not in ("gate_escalation_opened", "gate_escalation_open"):
        continue
    ts = e.get("timestamp") or ""
    if ts[:10] < CUTOVER:
        continue
    pl = payload(e)
    bar = pl.get("bar") or "unstated"
    s = stats[bar]
    s["opens"] += 1
    if pl.get("invited_peers"):
        s["invited_nonempty"] += 1
        s["invited_names"] += len(pl["invited_peers"])
    if pl.get("invitation_withheld"):
        s["withheld_nonempty"] += 1
    if pl.get("invitation_evidence"):
        s["evidence_nonempty"] += 1
    if pl.get("invitation_passed_over"):
        s["passed_over_nonempty"] += 1
    basis[bar][pl.get("asker_basis") or "-"] += 1

print(f"post-cutover opens (>= {CUTOVER}), invitation dispatch by bar\n")
for bar, s in sorted(stats.items(), key=lambda kv: -kv[1]["opens"]):
    print(f"bar = {bar}   opens={s['opens']}")
    print(f"    invited_peers non-empty     : {s['invited_nonempty']}"
          f"   (names dispatched: {s['invited_names']})")
    print(f"    invitation_withheld non-empty: {s['withheld_nonempty']}")
    print(f"    invitation_evidence non-empty: {s['evidence_nonempty']}")
    print(f"    invitation_passed_over       : {s['passed_over_nonempty']}")
    print(f"    asker_basis: {dict(basis[bar])}")
    print()
