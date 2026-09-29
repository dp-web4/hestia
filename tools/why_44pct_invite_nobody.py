#!/usr/bin/env python3
"""Why does 44% of escalations invite nobody, and does the record say so?

`invited_peers_cannot_answer.py` found that 157 of 357 opened escalations carry an EMPTY
`invited_peers`, and that those receive a peer factor 1.3% of the time against 64-72% when
real peers are invited. Invitation is very nearly deterministic of whether review happens
at all -- which puts the whole remedy space for `sovereign_plus_peer` on the invitation
step, not on the latency of the peers who were invited.

This driver asks the next question, at the same grain: is the empty list EXPLAINED in the
record? The `gate_escalation_opened` payload carries three fields that exist for exactly
this purpose -- `invitation_withheld`, `invitation_passed_over`, `invitation_evidence` --
so an empty list is either accounted for by them or it is a silent omission.

WHAT WOULD REFUTE THE WORRY: the no-invite rows carry a populated `invitation_withheld`
(the system knows it invited nobody, and why). WHAT WOULD CONFIRM IT: those fields are
empty too, i.e. the record cannot distinguish "deliberately sole-authority" from "the
invitation step silently did nothing".

Also cross-tabulated, because a difference in kind would explain the split without any
defect: `bar`, `opened_via`, `assurance`, `decided_awaiting_claim`, and the eventual
`status` / `bar_met`. If the no-invite rows are all `single_approver` by design, the 44%
is policy rather than breakage -- and that is a materially different finding, so it is
measured rather than assumed in either direction.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chain_walk import ChainWalker, payload  # noqa: E402

OPENED = "gate_escalation_opened"
DECIDED = "gate_escalation_decided"
CORROBORATED = "gate_escalation_corroborated"


def brief(v):
    if v is None:
        return "None"
    if isinstance(v, (list, dict)):
        return f"EMPTY({type(v).__name__})" if not v else f"SET n={len(v)}"
    if v == "":
        return "EMPTY(str)"
    return str(v)[:40]


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-hops", type=int, default=60000)
    args = ap.parse_args(argv)

    chain = ChainWalker()
    opened, decided = {}, {}
    factors = collections.defaultdict(int)
    span_new = span_old = None

    for entry in chain.walk(max_entries=args.max_hops):
        t = entry.get("timestamp")
        if t:
            span_new = span_new or t
            span_old = t
        et = entry.get("eventType")
        if et not in (OPENED, DECIDED, CORROBORATED):
            continue
        p = payload(entry)
        e = p.get("escalation_id") or p.get("id")
        if not e:
            continue
        if et == OPENED:
            opened[e] = p
        elif et == DECIDED:
            decided.setdefault(e, p)
        else:
            factors[e] += 1

    groups = {"NO-INVITE": [], "INVITED": []}
    for e, p in opened.items():
        groups["NO-INVITE" if not (p.get("invited_peers") or [])
               else "INVITED"].append((e, p))

    print(f"span {span_old} .. {span_new}  (HOP BUDGET, not a date)")
    for g, rows in groups.items():
        print(f"\n{'='*66}\n{g}: n={len(rows)}")
        for field in ("invitation_withheld", "invitation_passed_over",
                      "invitation_evidence", "bar", "opened_via", "assurance",
                      "decided_awaiting_claim", "role", "plugin_id", "answers_deny"):
            c = collections.Counter(brief(p.get(field)) for _, p in rows)
            top = ", ".join(f"{k}={v}" for k, v in c.most_common(4))
            print(f"  {field:24s} {top}")
        # outcome
        st = collections.Counter(
            (decided[e].get("status") if e in decided else "NEVER-DECIDED")
            for e, _ in rows)
        bm = collections.Counter(
            (str(decided[e].get("bar_met")) if e in decided else "-")
            for e, _ in rows)
        fac = sum(1 for e, _ in rows if factors.get(e))
        print(f"  {'status':24s} " + ", ".join(f"{k}={v}" for k, v in st.most_common(5)))
        print(f"  {'bar_met':24s} " + ", ".join(f"{k}={v}" for k, v in bm.most_common(4)))
        print(f"  {'got >=1 factor':24s} {fac}/{len(rows)} ({fac/len(rows):.1%})")

    # Is the empty list ever ACCOUNTED FOR by the fields that exist to account for it?
    ni = groups["NO-INVITE"]
    accounted = [e for e, p in ni
                 if (p.get("invitation_withheld") or p.get("invitation_passed_over")
                     or p.get("invitation_evidence"))]
    print(f"\n{'='*66}")
    print(f"no-invite rows whose record EXPLAINS the empty list: "
          f"{len(accounted)}/{len(ni)}")
    if accounted:
        e = accounted[0]
        p = dict(opened[e])
        print("  first example: " + json.dumps(
            {k: p.get(k) for k in ("escalation_id", "invitation_withheld",
                                   "invitation_passed_over", "invitation_evidence",
                                   "bar", "opened_via")}, default=str)[:400])
    print("  -> an unexplained empty list cannot be told apart, from the record alone,"
          "\n     from a deliberate sole-authority escalation.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
