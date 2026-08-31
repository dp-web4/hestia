#!/usr/bin/env python3
"""Is the escalation apparatus a review mechanism, or a HUMAN-PRESENCE DETECTOR?

THE FRAME QUESTION. The fleet has built a large peer-review apparatus on top of the
gate: bars (`sovereign_plus_peer`), invitation pools, `corroborate`/`dissent` factors,
reputation folds, review_done receipts, findings files. Every one of those artifacts
assumes the peer channel can MOVE an outcome. This script asks whether it ever does.

THE HYPOTHESIS, stated so it can be killed. If the outcome of an escalation is set by
whether a human was at the keyboard, and not by review, then time-from-open-to-terminal
is BIMODAL with nothing in the middle:

  * a SHARP spike at small dt -- the operator was present, read it, typed approve. Too
    fast for any mesh recipient to have woken, drained, walked the chain and filed.
  * a flat mass at the TTL (3600s) -- nobody was there; the record lapses unruled.

and the trough between them is exactly the region where peer review could have mattered.
REFUTED IF: substantial mass lands in the middle (say 120s..1800s) with peer factors
attached that moved a verdict. Then the apparatus works and this frame is wrong.

WHY THE WALK DIRECTION MAKES THE DENOMINATOR HONEST. The chain walks tip-first, newest
to oldest. A `decided` row is always NEWER than its `opened` row, so for any `opened`
this walk reaches, its decision (if one exists) was ALREADY VISITED. The old edge of the
walk therefore orphans `decided` rows (discarded here -- they cannot bias an open-keyed
rate) but never orphans an `opened` row's decision. The one real censor is the NEW edge:
an escalation opened minutes ago has not had time to lapse. Those are excluded by age,
not guessed at, and the excluded count is printed.

THE LEFT EDGE IS A WALK BOUNDARY, NOT A DATE (learned the hard way, #hop-budget). A hop
budget gives an unstated, drifting oldest-timestamp that moves every time the chain grows.
This prints the SPAN it actually covered so the run can be re-run and compared.
"""
from __future__ import annotations

import argparse
import collections
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chain_walk import ChainWalker, payload  # noqa: E402

OPENED = "gate_escalation_opened"
DECIDED = "gate_escalation_decided"
EXPIRED = "gate_escalation_expired"
CLAIMED = "gate_escalation_claimed"
#: TERMINAL STATES THIS DRIVER ORIGINALLY MISSED (corrected 2026-08-31, same day).
#: The first version knew only decided/expired and scored `withdrawn` as "no terminal
#: event at all" -- folding an asker's deliberate exit into the same bucket as a record
#: nobody ever looked at. They are opposite things: one is a voice, one is a silence.
WITHDRAWN = "gate_escalation_withdrawn"
ARBITER_REFUSED = "gate_escalation_arbiter_refused"
#: AND THE BIG ONE. `factors_present` on a `decided` row lists only the factors that were
#: in front of the decider AT DECISION TIME. Peer factors that land afterwards are their
#: own event class and never appear there, so a fold over `factors_present` answers
#: "how much review informed the verdict" while LOOKING like it answers "how much review
#: happened". Measured over this span the two differ by 6x: 32 vs 196. Counted separately.
CORROBORATED = "gate_escalation_corroborated"
TTL_SECS = 3600  # core/src/server/gate_escalation.rs:109 DEFAULT_TTL_SECS


