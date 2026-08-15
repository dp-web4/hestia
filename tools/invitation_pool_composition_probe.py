#!/usr/bin/env python3
"""What would flipping the invitation gate COST, in dead letters?

`resolve_invitation` invites only on `sovereign_plus_peer`. Opening it to
`single_approver` would put ~123 opens/week in front of peers who can actually clear
them — but it multiplies invitation volume by the same registry pool that PR#454 measured
as majority residue. This prices that, so the ordering (prune the registry, THEN widen the
invitation) rests on a number rather than on caution.

Counts, over post-cutover sovereign_plus_peer opens: names dispatched, and how many of
them the daemon itself flagged as having no reader.
"""
from __future__ import annotations

import collections
import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from chain_walk import ChainWalker, payload  # noqa: E402

CUTOVER = "2026-08-08"

names = collections.Counter()
no_reader = collections.Counter()
opens = 0
dispatched = 0
readerless = 0

w = ChainWalker()
for e in w.walk(max_entries=200000):
    if e.get("eventType") not in ("gate_escalation_opened", "gate_escalation_open"):
        continue
    if (e.get("timestamp") or "")[:10] < CUTOVER:
        continue
    pl = payload(e)
    if pl.get("bar") != "sovereign_plus_peer":
        continue
    opens += 1
    inv = pl.get("invited_peers") or []
    # field name per PR#454: readerless invitees are reported, not hidden
    nr = set(pl.get("invited_without_reader") or [])
    dispatched += len(inv)
    readerless += sum(1 for p in inv if p in nr)
    for p in inv:
        names[p] += 1
        if p in nr:
            no_reader[p] += 1

print(f"post-cutover sovereign_plus_peer opens : {opens}")
print(f"invitation names dispatched            : {dispatched}")
# READ THIS ZERO AS ABSENCE OF THE FIELD, NOT ABSENCE OF THE CONDITION. PR#454 adds
# `invited_without_reader`; it is not merged, so the DEPLOYED daemon never emits it and
# every row reads 0. The chain cannot answer the reader question until #454 deploys —
# the residue below is counted by IDENTITY instead, which needs no new field.
print(f"  flagged reader-less                  : {readerless}"
      f"   <- 0 means the field is not deployed (PR#454), not that readers exist")
print("\nper-invitee (dispatched / readerless):")
for p, n in names.most_common(20):
    print(f"  {n:>5} / {no_reader[p]:<5}  {p}")
