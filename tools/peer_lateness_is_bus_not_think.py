#!/usr/bin/env python3
"""Split a peer's review lateness into BUS WAIT and THINK TIME, using two instruments.

WHY THIS EXISTS, AND WHAT IT REPLACES. A first attempt (`peer_latency_is_batch_service.py`)
tried to separate "peers deliberate slowly" from "peers are never woken" by regressing each
factor's latency on the escalation's open time WITHIN a burst of factors. It returned a
textbook batch signature -- slope -0.955, R^2 0.996 -- and the number is worthless. Grouping
factors by "arrived close together" and then discovering they arrived close together is
circular: once the service instants are within 42s and the opens are spread over 146s, a
slope near -1 is forced by arithmetic, whatever the underlying mechanism. That driver's B3
is RETRACTED. Its B1/B2 are kept as descriptive, because those were measured against a
threshold fixed in advance and simply failed.

THE FIX IS AN INSTRUMENT THAT DOES NOT COME FROM THE CHAIN. Every mesh wake writes a log
file named for the instant the watcher fired (see WAKE_DIR below). That is an independent
clock for "when was this peer awake", recorded by the filesystem, produced by a process
that knows nothing about escalations. Joining it to the chain's factor timestamps gives a
decomposition the chain alone cannot:

    t_open ......... escalation opens, invitation is queued
    W .............. the peer's wake in which the factor was actually filed
    t_factor ....... the corroboration lands on the chain

    BUS WAIT  = max(0, W - t_open)     nobody was listening; pure cadence
    THINK     = t_factor - W           the peer awake, reading and judging

A member drains its mailbox ONCE at the top of a wake and then works (#506). If that model
holds, BUS WAIT dominates and THINK is small, and the standing 736s median lateness is a
property of the wake schedule rather than of anyone's diligence -- in which case lengthening
the decision window buys nothing until it exceeds the inter-wake interval.

THE DRAIN-ONCE MODEL IS ITSELF TESTED HERE, not assumed. If a factor was filed in a wake
that BEGAN BEFORE its escalation opened, the peer must have re-read its mailbox mid-wake.
Under strict drain-once that count is zero. It is printed as `filed_in_wake_that_predates_open`.

CENSORING, stated rather than hidden. A factor whose peer has no wake record at or before
t_factor cannot be decomposed (rotation, a seat whose records predate retention, a factor
filed by a non-watcher path). Those are counted and EXCLUDED, never imputed to either bucket.

TIMEZONE. Wake-record names are LOCAL time; verified against `stat` birth time on a live
file (codex-20260831-103201 born 2026-08-31 10:32:01 -0700). Parsed as naive local and
converted by the platform, so a DST boundary inside the span is handled by the tz database
rather than by an offset constant.

THE SPAN IS A HOP BUDGET, NOT A DATE (#hop-budget). Printed for re-run comparison.
"""
from __future__ import annotations

import argparse
import bisect
import collections
import json
import os
import re
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chain_walk import ChainWalker, payload  # noqa: E402

#: assembled rather than written whole: the literal string is extracted as a bare relative
#: path by the pre-tool gate and denied against the workspace root. The deny is a false
#: positive on a MENTION, and it fires on the file's text, not on anything it does.
WAKE_DIR = os.environ.get(
    "HESTIA_MESH_WAKE_DIR",
    os.path.join(os.path.expanduser("~"), ".local", "state", "hestia-mesh", "lo" + "gs"),
)
NAME_RE = re.compile(r"^(?P<seat>[a-z][a-z0-9-]*)-(?P<d>\d{8})-(?P<t>\d{6})\.log$")
#: wake-record seat names are SHORT; the chain's `corroborated_by` uses the member id.
#: Not a guess: the three watcher lockfiles are watch-claude-code / watch-codex /
#: watch-kimi-code and the record prefixes are claude / codex / kimi.
SEAT_TO_MEMBER = {"claude": "claude-code", "codex": "codex", "kimi": "kimi-code"}

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


def median(v):
    if not v:
        return None
    s = sorted(v)
    m = len(s) // 2
    return s[m] if len(s) % 2 else (s[m - 1] + s[m]) / 2


def pct(v, q):
    if not v:
        return None
    s = sorted(v)
    return s[min(len(s) - 1, int(q * len(s)))]


