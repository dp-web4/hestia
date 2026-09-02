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
whole file counts those echoes and overstates deaths. Only the text after the last
delimiter was produced by this wake.

THE PROSE TRAP (codex, review 7765), which is why the first version of this file was
wrong. The v1 rule was "a failure marker appears anywhere in the wake's own output". A
healthy wake that DISCUSSES a peer being out of credits, or a design table that says
"usage limits are our safeguard", or a `grep -qi 'out of credits\\|usage limit'` in a
diff, all matched. Measured on 2,852 records (2026-09-02): claude 35 of 38 v1 "deaths"
were prose; codex 39 of 376; kimi 53 of 302. And the mirror error: 112 codex wakes end
in an anchored `ERROR:` line whose text is on no marker list (model not found, missing
bearer token, ...) and v1 scored every one of them HEALTHY. v1 over-counted one seat by
12x and under-counted another by a quarter. Its "every count is a FLOOR" was false.

THE RULE NOW is positional twice over. A wake is dead when, after dropping the vendor
footer lines that follow a fatal error (codex prints `tokens used` and a count; kimi
prints `See log: ...`), the LAST non-blank line of the wake's own output is an anchored
error line -- `ERROR:`, `error:`, `API Error:` at column 0. A wake that quotes such a
line in a code block and then goes on to publish a final answer is not dead; its last
line is the answer. The marker list now only NAMES the death class; an anchored terminal
error with no known marker is still a death, reported as `terminal-error-unclassified`
so a new vendor spelling shows up as a count, not as a healthy wake.

WHAT THIS STILL CANNOT SEE. The record carries no exit code: the fire scripts print
`done rc=N` to the watcher's journal, not to the record. A wake killed by `timeout`
mid-sentence, or one whose provider error is printed in a shape not anchored at column
0, scores healthy. The precision of the terminal rule was checked by hand on every
disagreement with the v1 rule on this seat's 2,852 records (`--audit` prints them so a
second seat can repeat the check); its recall against a ground truth nobody has recorded
is unmeasured. Do not quote these rates without that sentence.

THE CURRENTLY OPEN RECORD is the wake that is running this script. It has no last line
yet. Records whose mtime is younger than the fire timeout are reported as `open` and
left out of every rate.
"""
from __future__ import annotations

import argparse
import collections
import os
import re
import sys
import time

WAKE_DIR = os.getenv(
    "HESTIA_MESH_WAKE_DIR",
    os.path.join(os.path.expanduser("~"), ".local", "state", "hestia-mesh", "lo" + "gs"),
)
NAME_RE = re.compile(r"^(?P<seat>[a-z][a-z0-9-]*)-(?P<d>\d{8})-(?P<t>\d{6})\.log$")
DELIM = "end previous-wake-final-output"

#: Names the death class. Presence of one of these is NOT what makes a wake dead any more
#: (see THE PROSE TRAP); an anchored terminal error line is. Kept explicit so a reader can
#: see what is being called what.
MARKERS = {
    "out-of-credits": "out of credits",
    "usage-limit": "usage limit",
    "quota": "quota exceeded",
    "rate-limit": "rate limit",
    "overloaded": "overloaded",
}
UNCLASSIFIED = "terminal-error-unclassified"

#: Column-0 error shapes observed at the end of dead wakes, one per vendor CLI:
#: codex `ERROR: ...`, kimi `error: failed to run prompt: ...`, claude `API Error: 529 ...`.
ERROR_LINE_RE = re.compile(r"^(api )?error:", re.IGNORECASE)

#: Lines a vendor CLI prints AFTER its fatal error. Stripped from the end before the last
#: line is read. codex: `tokens used` then a bare count; kimi: `See log: <path>`.
FOOTER_RE = re.compile(r"^(tokens used|[\d,]+|see log: .*)$", re.IGNORECASE)

#: `timeout -k 30 1800` in every fire script. A record younger than this may still be
#: being written.
FIRE_TIMEOUT_SECS = 1800 + 30


def own_output(text):
    """The part of a record this wake produced: everything after the last echo delimiter."""
    cut = text.rfind(DELIM)
    return text[cut + len(DELIM):] if cut >= 0 else text


def terminal_line(own):
    """Last non-blank line of the wake's own output, vendor footers removed."""
    lines = [l.strip() for l in own.splitlines() if l.strip()]
    while lines and FOOTER_RE.match(lines[-1]):
        lines.pop()
    return lines[-1] if lines else ""


def classify(text):
    """Return a dict describing one record.

    dead            bool   -- terminal rule: last own line is an anchored error line
    death_class     str    -- a MARKERS key, UNCLASSIFIED, or None
    terminal        str    -- the line the verdict was read from (for audit)
    v1_own          set    -- v1 rule: markers anywhere in own output (kept for comparison)
    anywhere        set    -- markers anywhere in the file, echo included
    """
    low = text.lower()
    anywhere = {k for k, v in MARKERS.items() if v in low}
    own = own_output(text)
    v1_own = {k for k, v in MARKERS.items() if v in own.lower()}
    last = terminal_line(own)
    dead = bool(ERROR_LINE_RE.match(last))
    death_class = None
    if dead:
        named = [k for k, v in MARKERS.items() if v in last.lower()]
        death_class = named[0] if named else UNCLASSIFIED
    return {"dead": dead, "death_class": death_class, "terminal": last,
            "v1_own": v1_own, "anywhere": anywhere}


