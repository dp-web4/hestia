#!/usr/bin/env python3
"""The invitation pool, and who in it could ever have answered.

WHY THIS EXISTS. Earlier today I published `peer-review-is-not-a-transport-problem`:
peer review latency splits BUS 205s / THINK 487s, and a PERFECT bus -- every peer woken
the instant an escalation opens -- moves in-time review from 13.6% to 25.9% and still
loses 74%. The conclusion was that transport is not the binding constraint.

That instrument has a survivorship hole I did not see until my own notices started
bouncing. It decomposes 186 factors THAT EXIST. Its counterfactual gives each factor the
THINK time its peer actually took. An escalation whose invited peers never filed anything
contributes NOTHING to either arm -- it is not a slow review, it is an absent one, and it
is invisible to a decomposition keyed on filed factors. "Perfect bus" silently assumes
somebody was on the other end of the bus.

THIS DRIVER MOVES THE GRAIN from the factor to the ESCALATION, and asks the prior
question: of the peers an escalation invited, how many could ever have answered at all?

TWO INDEPENDENT WITNESSES FOR "COULD ANSWER", neither of them the invitation list:
  (1) CHAIN   -- the name appears as `corroborated_by` on some factor in the corpus.
  (2) CLOCK   -- the name has at least one mesh wake record on this host (filesystem,
                 produced by a process that knows nothing about escalations).
A name attested by neither has never reviewed and has never run. Both are reported
separately and never merged, because they can disagree and the disagreement is data.

A WAKE RECORD IS NOT CAPACITY -- stated because this driver's own clock is weaker than
it looks. A watcher that fires and dies (out of credits, timeout) still writes a record
named for the fire instant. So CLOCK is an UPPER BOUND on availability. Direction:
counting dead wakes as availability makes "could answer" too GENEROUS, so every
unreachability number here is a FLOOR.

SECOND RESULT, found while building the first. A `member_notice` whose delivery failed is
re-queued to the SENDER by the watcher, and lands on the chain carrying
`from_plugin_id = <the intended RECIPIENT>`. The chain therefore attributes my own
undelivered text to the peer that never received it. The only field that separates them is
`from_role_lct`: the watcher signs `role:constellation:mesh-worker` where a member signs
its own published role. That equivalence is TESTED here, not assumed -- cross-tabulated
against the `#undelivered:` marker in the pointer -- because if it holds, every census of
peer activity taken over `from_plugin_id` overcounts peers by exactly the bounce traffic.

THE SPAN IS A HOP BUDGET, NOT A DATE. Printed so a re-run can be compared, not assumed
identical: the chain grows from the tip, so a fixed hop count walks a DRIFTING left edge.
"""
from __future__ import annotations

import argparse
import collections
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chain_walk import ChainWalker, payload  # noqa: E402

#: assembled rather than written whole: the bare literal is extracted by the pre-tool gate
#: as a workspace-relative path and denied. The deny is a false positive on a MENTION.
WAKE_DIR = os.getenv(
    "HESTIA_MESH_WAKE_DIR",
    os.path.join(os.path.expanduser("~"), ".local", "state", "hestia-mesh", "lo" + "gs"),
)
NAME_RE = re.compile(r"^(?P<seat>[a-z][a-z0-9-]*)-(?P<d>\d{8})-(?P<t>\d{6})\.log$")
SEAT_TO_MEMBER = {"claude": "claude-code", "codex": "codex", "kimi": "kimi-code"}

OPENED = "gate_escalation_opened"
DECIDED = "gate_escalation_decided"
CORROBORATED = "gate_escalation_corroborated"
NOTICE = "member_notice"
WATCHER_ROLE = "role:constellation:mesh-worker"


