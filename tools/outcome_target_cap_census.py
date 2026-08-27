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
MIN_SPIKE_ROWS = 20


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
    first_ts = last_ts = None
    walked = 0

    for e in ChainWalker().walk(max_entries=args.max):
        walked += 1
        ts = e.get("timestamp") or ""
        if ts:
            if first_ts is None:
                first_ts = ts
            last_ts = ts
        et = e.get("eventType")
        if et not in want:
            continue
        d = payload(e)
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
        "surfaces": {},
    }

    for et, field in SURFACES:
        seats = {}
        for pid, lc in lengths[et].items():
            spikes = find_spikes(lc, args.min_spike)
            for sp in spikes:
                sp["markers"] = dict(markers[et][pid][sp["length"]])
            cut_rows = sum(sp["rows"] for sp in spikes)
            n = totals[et][pid]
            seats[pid] = {
                "rows": n,
                "rows_at_a_cap": cut_rows,
                "cut_rate": round(cut_rows / n, 4) if n else None,
                "max_len": max(lc) if lc else None,
                "candidate_caps": spikes,
            }
        report["surfaces"][f"{et}.{field}"] = seats

    print(json.dumps(report, indent=2, sort_keys=True))
    if args.out:
        with open(args.out, "w") as fh:
            json.dump(report, fh, indent=2, sort_keys=True)
        print(f"\nwrote {args.out}", file=sys.stderr)

    # Loud, human-readable summary — the numbers a notice would quote.
    print("\n=== candidate caps, spelling-blind ===", file=sys.stderr)
    for surface, seats in report["surfaces"].items():
        for pid, s in sorted(seats.items()):
            caps = ", ".join(
                f"{c['length']}({c['rows']} rows, {'/'.join(c['markers'])})"
                for c in s["candidate_caps"]
            ) or "none"
            print(f"{surface:42s} {pid:12s} n={s['rows']:6d} "
                  f"cut={s['rows_at_a_cap']:6d} ({100*(s['cut_rate'] or 0):.1f}%)  caps: {caps}",
                  file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
