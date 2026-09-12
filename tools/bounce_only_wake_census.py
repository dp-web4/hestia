#!/usr/bin/env python3
"""How many wakes were bought entirely by this seat's own bounced mail?

A delivery failure is echoed back to the sender as an `#undelivered:fire-rc=N;why=...;via=watch-PEER`
pointer. Since #963 (merged 2026-09-06) that echo books no debt — `i_owe` is clean. It still
FIRES A WAKE. This counts the fires.

A primer is `bounce-only` when EVERY notice in it is such an echo: the seat woke, drained, and
no peer content was present. That is the unit of cost #963 did not address.

Normalize before concluding. The absolute count falls whenever total traffic falls, which is
what made the post-#963 drop look like a fix; per-primer SHARE is the honest statistic, and on
this box it did not fall. See findings/963-closed-the-debt-axis-not-the-fire-axis-2026-09-12.md.

Usage: bounce_only_wake_census.py [primer_glob] [--cut YYYY-MM-DD]
"""
import collections
import glob
import json
import sys

MARK = "#undelivered:"


def census(pattern):
    tot, bounce_only, any_bounce = (collections.Counter() for _ in range(3))
    why, via = collections.Counter(), collections.Counter()
    for path in glob.glob(pattern):
        try:
            notices = (json.load(open(path)) or {}).get("notices") or []
        except (OSError, ValueError):
            continue
        if not notices:
            continue
        day = min(n["queued_at"][:10] for n in notices)
        tot[day] += 1
        echoes = [n for n in notices if MARK in (n.get("pointer_uri") or "")]
        if not echoes:
            continue
        any_bounce[day] += 1
        if len(echoes) == len(notices):
            bounce_only[day] += 1
        for n in echoes:
            tail = n["pointer_uri"].split(MARK, 1)[1]
            for part in tail.split(";"):
                k, _, v = part.partition("=")
                (why if k == "why" else via if k == "via" else collections.Counter())[v] += 1
    return tot, bounce_only, any_bounce, why, via


def main():
    argv = sys.argv[1:]
    cut = None
    if "--cut" in argv:
        i = argv.index("--cut")
        cut = argv[i + 1] if i + 1 < len(argv) else None
        if cut is None:
            sys.exit("--cut needs a YYYY-MM-DD value")
        del argv[i:i + 2]
    positional = [a for a in argv if not a.startswith("--")]
    pattern = positional[0] if positional else "/home/dp/.claude/hestia-mesh-primers/*.json"
    tot, bo, ab, why, via = census(pattern)
    if not tot:
        sys.exit(f"no primers with notices matched {pattern}")

    def band(label, days):
        t, b, a = (sum(c[d] for d in days) for c in (tot, bo, ab))
        pct = lambda n: 100 * n / t if t else 0.0
        print(f"{label:16s} primers={t:5d}  bounce-only={b:4d} ({pct(b):5.1f}%)"
              f"  any-bounce={a:4d} ({pct(a):5.1f}%)")

    print(f"# {pattern}")
    if cut:
        band(f"pre  {cut}", [d for d in tot if d < cut])
        band(f"post {cut}", [d for d in tot if d >= cut])
    else:
        band("all", list(tot))
    print("\nwhy:", dict(why.most_common()))
    print("via:", dict(via.most_common()))
    print("\nper day (primers / bounce-only / any-bounce):")
    for d in sorted(tot):
        if bo[d] or ab[d]:
            print(f"  {d}  {tot[d]:4d}  {bo[d]:3d}  {ab[d]:3d}")


if __name__ == "__main__":
    main()
