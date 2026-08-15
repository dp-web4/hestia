#!/usr/bin/env python3
"""How much of the sovereign's escalation queue only the sovereign can clear.

WHY. Every open governance path on this fleet terminates at one human. The
mechanism work (invitation ordering, absent-derivation, the adjudicator ladder)
all improves how an escalation is ROUTED; none of it changes how many escalations
must reach dp. Before building another routing fix, measure the load and split it:

  decidable-by-peer  — bar SingleApprover, which `bar_met()` satisfies on a
                       PeerMember factor alone, AND `asker_basis` session. A live
                       peer can clear these.
  sovereign-only     — bar SovereignPlusPeer, whose `bar_met()` requires a
                       sovereign channel factor. No peer can clear these, and the
                       gate-self refusal class is UNAPPEALABLE, so there is no
                       second door either. An ASSERTED asker lands here too at any
                       bar: `eligibility_for` clause 0 refuses NOT-SAME outright,
                       so the row cannot collect a peer factor to spend.

THE BAR IS NOT THE WHOLE PREDICATE (codex, 2026-08-15, PR #455 review). Reading
`bar` alone over-counts: `arbiter::eligibility_for` clause 0 refuses the peer path
for `asker_basis == Asserted` BEFORE the bar is ever consulted, so a SingleApprover
row with an asserted asker is sovereign-only in production and peer-clearable only
in an instrument that stops at `bar`. Remeasured here with both clauses read,
139,647 entries, opens in the last 7d: 137 opens / 98 decided / 39 undecided, and
the undecided split is 31 peer-clearable + 8 sovereign-only, unchanged. The joint
is why it did not move — of 101 single_approver opens, 97 are session and the 4
asserted ones are all DECIDED, so the bar-only bucket and the two-clause bucket
happen to agree on this window. The count was right; the instrument printed a
number it could not prove,
and the next asserted row would have been mislabelled silently. Both clauses are
now read here, the basis split prints beside the bucket, and an ABSENT basis is
its own bucket rather than a default: pre-cutover `gate_escalation_opened`
payloads carry no `asker_basis` at all (measured: 0 of 362), and folding those
into either answer would be a guess wearing a count's clothes.

Then, within sovereign-only, split by what the escalation is ABOUT — because an
escalation minted by the gate firing on the investigation's own tooling is load
the fleet manufactures for itself, and it is removable without moving any
authority. That is the number that decides whether the next fix is a routing fix
or a precision fix.

TERMINAL STATE, honestly. `pending()` drops expired rows and expiry writes NO
chain event ([[ref-sovereign-plus-peer-bar-never]]), so "lapsed" is DERIVED here:
opened, no decided event, and the open is older than the widest window observed.
It is a lower bound on lapses, never a count of them, and it is labelled as such.

Usage:  python3 tools/sovereign_load_census.py [--days N] [--max-entries N]
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from chain_walk import ChainWalker, payload  # noqa: E402

OPENED = "gate_escalation_opened"
CLAIMED = "gate_escalation_claimed"
DECIDED = "gate_escalation_decided"
CORROB = "gate_escalation_corroborated"
# The two openers are DUPLICATED paths (#241); the installed hook calls claim, so a
# census keyed on one spelling alone under-counts. Count both, report the split.
OPEN_ALIASES = (OPENED, "gate_escalation_open")


def bucket(r):
    """Who could possibly clear this row — BOTH production clauses, in order.

    `arbiter::eligibility_for` clause 0 (asserted asker) runs BEFORE the bar, so it
    is tested first here too. Ordering matters for what the buckets MEAN: a
    SingleApprover row with an asserted asker is not a weaker peer-clearable row,
    it is a row with no peer door at all.

    An `unstated` basis is NOT read as either answer. It is the pre-cutover payload
    shape, and the honest bucket for it is "the instrument cannot tell".
    """
    basis = r.get("asker_basis", "unstated")
    bar = r["bar"]
    if bar not in ("sovereign_plus_peer", "single_approver"):
        return "unstated-bar"
    if bar == "sovereign_plus_peer":
        return "sovereign-only"
    if basis == "session":
        return "peer-clearable"
    if basis == "asserted":
        return "sovereign-only (asserted asker)"
    return "single_approver, basis unstated"


def parse_ts(raw):
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None


def esc_id(pl):
    for k in ("escalation_id", "id", "escalation"):
        v = pl.get(k)
        if isinstance(v, str) and v:
            return v
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=14)
    ap.add_argument("--max-entries", type=int, default=200000)
    args = ap.parse_args()

    since = datetime.now(timezone.utc) - timedelta(days=args.days)

    opens, decides, corrobs, claims = {}, {}, collections.defaultdict(list), {}
    seen_types = collections.Counter()
    walked = 0

    w = ChainWalker()
    for e in w.walk(max_entries=args.max_entries):
        walked += 1
        et = e.get("eventType")
        seen_types[et] += 1
        if et not in (CLAIMED, DECIDED, CORROB) and et not in OPEN_ALIASES:
            continue
        pl = payload(e)
        eid = esc_id(pl)
        if not eid:
            continue
        ts = parse_ts(e.get("timestamp") or pl.get("timestamp"))
        rec = {"ts": ts, "pl": pl, "type": et}
        if et in OPEN_ALIASES:
            opens.setdefault(eid, rec)
        elif et == DECIDED:
            decides.setdefault(eid, rec)
        elif et == CLAIMED:
            claims.setdefault(eid, rec)
        else:
            corrobs[eid].append(rec)

    # ---- window the OPENS; a decide outside the window still counts as a decide ----
    in_window = {k: v for k, v in opens.items()
                 if v["ts"] is not None and v["ts"] >= since}

    def bar_of(rec):
        b = rec["pl"].get("bar")
        return b if isinstance(b, str) and b else "unstated"

    def basis_of(rec):
        b = rec["pl"].get("asker_basis")
        return b if isinstance(b, str) and b else "unstated"

    def marker_of(rec):
        pl = rec["pl"]
        for k in ("marker", "rule", "reason", "rule_id"):
            v = pl.get(k)
            if isinstance(v, str) and v:
                return v
        return "unstated"

    rows = []
    for eid, rec in in_window.items():
        d = decides.get(eid)
        rows.append({
            "id": eid,
            "bar": bar_of(rec),
            "asker_basis": basis_of(rec),
            "marker": marker_of(rec),
            "opened": rec["ts"],
            "decided": bool(d),
            "decided_channel": (d["pl"].get("channel") or d["pl"].get("decided_by")
                                or "unstated") if d else None,
            "claimed": eid in claims,
            "peer_factors": len(corrobs.get(eid, [])),
        })

    total = len(rows)
    by_bar = collections.Counter(r["bar"] for r in rows)
    undecided = [r for r in rows if not r["decided"]]
    decided = [r for r in rows if r["decided"]]

    print(f"chain entries walked : {walked}")
    print(f"window               : last {args.days}d (opens since {since.isoformat()})")
    print(f"opens in window      : {total}")
    if not total:
        print("\nNo opens in the window. Widen --days before reading this as quiet.")
        return 0

    print(f"  decided            : {len(decided)}")
    print(f"  undecided          : {len(undecided)}  (lower bound on lapses; "
          f"expiry writes no chain event)")
    print("\nby bar:")
    for b, n in by_bar.most_common():
        print(f"  {b:<32} {n}")

    # THE SPLIT PRINTS BESIDE THE BUCKET, not behind it. A bucket count is a
    # judgement over two fields; showing only the judgement leaves a reader unable
    # to tell a 31/31-session backlog from a mixed one that happens to total 31.
    print("\nby (bar, asker_basis) — the joint, not two marginals:")
    for (b, ab), n in collections.Counter(
            (r["bar"], r["asker_basis"]) for r in rows).most_common():
        print(f"  {b:<24} {ab:<12} {n}")

    print("\nUNDECIDED, by who could clear it:")
    ub = collections.Counter(bucket(r) for r in undecided)
    for b, n in ub.most_common():
        print(f"  {b:<32} {n}")

    # Both sovereign-only spellings are sovereign LOAD. Matching the bare string
    # here would have quietly shrunk this number the day the first asserted row
    # landed — an error in the direction that flatters the routing fix.
    sov = [r for r in undecided if bucket(r).startswith("sovereign-only")]
    print(f"\nsovereign-only undecided: {len(sov)}")
    if sov:
        print("  by marker (what the gate refused):")
        for m, n in collections.Counter(r["marker"] for r in sov).most_common(15):
            print(f"    {n:>4}  {m}")
        wasted = sum(r["peer_factors"] for r in sov)
        with_peer = sum(1 for r in sov if r["peer_factors"])
        print(f"  peer factors already landed on them: {wasted} "
              f"across {with_peer} rows — work done that no bar can consume")

    print("\ndecided rows, by channel:")
    for c, n in collections.Counter(r["decided_channel"] for r in decided).most_common():
        print(f"  {c:<24} {n}")

    print("\nchain event types seen (top 12):")
    for t, n in seen_types.most_common(12):
        print(f"  {n:>7}  {t}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