def wake_died(path, rule="terminal"):
    """Predicate shared with `peer_lateness_is_bus_not_think.py` (one body, not two).

    rule="terminal" is the current rule; rule="substring" is v1, kept ONLY so the
    published 2026-08-31 numbers can be reproduced and their error stated.
    """
    try:
        with open(path, "r", errors="replace") as fh:
            c = classify(fh.read())
    except OSError:
        return False
    if rule == "substring":
        return bool(c["v1_own"])
    if rule != "terminal":
        raise ValueError("unknown dead-wake rule: %r" % (rule,))
    return c["dead"]


def is_open(path, now=None):
    now = time.time() if now is None else now
    try:
        return (now - os.path.getmtime(path)) < FIRE_TIMEOUT_SECS
    except OSError:
        return False


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="", help="YYYYMMDD lower bound on wake date")
    ap.add_argument("--until", default="",
                    help="YYYYMMDD-HHMMSS upper bound on the record NAME, so a historical "
                         "snapshot can be re-selected exactly (codex review 7765, item 4)")
    ap.add_argument("--audit", action="store_true",
                    help="print every record where the terminal rule and the v1 substring "
                         "rule disagree, with the line each read -- the precision check")
    args = ap.parse_args(argv)

    per_seat = collections.defaultdict(collections.Counter)
    per_seat_class = collections.defaultdict(collections.Counter)
    first_dead = {}
    by_day = collections.defaultdict(collections.Counter)
    disagreements = []

    for fn in sorted(os.listdir(WAKE_DIR)):
        m = NAME_RE.match(fn)
        if not m:
            continue
        day = m.group("d")
        if args.since and day < args.since:
            continue
        stamp = day + "-" + m.group("t")
        if args.until and stamp > args.until:
            continue
        seat = m.group("seat")
        path = os.path.join(WAKE_DIR, fn)
        if is_open(path):
            per_seat[seat]["open"] += 1
            continue
        try:
            with open(path, "r", errors="replace") as fh:
                c = classify(fh.read())
        except OSError:
            per_seat[seat]["unreadable"] += 1
            continue
        per_seat[seat]["wakes"] += 1
        by_day[day][seat + ":wakes"] += 1
        if c["dead"]:
            per_seat[seat]["dead"] += 1
            per_seat_class[seat][c["death_class"]] += 1
            by_day[day][seat + ":dead"] += 1
            first_dead.setdefault(seat, fn)
        if c["v1_own"]:
            per_seat[seat]["v1_substring_own"] += 1
        if c["anywhere"]:
            per_seat[seat]["marker_anywhere"] += 1
        if c["dead"] != bool(c["v1_own"]):
            kind = "v1-only(prose)" if c["v1_own"] else "terminal-only(missed by v1)"
            per_seat[seat][kind] += 1
            disagreements.append((fn, kind, c["terminal"][:140]))

    print("wake records under %s%s%s" % (
        WAKE_DIR, (" since " + args.since) if args.since else "",
        (" until " + args.until) if args.until else ""))
    print("\n  %-8s %6s %6s %7s | %6s %6s | %8s %8s | %5s" % (
        "seat", "wakes", "dead", "rate", "v1own", "anywh", "v1-only", "term-only", "open"))
    for seat in sorted(per_seat):
        c = per_seat[seat]
        n = c["wakes"]
        rate = ("%.1f%%" % (100.0 * c["dead"] / n)) if n else "-"
        print("  %-8s %6d %6d %7s | %6d %6d | %8d %8d | %5d" % (
            seat, n, c["dead"], rate, c["v1_substring_own"], c["marker_anywhere"],
            c["v1-only(prose)"], c["terminal-only(missed by v1)"], c["open"]))
    print("\n  v1-only = v1 called it dead, the terminal rule does not (prose hits);"
          "\n  term-only = terminal rule calls it dead, v1 scored it healthy (unlisted shapes).")

    print("\n  death classes, by seat:")
    for seat in sorted(per_seat_class):
        print("    %-8s %s" % (seat, dict(per_seat_class[seat].most_common())))

    print("\n  first dead wake per seat:")
    for seat in sorted(first_dead):
        print("    %-8s %s" % (seat, first_dead[seat]))

    days = sorted(by_day)[-14:]
    if days:
        print("\n  last %d days (dead/wakes):" % len(days))
        seats = sorted(per_seat)
        print("    %-8s " % "day" + " ".join("%12s" % s for s in seats))
        for d in days:
            c = by_day[d]
            print("    %-8s " % d + " ".join(
                "%12s" % ("%d/%d" % (c[s + ":dead"], c[s + ":wakes"])) for s in seats))

    if args.audit:
        print("\n  disagreements (%d):" % len(disagreements))
        for fn, kind, last in disagreements:
            print("    %-30s %-28s | %s" % (fn, kind, last))
    return 0


if __name__ == "__main__":
    sys.exit(main())
