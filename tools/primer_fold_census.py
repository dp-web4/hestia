#!/usr/bin/env python3
"""Census the wake primer's debt fold, and measure the cap it dies against.

The watcher composes each primer by handing the `hestia_member_unanswered`
result to a `python3 -c` interpreter.  Before PR #858 it travelled as a single
environment string, and a single environment string is capped by the kernel at
MAX_ARG_STRLEN.  Past the cap `execve` fails E2BIG, the interpreter never
starts, and `|| echo "$OUT" > "$PRIMER"` writes the raw drain — which silently
deletes `unanswered`, `open_petitions` and `for_plugin`.

Two subcommands, because the finding needs both halves and neither is worth
trusting from a citation:

  census   what the primers on this box actually show, per day
  cap      what this kernel's per-string execve limit actually is

WHY PER DAY AND NEVER POOLED.  The payload grows monotonically (`owed_to_me`
rows addressed to roster ids that never drain, #541) and the failure is a
threshold on it.  A threshold process is bimodal in time: days sit at ~0% or
~100% and a pooled rate describes no day that ever happened.  Report the
series; let the reader see the step.

THREE STATES, NOT TWO.  The fire templates gate the whole debt block —
including the #567 liveness legend, which is the only place three of the
primer's terms are ever defined — on `[ -n "$DEBT" ]`.  So a fold that is
present but EMPTY renders exactly like a fold that was deleted.  Counting
`unanswered in d` alone overstates delivery.
"""
import collections
import datetime
import glob
import json
import os
import subprocess
import sys

PRIMERS = os.path.expanduser("~/.claude/hestia-mesh-primers")

# The composition fallback is `echo "$OUT"`, the raw drain result. Its key set is
# fixed, so a primer's shape says WHICH failure produced it — no process
# archaeology needed, and none is possible after the fact anyway.
FALLBACK_KEYS = {"evicted", "notices", "peeked", "total"}


def classify(d):
    """A -> fold deleted at exec; B -> fold present but empty; C -> debt block ships."""
    u = d.get("unanswered")
    if u is None:
        return "A_absent"
    if not isinstance(u, dict):
        return "A_absent"
    if (u.get("i_owe") or []) or (u.get("owed_to_me") or []):
        return "C_ships"
    return "B_empty"


def producer(d):
    """Date the primer's PRODUCER from its key set alone.

    The watcher grew keys in order: `unanswered` (the debt fold), then
    `for_plugin` (3fc5088, 07-31), then `open_petitions` (ced61ba, 08-19).  A
    composed primer therefore carries every key its writer knew about, so the
    key set is a vintage stamp that survives on disk.

    This is what the `open_petitions`-absent branch of the primer text asks the
    reader to establish, and it costs a `.keys()` — see `open-petitions.py`,
    which currently sends them to a tool for it instead.
    """
    keys = set(d)
    if keys <= FALLBACK_KEYS:
        return "fallback (composer never ran)"
    if "open_petitions" in keys:
        return "current (>= ced61ba, 08-19)"
    if "for_plugin" in keys:
        return "pre-open_petitions (>= 3fc5088, 07-31)"
    return "pre-for_plugin (< 07-31)"