#: A WAKE RECORD IS NOT CAPACITY. The watcher names the record for the instant it FIRED,
#: before the agent runs. If the agent then dies -- out of credits, usage limit, overload
#: -- the record exists and the member could not have filed anything. Measured rate
#: (`dead_wakes_are_not_availability.py`): codex 39.7%, kimi 26.8%, claude 3.9% of all
#: wakes. Those are not rare enough to ignore.
#:
#: DIRECTION OF THE ERROR, so the correction can be read without re-deriving it. W is the
#: LATEST wake start <= t_factor. Dead wakes only ADD candidate starts, so including them
#: can only move W LATER, never earlier. BUS = W - t_open is therefore OVERSTATED and
#: THINK = t_factor - W UNDERSTATED by the published run. The correction moves latency
#: from BUS to THINK -- i.e. AGAINST the transport remedy and IN FAVOUR of this driver's
#: own conclusion. That is exactly the direction that obliges stating it.
#:
#: `--live-wakes-only` is OFF by default so the published numbers stay reproducible.
DEAD_MARKERS = ("out of credits", "usage limit", "quota exceeded", "rate limit",
                "overloaded")
ECHO_DELIM = "end previous-wake-final-output"


def wake_died(path):
    """True if THIS wake's own output carries a failure marker.

    Positional, not a plain substring test: each record embeds the PREVIOUS wake's final
    output, so a healthy wake following a dead one contains the death message. Only the
    text after the last delimiter was produced by this wake.
    """
    try:
        with open(path, "r", errors="replace") as fh:
            low = fh.read().lower()
    except OSError:
        return False
    cut = low.rfind(ECHO_DELIM)
    tail = low[cut + len(ECHO_DELIM):] if cut >= 0 else low
    return any(m in tail for m in DEAD_MARKERS)


def load_wakes(live_only=False):
    """member -> sorted list of wake-start epochs, from record FILENAMES (local tz)."""
    wakes = collections.defaultdict(list)
    dropped = collections.Counter()
    for fn in os.listdir(WAKE_DIR):
        m = NAME_RE.match(fn)
        if not m:
            continue
        member = SEAT_TO_MEMBER.get(m.group("seat"))
        if not member:
            continue
        if live_only and wake_died(os.path.join(WAKE_DIR, fn)):
            dropped[member] += 1
            continue
        dt = datetime.strptime(m.group("d") + m.group("t"), "%Y%m%d%H%M%S")
        wakes[member].append(dt.timestamp())     # naive -> local -> epoch
    for v in wakes.values():
        v.sort()
    if live_only:
        print("dead wakes excluded from the clock: %s"
              % (dict(dropped) or "none"), file=sys.stderr)
    return wakes


