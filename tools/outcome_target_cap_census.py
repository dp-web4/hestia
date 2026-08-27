#!/usr/bin/env python3
"""Find every place the chain cuts an act — by LENGTH-MODE, not by marker spelling.

WHY THIS EXISTS. Between 2026-08-25 and 2026-08-27 three members ran truncation
censuses on the escalation surface and each published a per-seat ZERO that was a claim
about their own regex:

  * claude-code matched `" …"` and read 220-char cuts. It scored codex and kimi-code at
    zero and published "claude-code is the only seat still truncating."
  * codex and kimi-code matched `"…[truncated]"` and read 400-char cuts. They scored
    claude-code's rows as uncut.
  * Nobody matched `"..."`, and so nobody saw the 240-char cap on `outcome.target` —
    35% of 18,706 rows, the fleet's largest evidence body (2026-08-27).

The failure is structural, not careless: a spelling-keyed search cannot return an error.
It returns a clean zero, which reads exactly like "this seat does not truncate."

SO THIS DRIVER DOES NOT LEAD WITH MARKERS. A hard cap leaves a signature that survives
not knowing its spelling: an impossible SPIKE in the length histogram. Real commands are
distributed smoothly over length; a cap piles hundreds of distinct commands onto one
exact value. `--min-spike` controls how many times the local background a length must
stand at before it is reported as a candidate cap. Markers are then read OFF the rows at
that length and reported as evidence, in whatever spelling they turn out to be. A cap
whose marker nobody has seen before is therefore still found, and names itself.

WHAT A CAP COSTS. The cut text is not recoverable from the chain. `act_digest` binds the
RENDERING (sha256(stated_reason), verified 125/125, PR #677), so a digest over a cut act
certifies only the visible prefix; attaching the full act afterwards is prefix-verified
and tail-asserted, never bound. That is why a cap is a governance defect and not a
display preference: it removes the reviewed half of the record from binding, permanently.

SURFACES. `outcome.target` (acts that RAN) and `gate_escalation_opened.stated_reason`
(acts that were REFUSED, i.e. the reviewed population) are censused together, because
the asymmetry between them is a finding: on 2026-08-27 the refused act carried the
SHORTER cap (220) and had no second witness at all, while the executed act carried 240.
Redundancy runs opposite to review need.

WHAT THIS DRIVER CANNOT SEE, SAID OUT LOUD. The spike test carries an ABSOLUTE row
floor (`MIN_SPIKE_ROWS`), and the first version of this file let that floor manufacture
the very artefact the file exists to abolish: a seat with 16 rows, ALL 16 at a genuine
240-char cap, reported `rows_at_a_cap: 0`, `cut_rate: 0.0`, `caps: none` — a clean zero,
produced by arithmetic rather than by measurement, indistinguishable in the report from a
seat that does not truncate. Found by codex on PR #679, not by the author.

So a zero is no longer a scalar here. Every (surface, seat) cell carries a `state`:

  * `measured`            — n >= MIN_SPIKE_ROWS. `cut_rate` is a real measurement, and a
                            FLOOR: a cap catching fewer than MIN_SPIKE_ROWS rows in this
                            window is below the detector's sensitivity and is not counted.
  * `insufficient_sample` — n < MIN_SPIKE_ROWS. A floor-clearing spike is IMPOSSIBLE, so
                            `rows_at_a_cap` and `cut_rate` are `null`, never `0`.
  * `no_rows`             — the seat appears in the walked chain but wrote nothing to this
                            surface in this window. Emitted explicitly, because a seat
                            missing from a per-seat table reads as a seat that is fine.

And every cell — at any n — carries its `ceiling`: the longest value observed, how many
rows sit on exactly that length, and their share. That one number survives the floor. A
hard cap is the one thing nothing can exceed, so it piles rows onto the ceiling: 16/16 at
240 is share 1.0 and screams at n=16, where the spike test is structurally deaf. An
uncapped surface puts one row on its ceiling. `ceiling.flags_cap` is reported as a
SUSPICION with its threshold named, never folded into `cut_rate`.

Usage:
    python3 outcome_target_cap_census.py [--max N] [--min-spike F] [--out report.json]
Reads via chain_walk.ChainWalker (the one correct reader — see its docstring for the
four traps in hestia_query_history that return plausible wrong answers).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chain_walk import ChainWalker, payload  # noqa: E402

# (eventType, field) pairs that carry an act. Add a row here, not a special case below.
SURFACES = (
    ("outcome", "target"),
    ("gate_escalation_opened", "stated_reason"),
)

# Known cut markers, for LABELLING spikes only — never for finding them. Longest first
# so `…[truncated]` is not swallowed by the bare `…` test.
KNOWN_MARKERS = (
    ("trunc_bracket", "…[truncated]"),
    ("ellipsis_sp", " …"),
    ("ellipsis", "…"),
    ("dots3", "..."),
)

# A spike must also clear this absolute count, so a 3-row seat cannot mint a "cap".
# It is ABSOLUTE, not a share of n: its blind region therefore scales with nothing, and a
# cap catching fewer than this many rows is invisible on a seat of ANY size. That bound is
# published as `detection_floor_rows` rather than hidden inside a zero.
MIN_SPIKE_ROWS = 20

# Below the floor the spike test is deaf, so the ceiling is what is left. A cap is the one
# length nothing can exceed, so it piles rows onto max_len; an uncapped surface leaves one
# row there. These two thresholds gate a SUSPICION only -- never a count, never a rate.
CEILING_MIN_ROWS = 2
CEILING_MIN_SHARE = 0.10


def marker_of(s: str) -> str:
    for name, mark in KNOWN_MARKERS:
        if s.endswith(mark):
            return name
    return "UNKNOWN_MARKER"


def find_spikes(lengths: Counter, factor: float) -> list:
    """Lengths standing >= `factor` x the local background. Cap detection, spelling-blind.

    Background is the mean count over the 10 lengths on each side, excluding the
    candidate. A smooth distribution gives ratio ~1; a hard cap gives ratio in the
    hundreds. Nothing here knows what a cut looks like.
    """
    spikes = []
    for L, n in lengths.items():
        if n < MIN_SPIKE_ROWS:
            continue
        neigh = [lengths.get(x, 0) for x in range(L - 10, L + 11) if x != L]
        bg = sum(neigh) / len(neigh) if neigh else 0.0
        ratio = float("inf") if bg == 0 else n / bg
        if ratio >= factor:
            spikes.append({"length": L, "rows": n, "background": round(bg, 2),
                           "ratio": None if bg == 0 else round(ratio, 1)})
    return sorted(spikes, key=lambda d: -d["rows"])


def ceiling_of(lengths: Counter, markers_at: dict, n: int) -> dict | None:
    """The longest value seen, and how much of the seat piles onto exactly that length.

    This is the signal that survives `MIN_SPIKE_ROWS`. It knows nothing about markers and
    nothing about row counts in the absolute -- only that a hard cap is the one length
    nothing can exceed, so it collects rows at max_len while a smooth distribution leaves
    a singleton there. `flags_cap` names its own thresholds and is a suspicion, not a
    measurement: it is never added to `rows_at_a_cap` and never moves `cut_rate`.
    """
    if not lengths or not n:
        return None
    L = max(lengths)
    rows = lengths[L]
    share = rows / n
    return {
        "length": L,
        "rows": rows,
        "share": round(share, 4),
        "markers": dict(markers_at.get(L, {})),
        "flags_cap": rows >= CEILING_MIN_ROWS and share >= CEILING_MIN_SHARE,
        "flags_cap_thresholds": {"min_rows": CEILING_MIN_ROWS,
                                 "min_share": CEILING_MIN_SHARE},
    }


def seat_report(lengths: Counter, markers_at: dict, n: int, factor: float) -> dict:
    """One (surface, seat) cell. Factored out of main() so the states are testable.

    The whole point of the split below: when a floor-clearing spike is IMPOSSIBLE, the
    count and the rate are `None`. `0` would be a claim about the surface; `None` is the
    truth about the instrument.
    """
    spikes = find_spikes(lengths, factor)
    for sp in spikes:
        sp["markers"] = dict(markers_at.get(sp["length"], {}))

    if n == 0:
        state = "no_rows"
    elif n < MIN_SPIKE_ROWS:
        state = "insufficient_sample"
    else:
        state = "measured"

    measured = state == "measured"
    cut_rows = sum(sp["rows"] for sp in spikes) if measured else None
    return {
        "state": state,
        "rows": n,
        "rows_at_a_cap": cut_rows,
        "cut_rate": round(cut_rows / n, 4) if measured else None,
        "cut_rate_is_a_floor": True,
        "detection_floor_rows": MIN_SPIKE_ROWS,
        "max_len": max(lengths) if lengths else None,
        "candidate_caps": spikes,
        "ceiling": ceiling_of(lengths, markers_at, n),
    }


def summary_line(surface: str, pid: str, s: dict) -> str:
    """The one line a notice would quote. It must not be quotable as a zero.

    `cut=` prints `n/a` in every state where the count is not a measurement, and the
    ceiling is appended whenever it is flagged, so the 16/16-at-240 cell reads as a
    suspected cap on a thin denominator instead of as `cut=0 (0.0%) caps: none`.
    """
    caps = ", ".join(
        f"{c['length']}({c['rows']} rows, {'/'.join(c['markers'])})"
        for c in s["candidate_caps"]
    ) or "none"
    if s["state"] == "measured":
        cut = f"cut={s['rows_at_a_cap']:6d} ({100 * s['cut_rate']:.1f}%)"
    else:
        cut = f"cut=   n/a [{s['state']}]"
    ceil = s.get("ceiling")
    suspect = ""
    if ceil and ceil["flags_cap"] and not any(
        c["length"] == ceil["length"] for c in s["candidate_caps"]
    ):
        suspect = (f"  SUSPECT ceiling {ceil['length']} "
                   f"({ceil['rows']}/{s['rows']} rows = {100 * ceil['share']:.0f}%, "
                   f"{'/'.join(ceil['markers']) or 'no marker'})")
    return f"{surface:42s} {pid:12s} n={s['rows']:6d} {cut}  caps: {caps}{suspect}"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=200_000)
    ap.add_argument("--min-spike", type=float, default=20.0)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    # surface -> plugin -> Counter(length)
    lengths = defaultdict(lambda: defaultdict(Counter))
    # surface -> plugin -> length -> Counter(marker)
    markers = defaultdict(lambda: defaultdict(lambda: defaultdict(Counter)))
    totals = defaultdict(Counter)
    want = {t: f for t, f in SURFACES}
    # Every plugin_id seen ANYWHERE in the walk. A seat that wrote nothing to a surface is
    # absent from that surface's Counter, and a seat missing from a per-seat table reads
    # as a seat that is fine -- the same absence-as-OK shape one level up from the floor.
    # This set is what lets the report say `no_rows` out loud.
    seen_plugins = set()
    first_ts = last_ts = None
    walked = 0

    for e in ChainWalker().walk(max_entries=args.max):
        walked += 1
        ts = e.get("timestamp") or ""
        if ts:
            if first_ts is None:
                first_ts = ts
            last_ts = ts
        d = payload(e)
        if isinstance(d, dict) and isinstance(d.get("plugin_id"), str):
            seen_plugins.add(d["plugin_id"])
        et = e.get("eventType")
        if et not in want:
            continue
        val = d.get(want[et])
        if not isinstance(val, str) or not val:
            continue
        pid = d.get("plugin_id") or "<<none>>"
        totals[et][pid] += 1
        lengths[et][pid][len(val)] += 1
        markers[et][pid][len(val)][marker_of(val)] += 1

    report = {
        "walked_entries": walked,
        "span_newest": first_ts,
        "span_oldest": last_ts,
        "min_spike_factor": args.min_spike,
        "min_spike_rows": MIN_SPIKE_ROWS,
        "plugins_seen_in_walk": sorted(seen_plugins),
        "surfaces": {},
    }

    for et, field in SURFACES:
        seats = {}
        # Union, not just the seats that wrote here: `no_rows` must be a printed state.
        for pid in sorted(seen_plugins | set(lengths[et])):
            seats[pid] = seat_report(
                lengths[et].get(pid, Counter()),
                markers[et].get(pid, {}),
                totals[et][pid],
                args.min_spike,
            )
        report["surfaces"][f"{et}.{field}"] = seats

    print(json.dumps(report, indent=2, sort_keys=True))
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(report, fh, indent=2, sort_keys=True)
        print(f"\nwrote {args.out}", file=sys.stderr)

    # Loud, human-readable summary — the numbers a notice would quote.
    print("\n=== candidate caps, spelling-blind ===", file=sys.stderr)
    print(f"(cut_rate is a FLOOR: a cap holding <{MIN_SPIKE_ROWS} rows in this window is "
          f"below the spike test's sensitivity on a seat of ANY size)", file=sys.stderr)
    for surface, seats in report["surfaces"].items():
        for pid, s in sorted(seats.items()):
            print(summary_line(surface, pid, s), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
