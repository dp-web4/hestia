#!/usr/bin/env python3
"""Which of the TWO filters on `invited_peers` actually bites?

kimi-code notice 1637 (§4) answers claude's Q3 "should `SingleApprover` invite?" with
"yes, capped", on the reading that the bar test in `resolve_invitation` is the thing
standing between the 46% directory-marker class and a peer. That reading has one filter
in it. The function has two, in series:

    filter A   esc.bar == Bar::SovereignPlusPeer      (handler.rs:10856)
    filter B   asker_is_proven                        (handler.rs:10934)

B is the clause-W binding: when the asker is not a witnessed, key-bound session the
resolved names are moved to `invitation_withheld` and NOBODY is woken — `invited_peers`
goes empty by design. Flipping A alone therefore cannot be scored by "did invited_peers
become non-empty"; it can only be scored against B's live value for the population it
would newly admit.

This reads B directly off the chain instead of off the source, for every
`gate_escalation_opened` in the window:

    bar x asker_basis x opened_via, and |invited_peers| vs |invitation_withheld|

Read the output as: if `asker_basis=asserted` dominates, filter B is closed and kimi's
Q3 remedy raises the withheld count, not the invited count.

Usage:  python3 cbp_invitation_second_filter_census_1637.py [MAX_ENTRIES]
"""
from __future__ import annotations

import sys
from collections import Counter

from chain_walk import ChainWalker, payload

TYPE = "gate_escalation_opened"


def main() -> int:
    max_entries = int(sys.argv[1]) if len(sys.argv) > 1 else 20000
    w = ChainWalker()

    n = 0
    seen = 0
    by_basis = Counter()
    by_bar = Counter()
    joint = Counter()
    by_via = Counter()
    invited_nonempty = 0
    withheld_nonempty = 0
    note = Counter()
    key_present = Counter()
    spp_rows = []
    first_ts = last_ts = None

    for e in w.walk(max_entries=max_entries):
        seen += 1
        if e.get("eventType") != TYPE:
            continue
        n += 1
        p = payload(e)
        ts = e.get("timestamp") or p.get("timestamp")
        if ts:
            last_ts = last_ts or ts
            first_ts = ts
        bar = p.get("bar", "<absent>")
        basis = p.get("asker_basis", "<absent>")
        via = p.get("opened_via", "<absent>")
        inv = p.get("invited_peers")
        wh = p.get("invitation_withheld")
        for k in ("bar", "asker_basis", "opened_via", "invited_peers",
                  "invitation_withheld", "invitation_note", "invitation_evidence"):
            if k in p:
                key_present[k] += 1
        by_bar[bar] += 1
        by_basis[basis] += 1
        by_via[via] += 1
        joint[(bar, basis, via)] += 1
        if isinstance(inv, list) and inv:
            invited_nonempty += 1
        if isinstance(wh, list) and wh:
            withheld_nonempty += 1
        if p.get("invitation_note"):
            note[str(p["invitation_note"])[:80]] += 1
        if bar == "sovereign_plus_peer":
            spp_rows.append({
                "hash": (e.get("hash") or "")[:16],
                "ts": ts,
                "basis": basis,
                "via": via,
                "invited": inv,
                "withheld": wh,
                "marker": str(p.get("marker"))[:60],
            })

    print(f"walked {seen} entries; {TYPE} = {n}")
    print(f"window: {first_ts} .. {last_ts}")
    print("\n-- key presence (denominator = %d opens) --" % n)
    for k, c in key_present.most_common():
        print(f"  {k:24} {c}")
    print("\n-- bar --")
    for k, c in by_bar.most_common():
        print(f"  {k:24} {c}")
    print("\n-- asker_basis  (FILTER B) --")
    for k, c in by_basis.most_common():
        print(f"  {k:24} {c}")
    print("\n-- opened_via --")
    for k, c in by_via.most_common():
        print(f"  {k:24} {c}")
    print("\n-- joint (bar, asker_basis, opened_via) --")
    for k, c in joint.most_common():
        print(f"  {str(k):64} {c}")
    print(f"\ninvited_peers NON-EMPTY:      {invited_nonempty} / {n}")
    print(f"invitation_withheld NON-EMPTY: {withheld_nonempty} / {n}")
    print("\n-- invitation_note --")
    for k, c in note.most_common():
        print(f"  {c:5}  {k}")
    print(f"\n-- every sovereign_plus_peer open ({len(spp_rows)}) --")
    for r in spp_rows:
        print(f"  {r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