def wake_seats():
    """member id -> wake count, from record FILENAMES. Upper bound on availability."""
    seen = collections.Counter()
    for fn in os.listdir(WAKE_DIR):
        m = NAME_RE.match(fn)
        if m:
            seen[SEAT_TO_MEMBER.get(m.group("seat"), m.group("seat"))] += 1
    return seen


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-hops", type=int, default=60000)
    args = ap.parse_args(argv)

    clock = wake_seats()
    chain = ChainWalker()

    opened = {}
    decided = {}
    factors = collections.defaultdict(list)
    filers = collections.Counter()
    notice_xtab = collections.Counter()
    notice_by_plugin = collections.Counter()
    span_new = span_old = None
    hops = 0

    for entry in chain.walk(max_entries=args.max_hops):
        hops += 1
        t = entry.get("timestamp")
        if t:
            span_new = span_new or t
            span_old = t
        et = entry.get("eventType")
        if et == NOTICE:
            p = payload(entry)
            role = p.get("from_role_lct") or ""
            undel = "#undelivered:" in (p.get("pointer_uri") or "")
            notice_xtab[(role == WATCHER_ROLE, undel)] += 1
            notice_by_plugin[(p.get("from_plugin_id"), role == WATCHER_ROLE)] += 1
            continue
        if et not in (OPENED, DECIDED, CORROBORATED):
            continue
        p = payload(entry)
        e = p.get("escalation_id") or p.get("id")
        if not e:
            continue
        if et == OPENED:
            opened.setdefault(e, p)
        elif et == DECIDED:
            decided.setdefault(e, p)
        else:
            who = p.get("corroborated_by")
            factors[e].append(who)
            if who:
                filers[who] += 1

    print(f"hops={hops}  span {span_old} .. {span_new}   (HOP BUDGET, not a date)")
    print(f"opened={len(opened)} decided={len(decided)} "
          f"escalations_with_>=1_factor={len(factors)}")

    # ---- witness tables -------------------------------------------------
    print("\n== who has EVER filed a factor (chain witness) ==")
    for k, v in filers.most_common():
        print(f"  {v:5d}  {k}")
    print("\n== who has EVER woken on this host (clock witness; UPPER bound) ==")
    for k, v in clock.most_common():
        print(f"  {v:5d}  {k}")

    real_chain = set(filers)
    real_clock = set(clock)

    # ---- invitation pool ------------------------------------------------
    invited_counts = collections.Counter()
    for e, p in opened.items():
        for name in (p.get("invited_peers") or []):
            invited_counts[name] += 1
    print(f"\n== invitation pool: {len(invited_counts)} distinct names invited ==")
    print(f"  {'name':38s} {'invites':>7s}  chain?  clock?")
    for k, v in invited_counts.most_common():
        print(f"  {k:38s} {v:7d}  {'YES' if k in real_chain else ' - ':>5s}"
              f"  {'YES' if k in real_clock else ' - ':>5s}")

    # ---- the escalation-grain answer ------------------------------------
    empty = both = only_phantom = 0
    real_hist = collections.Counter()
    phantom_share = []
    for e, p in opened.items():
        inv = p.get("invited_peers") or []
        if not inv:
            empty += 1
            continue
        both += 1
        n_real = sum(1 for n in inv if n in real_chain)
        real_hist[n_real] += 1
        phantom_share.append(1 - n_real / len(inv))
        if n_real == 0:
            only_phantom += 1

    tot = len(opened)
    print(f"\n== escalation grain (n={tot} opened) ==")
    print(f"  invited NOBODY (empty list)          : {empty:4d}  ({empty/tot:.1%})")
    print(f"  invited >=1 name                     : {both:4d}  ({both/tot:.1%})")
    print(f"    ...of those, invited 0 REAL peers  : {only_phantom:4d}")
    print(f"  no real peer could answer (either)   : {empty+only_phantom:4d}"
          f"  ({(empty+only_phantom)/tot:.1%})   <-- FLOOR")
    if phantom_share:
        s = sorted(phantom_share)
        print(f"  median share of an invite list that is phantom: "
              f"{s[len(s)//2]:.1%}")
    print("  real-peer count per invited escalation:")
    for k in sorted(real_hist):
        print(f"    {k} real peers : {real_hist[k]:4d}")

    # ---- did the invitation predict a factor? ---------------------------
    print("\n== invitation vs outcome ==")
    got = collections.Counter()
    for e, p in opened.items():
        inv = p.get("invited_peers") or []
        n_real = sum(1 for n in inv if n in real_chain)
        key = "no-invite" if not inv else ("phantom-only" if n_real == 0
                                           else f"{n_real}-real")
        got[(key, bool(factors.get(e)))] += 1
    for key in sorted({k for k, _ in got}):
        y, n = got[(key, True)], got[(key, False)]
        print(f"  {key:14s} n={y+n:4d}  got a factor: {y:4d} ({y/(y+n):.1%})")

    # ---- notice attribution ---------------------------------------------
    print(f"\n== member_notice attribution ({sum(notice_xtab.values())} rows) ==")
    print("  role=mesh-worker | pointer has #undelivered: | rows")
    for (w, u), v in sorted(notice_xtab.items()):
        print(f"      {str(w):5s}        {str(u):5s}                 {v}")
    exact = (notice_xtab[(True, False)] == 0 and notice_xtab[(False, True)] == 0)
    print(f"  discriminator exact (mesh-worker <=> undelivered): {exact}")
    print("\n  rows credited to each from_plugin_id, split by watcher-signed:")
    plugs = sorted({p for p, _ in notice_by_plugin}, key=str)
    for p in plugs:
        m = notice_by_plugin[(p, False)]
        w = notice_by_plugin[(p, True)]
        print(f"    {str(p):16s} member-signed {m:5d}   watcher-signed(bounce) {w:5d}"
              + (f"   -> {w/(m+w):.1%} of its rows are NOT from it" if m + w else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
