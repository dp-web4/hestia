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

And every MEASURED cell carries `min_detectable_rate` = MIN_SPIKE_ROWS/n — what the floor
costs THAT cell. The floor is absolute in rows, so it buys blindness in inverse proportion
to traffic: 44% on a 45-row seat, 0.04% on a 45,000-row one. Live, full chain, the sharpest
specimen: seat `unattributed` on the escalation surface has 19 of its 29 rows at exactly 228
chars ENDING IN A CUT MARKER, and the cell printed `cut=0 (0.0%)` — one row under the floor.
Its true rate (>=65.5%) sits below its own sensitivity (69.0%), which is what makes that
zero forced rather than found. A measured zero that does not print this number is still the
sentence this file exists to abolish, one indirection further out.

And every cell — at any n — carries its `concentrations`: every length holding at least
CONCENTRATION_MIN_SHARE of the seat. That survives the floor, because a cap piles rows onto
one length no matter how thin the denominator: 16/16 at 240 is share 1.0 and screams at
n=16, where the spike test is structurally deaf. Reported as a SUSPICION with its thresholds
named, never folded into `cut_rate`. `ceiling` is kept as the descriptive special case (the
concentration at max_len), not as the test — see `concentrations()` for why the maximum is
the wrong thing to key on.

WHAT THE LENGTH-MODE TEST GETS WRONG, AND THE COLUMN THAT FIXES IT. A spelling-blind test
has exactly one false-positive class: a probe or watcher that emits ONE FIXED STRING on
every act piles it onto a single length in an empty neighbourhood, which is arithmetically
indistinguishable from a cap and reports a 100% cut rate for a seat that truncates nothing.
Both live instances (`gate-handshake-probe` n=50 at len 32, `gate-lock-probe` n=61 at len
20) were found by kimi-code on the first full-chain run of this driver — the review caught
the defect the design was always going to have. The discriminator needs no marker and was
already in the walked data: DISTINCT VALUES at that length. Measured, full chain: the probes
sit at 1 distinct value (ratio 0.02) and the live 240 cap at 5,710 over 6,127 rows (0.93).
Two orders of magnitude apart, so `CONSTANT_MAX_DISTINCT_RATIO` is not a delicate number.

