#!/usr/bin/env python3
"""The denominator kimi-code named as missing on #648: reviewed-and-not-dissented, by asker.

kimi harvested `asked_by` for the 22-row #648 census and measured a real split
(class A = 9 claude / 12) -- then said the honest thing itself:

    "The data cannot fully separate 'claude's 220 truncates' from 'claude files
     the majority of everything' without a denominator of reviewed-and-not-
     dissented escalations by asker, which this census does not carry."

That denominator exists. It is not in the #648 census (n=22, hand-collected from
fire-record archives) but it IS on the chain, and `peer_dissent_ground_census.py`
already walks it for a 3x larger population (65 dissents / 60 concurrences,
hand-labelled). This file adds ONE field to that walk -- `plugin_id` off
`gate_escalation_opened`, the same daemon-minted asker field kimi bound four ways
-- and reports RATES instead of counts.

Two corrections to the shape of the question, both from the bigger census:

1. CONDITION ON REVIEWED, NOT ON DISSENTED. kimi's Fisher (p=0.0035) compares
   class A against B+C, i.e. it conditions on "a peer dissented". Rate over
   *reviewed* escalations is the comparison that answers "does an act asked by
   claude arrive unreviewable more often", because its denominator includes the
   escalations that were reviewed fine.

2. THE DISSENT-KEYED NUMERATOR IS CONTAMINATED BY REVIEWER IDIOM. The same
   census measured that whether the SAME obstacle is filed as dissent or as
   concurrence is predicted by which seat reviewed: codex 20/1 = 95% dissent,
   claude-code 8/7 = 53%, kimi-code 9/17 = 35% (chi2=18.07 df=2, codex vs rest
   p=2.6e-05). So "class A" membership is a joint function of (asker, reviewer).
   If claude-asked escalations disproportionately drew codex as reviewer, an
   asker-keyed split measures the roster. This file reports the reviewer mix per
   asker so that confound is visible, and repeats the rate with the
   idiom-free numerator: EVERY factor that says the record did not carry the
   act, on either value of the bool (record dissent + record_qualified +
   record_recovered concurrence).

THE HOP BUDGET IS NOT THE WINDOW. The hand labels cover a fixed era
(2026-08-24T00:13Z -> 2026-08-27T10:30Z, taken from the label keys themselves,
not asserted here). A `--max HOPS` walk has a drifting left edge, and a
`gate_escalation_corroborated` row re-serialises the WHOLE factor list, so a row
inside the walk can carry a factor filed days before it. The first run of this
file walked 25k hops (left edge 08-26) and still matched 101 labels from 08-24 --
i.e. its population was an era mix. So the population here is pinned to the
LABEL ERA, not to the walk: a factor counts only if its `at` is in the era, an
escalation counts only if every in-era dissent it drew is labelled, and the
walk must be deep enough to have SEEN the era (asserted, not assumed).

Usage: python3 tools/asker_denominator_census.py [--max HOPS]
"""
from __future__ import annotations

import argparse
import datetime as _dt
import sys
from collections import Counter, defaultdict

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from chain_walk import ChainWalker, payload  # noqa: E402
from peer_dissent_ground_census import (  # noqa: E402
    LABELS,
    CONCUR_LABELS,
    _chi2,
    _fisher_vs_rest,
)


def collect(max_entries: int):
    walker = ChainWalker()
    seen, asker, hops = {}, {}, 0
    first = last = None
    for entry in walker.walk(max_entries=max_entries):
        hops += 1
        ts = entry.get("timestamp")
        if first is None:
            first = ts
        last = ts
        data = payload(entry) or {}
        if not isinstance(data, dict):
            continue
        eid = data.get("escalation_id")
        if entry.get("eventType") == "gate_escalation_opened" and eid:
            # daemon-minted: deliver_invitations writes the invitation with
            # from = &esc.plugin_id (handler.rs:14436), so this is the same
            # field kimi bound through four evidence shapes.
            asker[eid] = data.get("plugin_id")
        factors = data.get("factors_present")
        if not isinstance(factors, list):  # INTEGER on gate_escalation_expired
            continue
        for f in factors:
            if f.get("channel") != "peer_member":
                continue
            seen[(eid, f.get("by"), f.get("at"))] = f
    return seen, asker, hops, first, last


def _parse(ts: str) -> int:
    return int(_dt.datetime.fromisoformat(ts).timestamp())


