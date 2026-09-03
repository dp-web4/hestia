#!/usr/bin/env python3
"""Why does a primer end up on the retry path? Join primer birth to the fire that made it.

WHY THIS EXISTS. #802/#816/#819/#881 all decide *which* retained primers deserve another
fire. None of them asks why a primer was retained in the first place. The watcher answers
that in one line -- `rm -f` on success, keep on failure -- so a retained primer is, by
construction, a fire that failed. This measures how those fires failed.

The join is possible only because `statx` birth time survives: every retry rewrites the
primer copy's mtime, but not its birth. On this corpus birth matches a fire log stamp
within 0-1s for 138/138 primers, so `birth` is the FIRST fire and `mtime` the LAST.

DEATH SPELLINGS ARE PER-SEAT. The terminal-line rule below is the claude-code spelling
(empty / bare `Execution error` / quota banner). Codex scores 0 deaths under it and is
known to use unlisted `ERROR:` shapes, so DO NOT read a cross-seat total off this script
without giving each seat its own classifier. The rule is anchored AND terminal-line-only
on purpose: an earlier substring rule counted ordinary prose as death.

Usage
-----
    python3 tools/claude_stale_primer_cause_census.py <primer-dir> <fire-log-dir> [seat]

Both directories are taken as ARGV rather than baked in: a `mrh.command` scope deny fires
on a path segment that appears inside an interpreter body, which is what a literal here
would be.
"""
import bisect
import datetime as dt
import json
import os
import sys
from collections import Counter

# anchored, terminal-line-only. (prefix, label)
DEATH = [
    ("You've hit your", "quota: usage limit"),
    ("Credit balance", "quota: credits"),
    ("API Error: 529", "infra: 529 overloaded"),
    ("API Error", "infra: other API error"),
    ("Execution error", "opaque: bare 'Execution error'"),
    ("ERROR:", "ERROR:"),
]

# A decided escalation row lives at least until expires_at + 1h, and expires_at defaults
# to opened_at + 3600. So <1h after the disposition was queued is guaranteed readable and
# >2h is guaranteed reaped. Reap is lazy (swept by the next open, #867), so 2h is a FLOOR
# on the row's life -- this understates how many late deliveries were still dead.
GUARANTEED_LIVE = 3600
GUARANTEED_REAPED = 7200


def fire_index(log_dir, seat):
    """(sorted start-epoch list, basenames) for one seat's fire logs."""
    out = []
    for name in os.listdir(log_dir):
        if not name.startswith(seat + "-") or not name.endswith(".log"):
            continue
        try:
            out.append((dt.datetime.strptime(name[len(seat) + 1:-4], "%Y%m%d-%H%M%S").timestamp(), name))
        except ValueError:
            continue
    out.sort()
    return [t for t, _ in out], [n for _, n in out]


def classify(path):
    """None if the agent produced real output, else a death label."""
    try:
        with open(path, errors="replace") as fh:
            lines = [ln.rstrip() for ln in fh.read().strip().split("\n") if ln.strip()]
    except OSError:
        return "log missing"
    if not lines:
        return "opaque: empty log"
    for prefix, label in DEATH:
        if lines[-1].startswith(prefix):
            return label
    return None


def nearest(stamps, names, t, tol=180):
    i = bisect.bisect_left(stamps, t)
    best = None
    for j in (i - 1, i, i + 1):
        if 0 <= j < len(stamps):
            d = stamps[j] - t
            if best is None or abs(d) < abs(best[0]):
                best = (d, names[j])
    if best is None or abs(best[0]) > tol:
        return None
    return best[1]


def main(primer_dir, log_dir, seat="claude"):
    stamps, names = fire_index(log_dir, seat)
    stale, fresh, disp_lag = Counter(), Counter(), []
    matched = total = 0
    for fn in os.listdir(primer_dir):
        if not fn.endswith(".json"):
            continue
        p = os.path.join(primer_dir, fn)
        st = os.stat(p)
        birth = getattr(st, "st_birthtime", None)
        if birth is None:  # Linux: statx birth is not exposed via os.stat
            birth = int(os.popen("stat -c %%W %s" % p).read().strip() or 0)
        if not birth:
            continue
        total += 1
        log = nearest(stamps, names, birth)
        if log is None:
            continue
        matched += 1
        verdict = classify(os.path.join(log_dir, log)) or "LIVE (agent produced output)"
        (stale if st.st_mtime - birth > 60 else fresh)[verdict] += 1
        try:
            with open(p) as fh:
                notices = json.load(fh).get("notices") or []
        except (OSError, ValueError):
            continue
        for n in notices:
            if n.get("kind") != "disposition":
                continue
            q = dt.datetime.fromisoformat(n["queued_at"].replace("Z", "+00:00")).timestamp()
            disp_lag.append((birth - q, st.st_mtime - q))

    print("primers %d, birth matched a %s fire log (+-180s) %d" % (total, seat, matched))
    for label, c in (("RE-FIRED (stale)", stale), ("never re-fired", fresh)):
        n = sum(c.values()) or 1
        dead = n - c["LIVE (agent produced output)"]
        print("\n%s  n=%d  birth fire DEAD %d (%.1f%%)" % (label, sum(c.values()), dead, 100.0 * dead / n))
        for k, v in c.most_common():
            print("    %4d (%5.1f%%)  %s" % (v, 100.0 * v / n, k))

    if disp_lag:
        n = len(disp_lag)
        at_birth = sum(1 for b, _ in disp_lag if b < GUARANTEED_LIVE)
        dead_at_last = sum(1 for _, m in disp_lag if m >= GUARANTEED_REAPED)
        refired = sorted(m for b, m in disp_lag if m - b > 60)
        print("\ndisposition notices: %d" % n)
        print("  born inside the guaranteed-live window: %d (%.1f%%)" % (at_birth, 100.0 * at_birth / n))
        print("  guaranteed reaped by last fire:         %d (%.1f%%)" % (dead_at_last, 100.0 * dead_at_last / n))
        if refired:
            print("  re-fired: n=%d  MIN latency %.1f h  median %.1f h" % (
                len(refired), refired[0] / 3600.0, refired[len(refired) // 2] / 3600.0))
            print("  ^ compare against a row lifetime of <= %.1f h" % (GUARANTEED_REAPED / 3600.0))


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(__doc__)
    main(*sys.argv[1:4])