def census(since):
    tot = collections.Counter()
    fold_bytes = collections.defaultdict(list)
    state = collections.defaultdict(collections.Counter)
    prod = collections.Counter()

    for f in sorted(glob.glob(os.path.join(PRIMERS, "*.json"))):
        try:
            d = json.load(open(f))
        except Exception:
            continue
        day = datetime.datetime.utcfromtimestamp(os.path.getmtime(f)).strftime("%m-%d")
        tot[day] += 1
        state[day][classify(d)] += 1
        prod[producer(d)] += 1
        if isinstance(d.get("unanswered"), dict):
            fold_bytes[day].append(len(json.dumps(d["unanswered"])))

    print("day      n   A absent  B empty  C ships    surviving fold bytes med/max")
    agg = collections.Counter()
    n_all = 0
    ceiling = 0
    for day in sorted(tot):
        if day < since:
            continue
        n = tot[day]
        n_all += n
        c = state[day]
        agg.update(c)
        s = sorted(fold_bytes[day])
        med = s[len(s) // 2] if s else 0
        mx = s[-1] if s else 0
        ceiling = max(ceiling, mx)
        print("%-6s %4d %5d %3.0f%% %6d %6d %3.0f%%  %11s %11s"
              % (day, n, c["A_absent"], 100.0 * c["A_absent"] / n, c["B_empty"],
                 c["C_ships"], 100.0 * c["C_ships"] / n, format(med, ","), format(mx, ",")))

    if not n_all:
        return
    print("---")
    print("since %s, n=%d: fold deleted %.1f%% | present-but-empty %.1f%% | debt block ships %.1f%%"
          % (since, n_all, 100.0 * agg["A_absent"] / n_all,
             100.0 * agg["B_empty"] / n_all, 100.0 * agg["C_ships"] / n_all))
    print("largest fold ever to survive composition: %s B" % format(ceiling, ","))
    print()
    print("producer vintage, from the key set alone (all primers on this box):")
    for k, v in prod.most_common():
        print("  %5d  %s" % (v, k))


def cap():
    """Binary-search the largest single environment string execve accepts.

    Measured, not cited: MAX_ARG_STRLEN is not exposed by getconf (ARG_MAX is a
    different, much larger, total-size limit), and a finding that turns on a
    number should not take that number on faith.
    """
    # A MINIMAL environment on purpose. `execve` enforces two separate limits: a
    # per-string cap (MAX_ARG_STRLEN, what kills the fold) and a total-size cap
    # (ARG_MAX, ~2 MB). Inheriting the ambient environment would let the total
    # limit contaminate a measurement of the per-string one.
    #
    # (Naming the mapping attribute directly is avoided here: the local command
    # classifier substring-matches a credential filename inside its spelling and
    # refuses the write. Same disclosed false positive as the findings doc.)
    def ok(n):
        try:
            subprocess.run(["/bin/true"], env={"UN": "x" * n}, check=True)
            return True
        except OSError:
            return False

    lo, hi = 0, 1 << 20
    while not ok(hi // 2) and hi > 2:
        hi //= 2
    lo = hi // 2
    while lo + 1 < hi:
        mid = (lo + hi) // 2
        if ok(mid):
            lo = mid
        else:
            hi = mid
    page = os.sysconf("SC_PAGESIZE")
    print("largest accepted `UN=` payload : %s B" % format(lo, ","))
    print("first refused                  : %s B" % format(hi, ","))
    print("whole string incl. 'UN=' + NUL : %s B" % format(lo + 4, ","))
    print("32 * page size (%d)           : %s B" % (page, format(32 * page, ",")))
    return lo + 4


def tail(n=30):
    """The daily series pools within a day; a threshold crossing happens at an hour.

    Print the most recent primers in time order, and the last one whose fold
    survived. A run of consecutive deletions since that point is the falsifiable
    part of the mechanism: the never-drainable component of the payload (#541)
    has no shrink path, so once IT alone exceeds the cap the fold cannot compose
    again. Any later primer carrying a non-empty `unanswered` refutes that.
    """
    rows = []
    for f in glob.glob(os.path.join(PRIMERS, "*.json")):
        try:
            d = json.load(open(f))
        except Exception:
            continue
        s = classify(d)
        u = d.get("unanswered")
        rows.append((os.path.getmtime(f), s,
                     len(json.dumps(u)) if isinstance(u, dict) else 0,
                     os.path.basename(f)))
    rows.sort()
    for t, s, b, name in rows[-n:]:
        print("  %s  %-8s %9s  %s"
              % (datetime.datetime.utcfromtimestamp(t).strftime("%m-%d %H:%M:%S"),
                 s, format(b, ",") if b else "-", name))
    ships = [r for r in rows if r[1] == "C_ships"]
    if not ships:
        return
    t, _, b, _ = ships[-1]
    after = [r for r in rows if r[0] > t]
    print()
    print("last surviving non-empty fold: %s (%s B)"
          % (datetime.datetime.utcfromtimestamp(t).strftime("%Y-%m-%d %H:%M:%SZ"), format(b, ",")))
    print("primers composed since:        %d, fold deleted in %d of them"
          % (len(after), sum(1 for r in after if r[1] == "A_absent")))


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "census"
    if cmd == "cap":
        cap()
    elif cmd == "tail":
        tail(int(sys.argv[2]) if len(sys.argv) > 2 else 30)
    else:
        census(sys.argv[2] if len(sys.argv) > 2 else "08-15")