A CAP IS A PROPERTY OF A SUB-POPULATION, NOT OF A SURFACE (kimi-code, PR #679). This seat's
`extract_target` caps only its `command` branch at 240; the `file_path`/`url` branch returns
the value UNCAPPED. So claude-code's `outcome.target` carries a max_len of 318 sitting ABOVE
a 240 cap that cuts 30.7% of the surface. Any test built on "a cap has an empty right tail"
— including the first draft of the ceiling test below — is therefore wrong on a mixed
surface, and live surfaces are mixed. What survives is the SHARE, unbound from the maximum:
`concentrations()` flags any length holding >=10% of a seat on >=2 rows, ceiling or not.

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

# Known cut markers, for LABELLING spikes only — never for finding them, and (see
# `demote_constants`) for REFUSING to call a repeated constant a cap. Order is immaterial:
# `…[truncated]` ends in `]`, so the bare `…` test can never swallow it. It was written
# "longest first" for a collision that does not exist; kept sorted only for reading.
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
CONCENTRATION_MIN_ROWS = 2
CONCENTRATION_MIN_SHARE = 0.10
# Back-compat aliases: the ceiling is one concentration (the one at max_len).
CEILING_MIN_ROWS = CONCENTRATION_MIN_ROWS
CEILING_MIN_SHARE = CONCENTRATION_MIN_SHARE

# A hard cap piles hundreds of DISTINCT acts onto one length. A bot repeating one fixed
# string piles one value there hundreds of times, and in a sparse neighbourhood that reads
# as a spike of ratio infinity. Measured on the full chain (kimi-code, PR #679 review):
# two probe seats spiked at 1 distinct value over 50 and 61 rows (ratio 0.02), while the
# live 240 cap held 5,710 distinct values over 6,127 rows (0.93). Two orders of magnitude,
# so the threshold is not delicate.
CONSTANT_MAX_DISTINCT_RATIO = 0.05

# How many flagged concentrations reach the human-readable line before it is truncated.
MAX_SUSPECTS_ON_A_LINE = 3


def marker_of(s: str) -> str:
    for name, mark in KNOWN_MARKERS:
        if s.endswith(mark):
            return name
    return "UNKNOWN_MARKER"


def find_spikes(lengths: Counter, factor: float, distinct: dict | None = None) -> list:
    """Lengths standing >= `factor` x the local background. Cap detection, spelling-blind.

    Background is the mean count over the 10 lengths on each side, excluding the
    candidate. A smooth distribution gives ratio ~1; a hard cap gives ratio in the
    hundreds. Nothing here knows what a cut looks like.

    THE BACKGROUND WINDOW IS TWO-SIDED AND A CAP'S RIGHT SIDE IS STRUCTURALLY EMPTY (kimi
    on PR #679): within a capped sub-population, lengths L+1..L+10 cannot exist, so `bg` is
    roughly halved and `ratio` roughly doubled at exactly the spikes this test is hunting.
    The direction favours detection, so nothing is hidden — but `--min-spike 20` is
    therefore doing about 10x of work at a boundary, and any recalibration of that factor
    must be done against a LEFT-ONLY window or it will silently move by 2x.

    `distinct` (length -> set of value hashes) adds the column that separates a cap from a
    bot repeating one fixed string; see `demote_constants`. It is optional so the histogram
    tests can drive this function with no values at all.
    """
    spikes = []
    for L, n in lengths.items():
        if n < MIN_SPIKE_ROWS:
            continue
        neigh = [lengths.get(x, 0) for x in range(L - 10, L + 11) if x != L]
        bg = sum(neigh) / len(neigh) if neigh else 0.0
        ratio = float("inf") if bg == 0 else n / bg
        if ratio >= factor:
            vals = (distinct or {}).get(L)
            k = len(vals) if vals is not None else None
            spikes.append({"length": L, "rows": n, "background": round(bg, 2),
                           "ratio": None if bg == 0 else round(ratio, 1),
                           "distinct": k,
                           "distinct_ratio": None if k is None else round(k / n, 3)})
    return sorted(spikes, key=lambda d: -d["rows"])


def demote_constants(spikes: list, markers_at: dict) -> tuple:
    """Split candidate spikes into caps and repeated constants. Returns (caps, demoted).

    The one false-positive class the length-mode test has: a probe or watcher emitting ONE
    fixed string on every act piles that string onto a single length in an otherwise empty
    neighbourhood — ratio infinity, rows over the floor, and a 100% "cut rate" for a seat
    that truncates nothing. Both live instances (`gate-handshake-probe` n=50 at len 32,
    `gate-lock-probe` n=61 at len 20) were found by kimi-code on the first full-chain run
    of this driver, which is where a spelling-blind test was always going to be weakest.

    The discriminator is already in the walked data and needs no marker: a cap collects
    DISTINCT values, a constant collects one. Demotion additionally requires that no known
    cut marker was read at that length. That marker read can only REFUSE a cap, never mint
    one, so the file's spelling-blindness is intact in the direction that matters —
    but it does mean a genuine cut CONSTANT (one long command, repeated, cut every time,
    ending in a marker nobody has catalogued) is demoted. That row is printed under
    `demoted_spikes` with its reason, never dropped.
    """
    caps, demoted = [], []
    for sp in spikes:
        k, dr = sp.get("distinct"), sp.get("distinct_ratio")
        marks = markers_at.get(sp["length"], {})
        known = [m for m in marks if m != "UNKNOWN_MARKER"]
        # `k == 1` is the sharp form and the only one that reaches a THIN candidate: a ratio
        # floor of 0.05 needs 20+ rows before one distinct value can clear it, and the share
        # test proposes candidates with as few as 2. Live: `conformance-runner-rust`, 14 rows
        # at length 12, ONE value -- ratio 0.07, over the floor, demoted only by `k == 1`.
        if (k == 1 or (dr is not None and dr <= CONSTANT_MAX_DISTINCT_RATIO)) and not known:
            demoted.append(dict(sp, demoted_because=(
                f"distinct_ratio {dr} <= {CONSTANT_MAX_DISTINCT_RATIO} and no known cut "
                f"marker at this length: a repeated constant, not a cap")))
        else:
            caps.append(sp)
    return caps, demoted


def _from(entries: list, source: str) -> list:
    """Tag demoted rows with which detector proposed them, so one printed DEMOTED clause
    can serve both and the reader still knows what was refused."""
    return [dict(e, proposed_by=source) for e in entries]


def concentrations(lengths: Counter, markers_at: dict, n: int,
                   distinct: dict | None = None) -> list:
    """Every length holding >= CONCENTRATION_MIN_SHARE of the seat on >= MIN_ROWS rows.

    This is the signal that survives `MIN_SPIKE_ROWS`, and it is the CEILING TEST WITH THE
    CEILING TAKEN OUT. The ceiling version — "a cap is the one length nothing can exceed,
    so look at max_len" — is true only inside the capped sub-population, and kimi's own
    correction on PR #679 shows live surfaces are MIXED: `extract_target` caps the
    `command` branch at 240 and returns the `file_path`/`url` branch UNCAPPED, so
    claude-code's `outcome.target` has a max_len of 318 sitting above a 240 cap that cuts
    ~31% of the surface. On that seat the spike test still finds the cap, so nothing was
    lost — but the ceiling test looks at 318 (3 rows, share ~0), flags nothing, and would
    have been the ONLY instrument on a cell of the same shape below the row floor.

    So the share test is unbound from max_len: a cap piles a large share onto ONE length
    whether or not anything sits above it. A suspicion with its thresholds named, never a
    count and never a rate.
    """
    if not lengths or not n:
        return []
    top = max(lengths)
    out = []
    for L, rows in lengths.items():
        share = rows / n
        if rows >= CONCENTRATION_MIN_ROWS and share >= CONCENTRATION_MIN_SHARE:
            vals = (distinct or {}).get(L)
            k = len(vals) if vals is not None else None
            out.append({"length": L, "rows": rows, "share": round(share, 4),
                        "markers": dict(markers_at.get(L, {})),
                        "distinct": k,
                        "distinct_ratio": None if k is None else round(k / rows, 3),
                        "is_ceiling": L == top})
    return sorted(out, key=lambda d: -d["rows"])


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


def seat_report(lengths: Counter, markers_at: dict, n: int, factor: float,
                distinct: dict | None = None) -> dict:
    """One (surface, seat) cell. Factored out of main() so the states are testable.

    The whole point of the split below: when a floor-clearing spike is IMPOSSIBLE, the
    count and the rate are `None`. `0` would be a claim about the surface; `None` is the
    truth about the instrument.

    `min_detectable_rate` finishes that job for the cells that ARE measured. The floor is
    absolute in rows, so on a seat of n rows no cap cutting less than MIN_SPIKE_ROWS/n of
    it can be seen at all — 44% on a 45-row seat, 0.04% on a 45,000-row one. kimi-code's
    escalation cell measured `0.0%` at n=45 while its true full-window rate was 24.8%: the
    zero was structurally forced, not bad luck, and the report that printed it owed the
    reader that number. It is the sensitivity of the instrument, printed beside its result.
    """
    spikes = find_spikes(lengths, factor, distinct)
    for sp in spikes:
        sp["markers"] = dict(markers_at.get(sp["length"], {}))
    spikes, demoted = demote_constants(spikes, markers_at)
    # The same false-positive class reaches the share test, and harder: below the row floor
    # the share test is the ONLY instrument, so an 11-row seat repeating one 12-char string
    # is a 100%-share "SUSPECT ceiling" with nothing else to contradict it. Live on the full
    # chain: three `conformance-runner*` seats. Both detectors get the same discriminator.
    cons, cons_demoted = demote_constants(
        concentrations(lengths, markers_at, n, distinct), markers_at)
    demoted = _from(demoted, "spike") + _from(cons_demoted, "concentration")

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
        # What the floor costs THIS cell, as a rate. `None` where no rate is expressible.
        "min_detectable_rate": round(MIN_SPIKE_ROWS / n, 4) if measured else None,
        "max_len": max(lengths) if lengths else None,
        "candidate_caps": spikes,
        "demoted_as_repeated_constants": demoted,
        "concentrations": cons,
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
        # A measured zero must carry the sensitivity that produced it, or it reads as
        # "this seat does not truncate" — the sentence this whole file exists to kill.
        if not s["rows_at_a_cap"]:
            caps += f" [floor: no cap under {100 * s['min_detectable_rate']:.1f}% is visible here]"
    else:
        cut = f"cut=   n/a [{s['state']}]"
    named = {c["length"] for c in s["candidate_caps"]}
    shown = [c for c in s.get("concentrations", []) if c["length"] not in named]
    suspect = "".join(
        f"  SUSPECT {'ceiling' if c['is_ceiling'] else 'concentration'} {c['length']} "
        f"({c['rows']}/{s['rows']} rows = {100 * c['share']:.0f}%, "
        f"{'/'.join(c['markers']) or 'no marker'})"
        for c in shown[:MAX_SUSPECTS_ON_A_LINE]
    )
    # A thin seat can put a dozen lengths over a 10% share, and a line nobody reads is the
    # same as no line. Truncated LOUDLY -- the count is the whole point, and the JSON holds
    # every row. (`concentrations` is sorted by rows, so the ones dropped are the smallest.)
    if len(shown) > MAX_SUSPECTS_ON_A_LINE:
        suspect += f"  (+{len(shown) - MAX_SUSPECTS_ON_A_LINE} more >={100 * CONCENTRATION_MIN_SHARE:.0f}% concentrations in the JSON)"
    # Both detectors can propose the same length, and both refusals are recorded in the
    # JSON. The line says it once.
    dem_seen, dem = set(), ""
    for c in s.get("demoted_as_repeated_constants", []):
        if c["length"] in dem_seen:
            continue
        dem_seen.add(c["length"])
        dem += (f"  DEMOTED {c['length']} ({c['rows']} rows, {c['distinct']} distinct value"
                f"{'' if c['distinct'] == 1 else 's'}: repeated constant, not a cap)")
    return f"{surface:42s} {pid:12s} n={s['rows']:6d} {cut}  caps: {caps}{suspect}{dem}"


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
    # surface -> plugin -> length -> set(value). The values THEMSELVES, not hashes: the
    # count is what separates a cap from a repeated constant, and a 64-bit hash would make
    # that count an estimate for no benefit worth arguing about. A set dedupes as it goes,
    # so this is bounded by DISTINCT act text on the walked surfaces, not by rows.
    distinct = defaultdict(lambda: defaultdict(lambda: defaultdict(set)))
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
        distinct[et][pid][len(val)].add(val)

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
                distinct[et].get(pid, {}),
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
          f"below the spike test's sensitivity on a seat of ANY size. Every measured zero "
          f"prints the rate that floor costs IT.)", file=sys.stderr)
    for surface, seats in report["surfaces"].items():
        for pid, s in sorted(seats.items()):
            print(summary_line(surface, pid, s), file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
