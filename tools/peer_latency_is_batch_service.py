#!/usr/bin/env python3
"""Is a peer factor LATE because the peer deliberated, or because nobody woke it?

THE STANDING FACT this interrogates. Measured 2026-08-31 (`escalation_outcome_is_presence.py`,
findings/the-gate-filters-by-attention-not-judgment-20260831.md): peers file plenty of
review -- 196 corroboration factors on 39% of escalations -- and 130 of them land AFTER the
ruling is already final, median 736s late. Only 11% reaches the decision it was written for.

That number is compatible with two completely different worlds, and the remedy differs in
each. Nobody has separated them:

  WORLD A -- DELIBERATION. Reviewing is genuinely slow. A peer receives the invitation
  promptly and takes ~700s to walk the chain, read the act and form a verdict. The window
  is simply too short for the work. Remedy: lengthen the window, or accept post-hoc factors.

  WORLD B -- BATCH SERVICE. Reviewing is fast, but a member is not a server. It drains its
  mailbox ONCE at the top of a wake and then works (#506). Between wakes the invitation
  sits undelivered no matter how quick the reviewer is. Latency is then a property of the
  WAKE CADENCE, and is the same whether the review takes 5 seconds or 5 minutes. Remedy:
  lengthening the window does nothing until it exceeds the inter-wake interval; you must
  either wake on invite or hold the decision for invited peers.

THE DISCRIMINATOR, and why it cannot be faked by either world. Under batch service, every
factor filed in one wake is stamped at essentially the same instant T, while the
escalations it answers were opened at scattered earlier times. So within a burst:

    latency(e) = T - t_open(e)          =>  d(latency)/d(t_open) = -1 exactly, R^2 ~ 1

Under deliberation, each factor's latency is drawn from a service-time distribution that
knows nothing about when the escalation opened, so the slope is ~0 with no fit. The two
worlds differ not by a little but by the whole dynamic range of the statistic, and the
sign is not reachable from the other model: no amount of slow thinking makes an EARLIER
escalation take LONGER by exactly the elapsed time.

PREREGISTERED, before the first run:
  B1  >= 60% of factors sit in a burst (inter-arrival gap < --gap) of >= 3 factors.
  B2  median within-burst SPREAD of opened_at >> median within-burst DURATION
      (a peer answers hours of backlog in a couple of minutes).
  B3  pooled within-burst slope of latency on t_open  <  -0.8  with R^2 > 0.8.
  Verdict BATCH only if all three hold. Verdict DELIBERATION if the slope is > -0.3.
  Anything else is MIXED and is reported as unresolved, not rounded to the nearer story.

WHY THE SLOPE IS COMPUTED WITHIN BURSTS AND NEVER POOLED RAW. Regressing latency on t_open
across the whole corpus would find slope -1 for a trivial and wrong reason: any bounded
observation window forces old opens to have had more time. The within-burst fit conditions
on the service event, which is the thing whose timing is in question.

THE SPAN IS A HOP BUDGET, NOT A DATE. The walk is tip-first; its old edge moves every time
the chain grows. The covered span is printed so a re-run can be compared rather than
assumed identical (#hop-budget).
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
CORROBORATED = "gate_escalation_corroborated"


def ts(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def fit(xs, ys):
    """Least squares slope + R^2. Returns (slope, r2, n) or (None, None, n)."""
    n = len(xs)
    if n < 3:
        return None, None, n
    mx = sum(xs) / n
    my = sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx == 0:
        return None, None, n
    slope = sxy / sxx
    syy = sum((y - my) ** 2 for y in ys)
    r2 = (sxy * sxy) / (sxx * syy) if syy > 0 else None
    return slope, r2, n


def median(v):
    if not v:
        return None
    s = sorted(v)
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max-hops", type=int, default=60000)
    ap.add_argument("--gap", type=float, default=180.0,
                    help="inter-arrival gap (s) that ends a burst")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    chain = ChainWalker()
    opened, decided = {}, {}
    factors = []          # (t, peer, escalation_id, dissent)
    span_new = span_old = None
    hops = 0

    for entry in chain.walk(max_entries=args.max_hops):
        hops += 1
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
        if et == CORROBORATED:
            factors.append({
                "t": ts(t), "peer": p.get("corroborated_by"),
                "eid": e, "dissent": bool(p.get("dissent")),
            })
        elif et == OPENED:
            opened[e] = ts(t)          # tip-first: keep the OLDEST sighting
        else:
            decided[e] = ts(t)

    # One factor per (peer, escalation): a re-file is not a second review event.
    first = {}
    for f in factors:
        k = (f["peer"], f["eid"])
        if k not in first or f["t"] < first[k]["t"]:
            first[k] = f
    facts = sorted(first.values(), key=lambda f: f["t"])

    # Bursts are PER PEER: two members waking minutes apart are two services, not one.
    by_peer = collections.defaultdict(list)
    for f in facts:
        by_peer[f["peer"]].append(f)

    bursts = []
    for peer, fs in by_peer.items():
        fs.sort(key=lambda f: f["t"])
        cur = [fs[0]]
        for a, b in zip(fs, fs[1:]):
            if b["t"] - a["t"] <= args.gap:
                cur.append(b)
            else:
                bursts.append((peer, cur))
                cur = [b]
        bursts.append((peer, cur))

    n_fact = len(facts)
    in_big = sum(len(b) for _, b in bursts if len(b) >= 3)
    b1 = in_big / n_fact if n_fact else 0.0

    spreads, durations = [], []
    all_x, all_y = [], []      # pooled WITHIN-burst, centred per burst
    per_burst_fits = []
    for peer, b in bursts:
        if len(b) < 3:
            continue
        opens = [opened.get(f["eid"]) for f in b]
        pairs = [(o, f["t"] - o) for o, f in zip(opens, b) if o is not None]
        durations.append(b[-1]["t"] - b[0]["t"])
        if len(pairs) >= 2:
            spreads.append(max(o for o, _ in pairs) - min(o for o, _ in pairs))
        if len(pairs) >= 3:
            s, r2, n = fit([p[0] for p in pairs], [p[1] for p in pairs])
            per_burst_fits.append({"peer": peer, "n": n, "slope": s, "r2": r2,
                                   "at": datetime.fromtimestamp(b[0]["t"], timezone.utc)
                                   .isoformat(timespec="seconds")})
            mx = sum(p[0] for p in pairs) / len(pairs)
            my = sum(p[1] for p in pairs) / len(pairs)
            for o, l in pairs:
                all_x.append(o - mx)
                all_y.append(l - my)

    slope, r2, nfit = fit(all_x, all_y)
    med_spread, med_dur = median(spreads), median(durations)
    b2 = (med_spread is not None and med_dur is not None
          and med_spread > 5 * max(med_dur, 1.0))
    b3 = slope is not None and slope < -0.8 and (r2 or 0) > 0.8

    if b1 >= 0.6 and b2 and b3:
        verdict = "BATCH SERVICE — latency is wake cadence, not deliberation"
    elif slope is not None and slope > -0.3:
        verdict = "DELIBERATION — latency is service time; the window is genuinely short"
    else:
        verdict = "MIXED / UNRESOLVED — preregistered criteria not all met"

    # How much of the observed lateness would vanish if the peer had been woken at invite?
    late = [f["t"] - decided[f["eid"]] for f in facts
            if f["eid"] in decided and f["t"] > decided[f["eid"]]]
    # Counterfactual: peer answers at its own burst's INTERNAL pace, starting at t_open.
    within = []
    for peer, b in bursts:
        if len(b) < 2:
            continue
        for a, c in zip(b, b[1:]):
            within.append(c["t"] - a["t"])

    out = {
        "hops": hops, "span_newest": span_new, "span_oldest": span_old,
        "gap_secs": args.gap,
        "factors_unique_peer_escalation": n_fact,
        "raw_corroborated_rows": len(factors),
        "peers": {p: len(v) for p, v in sorted(by_peer.items(), key=lambda kv: -len(kv[1]))},
        "bursts_total": len(bursts),
        "bursts_ge3": sum(1 for _, b in bursts if len(b) >= 3),
        "B1_frac_in_bursts_ge3": round(b1, 3),
        "B2_median_open_spread_secs": med_spread,
        "B2_median_burst_duration_secs": med_dur,
        "B2_pass": b2,
        "B3_pooled_within_burst_slope": None if slope is None else round(slope, 3),
        "B3_r2": None if r2 is None else round(r2, 3),
        "B3_n": nfit,
        "B3_pass": b3,
        "verdict": verdict,
        "median_lateness_after_ruling_secs": median(late),
        "n_late": len(late),
        "median_intra_burst_service_secs": median(within),
        "per_burst_fits": per_burst_fits,
    }

    if args.json:
        print(json.dumps(out, indent=2, default=str))
        return 0

    print(f"walk: {hops} hops, span {span_old} .. {span_new}")
    print(f"      (HOP BUDGET boundary, not a date the chain starts)")
    print(f"factors: {n_fact} unique (peer,escalation) from {len(factors)} rows")
    print("  by peer: " + ", ".join(f"{p}={n}" for p, n in out["peers"].items()))
    print(f"bursts (gap<{args.gap:g}s, per peer): {len(bursts)} total, "
          f"{out['bursts_ge3']} with >=3 factors")
    print()
    print(f"B1  factors inside a burst of >=3 : {b1:.1%}   "
          f"[{'PASS' if b1>=0.6 else 'FAIL'} vs >=60%]")
    print(f"B2  median opened_at SPREAD within a burst : "
          f"{med_spread and round(med_spread)}s")
    print(f"    median burst DURATION                 : "
          f"{med_dur and round(med_dur)}s   [{'PASS' if b2 else 'FAIL'}]")
    print(f"B3  pooled within-burst slope d(latency)/d(t_open) = "
          f"{slope if slope is None else round(slope,3)}  "
          f"R^2={r2 if r2 is None else round(r2,3)}  n={nfit}   "
          f"[{'PASS' if b3 else 'FAIL'} vs < -0.8, R^2 > 0.8]")
    print()
    print(f"VERDICT: {verdict}")
    print()
    print(f"observed: {out['n_late']} factors landed after the ruling, "
          f"median {med := out['median_lateness_after_ruling_secs']} "
          f"{'' if med is None else 's'} late")
    print(f"a peer, once awake, files its NEXT factor in "
          f"{out['median_intra_burst_service_secs']}s (median intra-burst gap)")
    print()
    for f in per_burst_fits:
        print(f"  burst {f['at']} {f['peer']:<12} n={f['n']:<3} "
              f"slope={f['slope']:+.3f} R^2={f['r2'] if f['r2'] is None else round(f['r2'],3)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
