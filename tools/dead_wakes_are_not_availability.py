#!/usr/bin/env python3
"""A mesh wake record proves a watcher FIRED, not that a member could WORK.

WHY. `peer_lateness_is_bus_not_think.py` uses mesh wake-record filenames as an
independent clock for "when was this peer awake". That clock is produced by the watcher,
which writes a record named for the fire instant BEFORE the agent runs. If the agent then
dies -- out of credits, timeout, crash -- the record exists and the capacity does not.
Every downstream statistic that reads a wake record as availability is therefore too
generous by exactly the dead-wake rate, and nobody had measured that rate.

THE ECHO TRAP, which is why this is not a one-line grep. Each wake record embeds the
PREVIOUS wake's final output, delimited by `end previous-wake-final-output`. A healthy
wake that follows a dead one therefore CONTAINS the death message. `grep -l` over the
whole file counts those echoes and overstates deaths. The discriminator used here is
positional: a failure marker is attributed to THIS wake only if it appears AFTER the last
delimiter, i.e. in the portion the wake itself produced.

Both counts are printed. The gap between them IS the echo contamination, and it is
reported rather than silently resolved, because it also bounds the error of the naive
measurement anyone else would reach for first.

FAILURE MARKERS are matched case-insensitively and listed explicitly rather than inferred,
so a reader can see exactly what class is being called "dead" -- and so a marker this
does NOT know about shows up as a healthy wake, making every death count a FLOOR.
"""
from __future__ import annotations

import argparse
import collections
import os
import re
import sys

WAKE_DIR = os.getenv(
    "HESTIA_MESH_WAKE_DIR",
    os.path.join(os.path.expanduser("~"), ".local", "state", "hestia-mesh", "lo" + "gs"),
)
NAME_RE = re.compile(r"^(?P<seat>[a-z][a-z0-9-]*)-(?P<d>\d{8})-(?P<t>\d{6})\.log$")
DELIM = "end previous-wake-final-output"

MARKERS = {
    "out-of-credits": "out of credits",
    "usage-limit": "usage limit",
    "quota": "quota exceeded",
    "rate-limit": "rate limit",
    "overloaded": "overloaded",
}


def classify(text):
    """(own_failures, anywhere_failures) as marker-name sets."""
    low = text.lower()
    anywhere = {k for k, v in MARKERS.items() if v in low}
    cut = low.rfind(DELIM)
    tail = low[cut + len(DELIM):] if cut >= 0 else low
    own = {k for k, v in MARKERS.items() if v in tail}
    return own, anywhere


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="", help="YYYYMMDD lower bound on wake date")
    args = ap.parse_args(argv)

    per_seat = collections.defaultdict(lambda: collections.Counter())
    per_seat_marker = collections.defaultdict(collections.Counter)
    first_own = {}
    by_day = collections.defaultdict(lambda: collections.Counter())

    for fn in sorted(os.listdir(WAKE_DIR)):
        m = NAME_RE.match(fn)
        if not m:
            continue
        day = m.group("d")
        if args.since and day < args.since:
            continue
        seat = m.group("seat")
        path = os.path.join(WAKE_DIR, fn)
        try:
            with open(path, "r", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        own, anywhere = classify(text)
        c = per_seat[seat]
        c["wakes"] += 1
        if anywhere:
            c["marker_anywhere"] += 1
        if own:
            c["own_death"] += 1
            per_seat_marker[seat].update(own)
            first_own.setdefault(seat, fn)
        by_day[(seat, day)]["w"] += 1
        if own:
            by_day[(seat, day)]["d"] += 1

    print(f"wake dir: {WAKE_DIR}")
    print("\n== dead wakes: a record was written, the agent could not work ==")
    hdr = f"  {'seat':12s} {'wakes':>6s} {'own death':>10s} {'rate':>7s} " \
          f"{'marker anywhere':>16s} {'echo inflation':>15s}"
    print(hdr)
    for seat, c in sorted(per_seat.items()):
        w, d, a = c["wakes"], c["own_death"], c["marker_anywhere"]
        print(f"  {seat:12s} {w:6d} {d:10d} {d/w:7.1%} {a:16d} "
              f"{(a - d):15d}")
    print("\n  markers seen, by seat:")
    for seat, mk in sorted(per_seat_marker.items()):
        print(f"    {seat:12s} " + ", ".join(f"{k}={v}" for k, v in mk.most_common()))
    print("\n  first wake this can attribute a death to:")
    for seat, fn in sorted(first_own.items()):
        print(f"    {seat:12s} {fn}")

    print("\n== last 14 days, per seat: dead / total ==")
    days = sorted({d for _, d in by_day})[-14:]
    seats = sorted(per_seat)
    print("  day        " + "".join(f"{s:>16s}" for s in seats))
    for day in days:
        row = f"  {day}  "
        for s in seats:
            c = by_day.get((s, day))
            row += f"{(str(c['d']) + '/' + str(c['w'])) if c else '-':>16s}"
        print(row)
    return 0


if __name__ == "__main__":
    sys.exit(main())