def _rate_table(name, tab, focus="claude-code"):
    print(f"\n{name}")
    tot_h = tot_m = 0
    for st in sorted(tab):
        h, m = tab[st]
        tot_h, tot_m = tot_h + h, tot_m + m
        pct = 100.0 * h / (h + m) if h + m else 0.0
        print(f"  {st:<12} {h:>3} / {h + m:>3}   {pct:5.1f}%")
    pct = 100.0 * tot_h / (tot_h + tot_m) if tot_h + tot_m else 0.0
    print(f"  {'ALL':<12} {tot_h:>3} / {tot_h + tot_m:>3}   {pct:5.1f}%")
    if len(tab) >= 2 and focus in tab:
        print(f"  chi2 = {_chi2(tab):.2f}, df = {len(tab) - 1}"
              f"  |  {focus} vs rest, Fisher two-sided p = "
              f"{_fisher_vs_rest(tab, focus):.3f}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=25000)
    args = ap.parse_args()

    seen, asker, hops, first, last = collect(args.max)
    print(f"walked {hops} hops, {last} -> {first}")

    # The era comes from the label keys, so it cannot drift with the walk.
    ats = [k[2] for k in list(LABELS) + list(CONCUR_LABELS)]
    era_lo, era_hi = min(ats), max(ats)
    iso = lambda t: _dt.datetime.fromtimestamp(t, _dt.timezone.utc).isoformat()
    print(f"label era (from the label keys): {iso(era_lo)} -> {iso(era_hi)}")
    if first is None or _parse(last) > era_lo:
        print(f"  WARNING: the walk`s left edge ({last}) is INSIDE the era --"
              " deepen --max or the denominator is truncated.")
    seen = {k: v for k, v in seen.items() if era_lo <= k[2] <= era_hi}
    print(f"  factors inside the era: {len(seen)}")
    print(f"escalations opened in window with an asker: {len(asker)}")
    print(f"unique peer factors: {len(seen)}")
    print(f"asker census (all opened): {dict(Counter(asker.values()).most_common())}")

    # An escalation is REVIEWED if it drew at least one peer factor whose
    # opened-row we also saw, so numerator and denominator share a window.
    reviewed = defaultdict(set)
    for (eid, by, at) in seen:
        a = asker.get(eid)
        if a:
            reviewed[a].add(eid)

    rec_dissent = {k[0] for k, g in LABELS.items() if g == "record"}
    rec_concur = {k[0] for k, g in CONCUR_LABELS.items() if g != "none"}
    rec_any = rec_dissent | rec_concur
    any_dissent = {k[0] for k, f in seen.items() if f.get("dissent")}

    # An escalation with an UNREAD dissent cannot be scored either way: drop the
    # whole escalation from both numerator and denominator, and say how many.
    dropped = {k[0] for k, f in seen.items() if f.get("dissent") and k not in LABELS}
    noasker = {k[0] for k in seen if not asker.get(k[0])}
    for a in reviewed:
        reviewed[a] -= dropped
    print(f"dropped {len(dropped)} escalations carrying an unlabelled dissent;"
          f" {len(noasker)} escalations in the era have no opened row in the walk"
          " (their asker is unknown, so they are absent from every table below)")

    seats = sorted(reviewed)
    def tab(numer):
        return {s: (len(reviewed[s] & numer), len(reviewed[s] - numer)) for s in seats}

    _rate_table("A. RECORD DISSENT per REVIEWED escalation, by asker"
                " (kimi's class A, volume removed):", tab(rec_dissent))
    _rate_table("B. ANY dissent per REVIEWED escalation, by asker (the control:"
                " if B moves with A, the asker predicts dissent, not"
                " unreviewability):", tab(any_dissent))
    _rate_table("C. ANY record-obstacle factor per REVIEWED escalation, by asker"
                " (dissent + qualified + recovered -- reviewer idiom removed):",
                tab(rec_any))

    print("\nREVIEWER MIX per asker (the confound: codex files 95% of the same"
          "\nobstacle as dissent, kimi-code 35%, so who reviewed moves class A):")
    mix = defaultdict(Counter)
    for (eid, by, at) in seen:
        a = asker.get(eid)
        if a and eid not in dropped:
            mix[a][by] += 1
    for a in sorted(mix):
        tot = sum(mix[a].values())
        share = {b: f"{100.0 * n / tot:.0f}%" for b, n in mix[a].most_common()}
        print(f"  asked by {a:<12} n={tot:<4} reviewer share {share}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