def ts(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def eid_of(p):
    return p.get("escalation_id") or p.get("id")


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max-hops", type=int, default=25000)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    chain = ChainWalker()
    opened, decided, expired, claimed = {}, {}, {}, {}
    withdrawn, refused = {}, {}
    corroborations = collections.defaultdict(list)
    hops = 0
    span_new = span_old = None
    kinds = collections.Counter()

    for entry in chain.walk(max_entries=args.max_hops):
        hops += 1
        et = entry.get("eventType")
        t = entry.get("timestamp")
        if t:
            span_new = span_new or t
            span_old = t
        if et not in (OPENED, DECIDED, EXPIRED, CLAIMED, WITHDRAWN,
                      ARBITER_REFUSED, CORROBORATED):
            continue
        kinds[et] += 1
        p = payload(entry)
        e = eid_of(p)
        if not e:
            continue
        rec = dict(p)
        rec["_at"] = t
        if et == CORROBORATED:
            corroborations[e].append(rec)
            continue
        # tip-first walk: keep the OLDEST sighting of each id per kind
        {OPENED: opened, DECIDED: decided, EXPIRED: expired, CLAIMED: claimed,
         WITHDRAWN: withdrawn, ARBITER_REFUSED: refused}[et][e] = rec

    newest = ts(span_new) or 0.0

    rows = []
    for e, o in opened.items():
        t0 = ts(o.get("_at"))
        d = decided.get(e)
        term, t1 = None, None
        for src, label in ((d, "decided"), (withdrawn.get(e), "withdrawn"),
                           (expired.get(e), "expired_witnessed"),
                           (refused.get(e), "arbiter_refused")):
            if src:
                term, t1 = label, ts(src.get("_at"))
                break
        rows.append({
            "escalation_id": e,
            "opened_at": o.get("_at"),
            "plugin_id": o.get("plugin_id"),
            "bar": o.get("bar"),
            "terminal": term,
            "dt": (t1 - t0) if (t0 and t1) else None,
            "age": (newest - t0) if t0 else None,
            "status": (d or {}).get("status"),
            "bar_met": (d or {}).get("bar_met"),
            "decided_by": (d or {}).get("decided_by"),
            "decided_via": (d or {}).get("decided_via"),
            "decided_role": (d or {}).get("decided_role"),
            "secs_into_window": (d or {}).get("secs_into_window"),
            "factors_present": (d or {}).get("factors_present") or [],
            "claimed": e in claimed,
        })

    # A row younger than the TTL has not had time to lapse: censored, not evidence.
    mature = [r for r in rows if (r["age"] or 0) >= TTL_SECS]
    censored = len(rows) - len(mature)

    unruled = [r for r in mature if r["terminal"] is None]
    ruled = [r for r in mature if r["terminal"] == "decided"]
    lapsed = [r for r in mature if r["terminal"] == "expired_witnessed"]
    pulled = [r for r in mature if r["terminal"] == "withdrawn"]

    # WHEN did peer review arrive, relative to the verdict it was meant to inform?
    c_before = c_after = c_never = 0
    lateness = []
    for e, cs in corroborations.items():
        d = decided.get(e)
        for c in cs:
            tc = ts(c.get("_at"))
            if not d or tc is None:
                c_never += 1
                continue
            td = ts(d.get("_at"))
            if tc <= td:
                c_before += 1
            else:
                c_after += 1
                lateness.append(tc - td)
    lateness.sort()

    # The bimodality test, on RULED rows only -- the ones a peer could in principle reach.
    buckets = collections.Counter()
    EDGES = [(0, 30), (30, 60), (60, 120), (120, 300), (300, 600),
             (600, 1800), (1800, 3600), (3600, 10**9)]
    for r in ruled:
        dt = r["secs_into_window"]
        if dt is None:
            dt = r["dt"]
        if dt is None:
            buckets["no-dt"] += 1
            continue
        for lo, hi in EDGES:
            if lo <= dt < hi:
                buckets[f"{lo}-{hi}s"] += 1
                break

    out = {
        "hops": hops,
        "span_newest": span_new,
        "span_oldest": span_old,
        "note_left_edge": "oldest is a HOP BUDGET boundary, not a date the chain starts",
        "event_counts": dict(kinds),
        "opened_total": len(rows),
        "censored_younger_than_ttl": censored,
        "mature": len(mature),
        "ruled": len(ruled),
        "lapsed_witnessed_expiry": len(lapsed),
        "withdrawn_by_asker": len(pulled),
        "corroboration_events": sum(len(v) for v in corroborations.values()),
        "escalations_touched_by_a_peer": len(corroborations),
        "factors_before_the_ruling": c_before,
        "factors_AFTER_the_ruling": c_after,
        "factors_on_never_ruled": c_never,
        "median_lateness_secs": (lateness[len(lateness) // 2] if lateness else None),
        "unruled_no_terminal_event": len(unruled),
        "dt_buckets_for_ruled": dict(buckets),
        "ruled_claimed": sum(1 for r in ruled if r["claimed"]),
        "decided_by": dict(collections.Counter(r["decided_by"] for r in ruled)),
        "decided_via": dict(collections.Counter(r["decided_via"] for r in ruled)),
        "status": dict(collections.Counter(r["status"] for r in ruled)),
        "bar": dict(collections.Counter(r["bar"] for r in mature)),
        "factor_authors": dict(collections.Counter(
            f.get("by") for r in ruled for f in r["factors_present"])),
        "peer_factors_total": sum(
            1 for r in ruled for f in r["factors_present"] if f.get("by") != "operator"),
        "ruled_with_a_peer_factor": sum(
            1 for r in ruled
            if any(f.get("by") != "operator" for f in r["factors_present"])),
    }
    if args.json:
        print(json.dumps(out, indent=2, default=str))
        return 0

    print(f"hops={hops}  span {span_old} .. {span_new}")
    print(f"  (oldest edge is the HOP BUDGET, not a chain start date)")
    print(f"event counts: {dict(kinds)}")
    print()
    print(f"opened rows seen              : {len(rows)}")
    print(f"  censored (younger than TTL) : {censored}")
    print(f"  mature (>= {TTL_SECS}s old)      : {len(mature)}")
    print()
    print(f"  ruled (decided event)       : {len(ruled)}")
    print(f"  lapsed (expired event)      : {len(lapsed)}")
    print(f"  withdrawn by the asker      : {len(pulled)}")
    print(f"  NO terminal event at all    : {len(unruled)}")
    print()
    print("secs_into_window at decision, RULED rows only (daemon field):")
    for lo, hi in EDGES:
        k = f"{lo}-{hi}s"
        if buckets.get(k):
            n = buckets[k]
            bar = "#" * min(60, n)
            print(f"  {k:>14}  {n:5d}  {bar}")
    if buckets.get("no-dt"):
        print(f"  {'no-dt':>14}  {buckets['no-dt']:5d}")
    print()
    print(f"WHO decided (daemon's own field): {out['decided_by']}")
    print(f"  via                           : {out['decided_via']}")
    print(f"  status                        : {out['status']}")
    print(f"bar declared on mature opens    : {out['bar']}")
    print(f"factor authors                  : {out['factor_authors']}")
    print(f"ruled rows with a PEER factor   : {out['ruled_with_a_peer_factor']} / {len(ruled)}")
    print(f"ruled rows ever CLAIMED         : {out['ruled_claimed']} / {len(ruled)}")
    print()
    print("PEER REVIEW, counted as its own event class (not via factors_present):")
    print(f"  corroboration events          : {out['corroboration_events']}"
          f" on {out['escalations_touched_by_a_peer']} escalations")
    print(f"  in front of the decider       : {out['factors_before_the_ruling']}")
    _med = out["median_lateness_secs"]
    print(f"  landed AFTER the ruling       : {out['factors_AFTER_the_ruling']}"
          + (f"  (median {_med:.0f}s late)" if _med is not None else ""))
    print(f"  on escalations never ruled    : {out['factors_on_never_ruled']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
