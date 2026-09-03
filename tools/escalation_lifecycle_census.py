#!/usr/bin/env python3
"""Every escalation's fate, from the CHAIN, because polled status cannot tell two fates apart.

WHY THIS EXISTS. Every lapse number this fleet has quoted, including the 76-of-116 unclaimed
approvals in #719 that motivated PRD #845, was read from the live store: `hestia gate poll`, or
a pending list, or a dashboard fed by them. #867 then measured that a REAPED row polls as
synthetic `expired` whether it was ruled or never ruled, and whether that ruling was approve or
deny. So a census over polled status counts every evicted RULING as a lapse, and nobody knows
by how much. Confirmed by hand on `1bce91a7dc4cbe4a`: opened by this seat, approved, claimed,
and today it polls `status=expired, bar=None`.

The chain does not forget. `gate_escalation_opened`, `_decided`, `_claimed`, `_expired` and
`_withdrawn` are append-only, so joining them by escalation id gives each petition's actual
fate, and the store's opinion is not consulted at all.

WHAT IT ANSWERS.
  1. How many escalations were opened, over the reachable window?
  2. Of those, how many were RULED (approved or denied), and how many carry no terminal event?
  3. Of the approvals, how many were CLAIMED? That is the number #719's ratio was reaching for,
     and it is the one PRD #845 exists to move.
  4. How many rulings would a poll TODAY misreport, because their row has been evicted? That
     is the correction factor for every previously published rate.

WHAT IT DOES NOT ANSWER. Anything before the reachable window. The walk is newest-to-oldest
past the 500-row cap via prevHash, and a bounded budget means a bounded window: the oldest
timestamp seen is printed, and every rate is a rate over THAT window, not over all time. An
escalation whose open predates the window but whose ruling does not is counted as `ruled,
open not seen` rather than silently folded into either side.

Read-only. One chain walk, no gate call, no poll, no write.

    python3 tools/escalation_lifecycle_census.py [--max 120000] [--json]
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chain_walk import ChainWalker, payload  # noqa: E402

OPENED = "gate_escalation_opened"
DECIDED = "gate_escalation_decided"
CLAIMED = "gate_escalation_claimed"
EXPIRED = "gate_escalation_expired"
WITHDRAWN = "gate_escalation_withdrawn"
KINDS = (OPENED, DECIDED, CLAIMED, EXPIRED, WITHDRAWN)


def esc_id(p: dict):
    for k in ("escalation_id", "escalationId", "id"):
        v = p.get(k)
        if isinstance(v, str) and v.strip():
            return v.strip()
    return None


def collect(walker, max_entries: int):
    """{escalation_id: {kind: payload}}, plus the event tally and the window's edges."""
    rows = defaultdict(dict)
    kinds = Counter()
    oldest = newest = None
    for e in walker.walk(max_entries=max_entries):
        kind = e.get("eventType") or e.get("event_type") or ""
        ts = e.get("timestamp") or e.get("createdAt") or ""
        if isinstance(ts, str) and ts:
            newest = newest or ts
            oldest = ts
        if kind not in KINDS:
            continue
        kinds[kind] += 1
        p = payload(e)
        eid = esc_id(p)
        if eid:
            rows[eid].setdefault(kind, p)   # newest-first walk: keep the FIRST seen
    return rows, kinds, oldest, newest


def classify(ev: dict) -> str:
    """One fate per escalation, from what the chain says happened to it."""
    if WITHDRAWN in ev:
        return "withdrawn"
    if DECIDED in ev:
        d = ev[DECIDED]
        approved = d.get("approve")
        if approved is None:
            approved = (d.get("status") or "").lower() == "approved"
        if not approved:
            return "denied"
        return "approved and claimed" if CLAIMED in ev else "approved, never claimed"
    if EXPIRED in ev:
        return "expired unruled"
    return "no terminal event on this chain window"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max", type=int, default=120_000, help="chain entries to walk")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rows, kinds, oldest, newest = collect(ChainWalker(), args.max)
    fates = Counter(classify(ev) for ev in rows.values())
    seen_open = sum(1 for ev in rows.values() if OPENED in ev)
    ruled = fates["approved and claimed"] + fates["approved, never claimed"] + fates["denied"]
    approvals = fates["approved and claimed"] + fates["approved, never claimed"]

    out = {
        "window_oldest": oldest, "window_newest": newest, "chain_entries_walked": args.max,
        "events": dict(kinds), "escalations_seen": len(rows), "open_event_seen": seen_open,
        "fates": dict(fates), "ruled": ruled, "approvals": approvals,
        "unclaimed_approvals": fates["approved, never claimed"],
        "unclaimed_rate_over_approvals": (
            round(fates["approved, never claimed"] / approvals, 4) if approvals else None),
        "rulings_a_poll_would_now_call_expired": ruled,
    }
    if args.json:
        print(json.dumps(out, indent=1))
        return 0

    print(f"CHAIN WINDOW  {oldest} .. {newest}   ({args.max} entries walked)")
    print("events: " + "  ".join(f"{k.replace('gate_escalation_', '')}={v}" for k, v in sorted(kinds.items())))
    print(f"\nescalations seen: {len(rows)}   (with an open event on this window: {seen_open})")
    for fate, n in fates.most_common():
        print(f"  {n:>5}  {fate}")
    if approvals:
        print(f"\nUNCLAIMED APPROVALS: {fates['approved, never claimed']} of {approvals} approvals "
              f"= {100 * fates['approved, never claimed'] / approvals:.1f}%")
        print("  denominator is APPROVALS ON THE CHAIN, not rows a poll can still see")
    print(f"\n{ruled} rulings are on the chain. A poll today reports `expired` for every one whose\n"
          "row has been reaped (#867), ruled or not, so any rate computed from polled status\n"
          "counts those as lapses. This census does not consult the store at all.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