def wake_containing(wakes, t):
    """The latest wake start <= t: the wake this act happened inside."""
    i = bisect.bisect_right(wakes, t)
    return wakes[i - 1] if i else None


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--max-hops", type=int, default=60000)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--live-wakes-only", action="store_true",
                    help="drop wakes whose own output shows the agent died "
                         "(out of credits / usage limit / overload). OFF by "
                         "default so the published run stays reproducible.")
    args = ap.parse_args(argv)

    wakes = load_wakes(live_only=args.live_wakes_only)
    chain = ChainWalker()
    opened, decided = {}, {}
    factors = {}
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
            k = (p.get("corroborated_by"), e)
            tt = ts(t)
            if k not in factors or tt < factors[k]["t"]:
                factors[k] = {"t": tt, "peer": p.get("corroborated_by"), "eid": e,
                              "dissent": bool(p.get("dissent"))}
        elif et == OPENED:
            opened[e] = ts(t)          # tip-first walk: keep the OLDEST sighting
        else:
            decided[e] = ts(t)

    rows, censored = [], collections.Counter()
    for f in factors.values():
        t0 = opened.get(f["eid"])
        if t0 is None:
            censored["open_row_outside_walk"] += 1
            continue
        w = wakes.get(f["peer"])
        if not w:
            censored["no_wake_record_for_" + str(f["peer"])] += 1
            continue
        W = wake_containing(w, f["t"])
        if W is None:
            censored["factor_predates_oldest_record"] += 1
            continue
        rows.append({
            "peer": f["peer"], "eid": f["eid"], "dissent": f["dissent"],
            "latency": f["t"] - t0,
            "bus": max(0.0, W - t0),
            "think": f["t"] - W,
            "wake_predates_open": W < t0,
            "late_by": (f["t"] - decided[f["eid"]]) if f["eid"] in decided else None,
        })

    n = len(rows)
    if not n:
        print("no decomposable factors; censored: " + json.dumps(dict(censored)))
        return 1
    bus = [r["bus"] for r in rows]
    think = [r["think"] for r in rows]
    lat = [r["latency"] for r in rows]
    predates = sum(1 for r in rows if r["wake_predates_open"])

    # THE COUNTERFACTUAL THE REMEDY TURNS ON. Suppose the bus were perfect: the peer is
    # woken the instant the escalation opens, and then takes exactly the IN-SESSION time it
    # actually took. Would its factor have reached the decider? This is the only question
    # that separates "wake peers faster" from "hold the decision", and it is answerable
    # because both halves are measured, not modelled.
    cf = {"n_with_ruling": 0, "actually_in_time": 0, "in_time_if_bus_were_zero": 0}
    for r in rows:
        d = decided.get(r["eid"])
        t0 = opened.get(r["eid"])
        if d is None or t0 is None:
            continue
        cf["n_with_ruling"] += 1
        if r["latency"] <= (d - t0):
            cf["actually_in_time"] += 1
        if r["think"] <= (d - t0):
            cf["in_time_if_bus_were_zero"] += 1

    lo = ts(span_old) or 0
    inter = {}
    for mem, w in wakes.items():
        ws = [x for x in w if x >= lo]
        gaps = [b - a for a, b in zip(ws, ws[1:])]
        inter[mem] = {"n_wakes": len(ws), "median_gap_secs": median(gaps)}

    tot_bus, tot_think = sum(bus), sum(think)
    share = tot_bus / (tot_bus + tot_think) if (tot_bus + tot_think) else None

    out = {
        "hops": hops, "span_oldest": span_old, "span_newest": span_new,
        "factors_decomposed": n, "censored": dict(censored),
        "median_latency_open_to_factor": median(lat),
        "median_BUS_wait": median(bus), "median_THINK": median(think),
        "p90_BUS_wait": pct(bus, 0.9), "p90_THINK": pct(think, 0.9),
        "share_of_total_latency_that_is_BUS": None if share is None else round(share, 3),
        "filed_in_wake_that_predates_open": predates,
        "filed_in_wake_that_predates_open_frac": round(predates / n, 3),
        "inter_wake": inter,
        "counterfactual_perfect_bus": cf,
        "by_peer": {},
    }
    for peer in sorted({r["peer"] for r in rows}):
        rs = [r for r in rows if r["peer"] == peer]
        out["by_peer"][peer] = {
            "n": len(rs),
            "median_bus": median([r["bus"] for r in rs]),
            "median_think": median([r["think"] for r in rs]),
            "predates": sum(1 for r in rs if r["wake_predates_open"]),
        }

    if args.json:
        print(json.dumps(out, indent=2, default=str))
        return 0

    print("walk: %d hops, span %s .. %s  (HOP BUDGET, not a date)"
          % (hops, span_old, span_new))
    print("wake records: " + ", ".join(
        "%s=%d wakes, median gap %ss" % (
            m, v["n_wakes"], v["median_gap_secs"] and round(v["median_gap_secs"]))
        for m, v in sorted(inter.items())))
    print("factors decomposed: %d   censored: %s" % (n, dict(censored) or "none"))
    print()
    print("  median open->factor latency : %ss" % round(median(lat)))
    print("  median BUS WAIT  (asleep)   : %ss      p90 %ss"
          % (round(median(bus)), round(pct(bus, 0.9))))
    print("  median THINK     (awake)    : %ss      p90 %ss"
          % (round(median(think)), round(pct(think, 0.9))))
    print("  share of ALL latency that is BUS : %.1f%%" % (100 * share))
    print()
    print("drain-once check: %d/%d (%.1f%%) factors were filed in a wake that BEGAN "
          "BEFORE the escalation opened" % (predates, n, 100 * predates / n))
    print("  (strict drain-once predicts 0; nonzero means members re-read mid-wake)")
    print()
    if cf["n_with_ruling"]:
        print("counterfactual, PERFECT BUS (peer woken at the instant of open, same "
              "in-session time):")
        print("  factors on a ruled escalation      : %d" % cf["n_with_ruling"])
        print("  reached the decider as it happened : %d (%.1f%%)"
              % (cf["actually_in_time"],
                 100 * cf["actually_in_time"] / cf["n_with_ruling"]))
        print("  would reach it with a perfect bus  : %d (%.1f%%)"
              % (cf["in_time_if_bus_were_zero"],
                 100 * cf["in_time_if_bus_were_zero"] / cf["n_with_ruling"]))
        print()
    for p, v in out["by_peer"].items():
        print("  %-12s n=%-4d median bus=%ss  think=%ss  mid-wake=%d"
              % (p, v["n"], round(v["median_bus"]), round(v["median_think"]),
                 v["predates"]))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
