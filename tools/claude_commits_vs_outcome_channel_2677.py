#!/usr/bin/env python3
"""Score the witness chain's outcome channel against an INDEPENDENT witness: git.

The dispute over the 11-minute hole is about acts that succeeded but left no
`outcome` row. Every argument so far leans on one member's fire log -- a
self-report. Git is a second, non-hestia witness with its own clock: a commit
object's committer timestamp is durable proof that a `git commit` (a Bash act,
and Bash is the single best-covered tool in the outcome channel at 22,303 rows)
executed successfully at a known instant.

So: for every commit reachable in this repo inside the chain-walk span, ask
whether the outcome channel has a Bash row within +/- TOL seconds. That yields a
BASE RATE of witnessed-commits, against which the two suspect windows can be
scored. A base rate near 1.0 makes an unwitnessed commit a genuine anomaly; a low
base rate would mean the outcome channel never reliably witnessed commits and the
"hole" is just the ordinary texture of the channel.

Note the direction of error: this test is CONSERVATIVE about finding holes. Any
Bash row within tolerance counts as a witness even if it was a different command,
so the measured witness rate is an UPPER bound and true coverage is <= what it
reports.

Reads only.
"""
from __future__ import annotations

import subprocess
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from chain_walk import ChainWalker, payload  # noqa: E402

MAX = int(sys.argv[1]) if len(sys.argv) > 1 else 40000
TOL = int(sys.argv[2]) if len(sys.argv) > 2 else 60  # seconds either side

SUSPECT = [
    ("kimi's hole", datetime(2026, 8, 15, 22, 29, 5, tzinfo=timezone.utc),
     datetime(2026, 8, 15, 22, 40, 7, tzinfo=timezone.utc)),
    ("second window", datetime(2026, 8, 16, 4, 44, 37, tzinfo=timezone.utc),
     datetime(2026, 8, 16, 5, 8, 39, tzinfo=timezone.utc)),
]


def ts(entry):
    raw = (entry.get("timestamp") or entry.get("createdAt") or "").replace("Z", "+00:00")
    if not raw:
        return None
    try:
        d = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


# --- independent witness: every commit on every ref, with committer time in UTC ---
out = subprocess.run(
    ["git", "log", "--all", "--no-merges", "--pretty=%H%x09%cI%x09%s"],
    capture_output=True, text=True, check=True).stdout.splitlines()
commits = []
for line in out:
    sha, iso, subj = line.split("\t", 2)
    d = datetime.fromisoformat(iso).astimezone(timezone.utc)
    commits.append((d, sha[:7], subj[:60]))
commits.sort()

# --- the chain's outcome channel ---
w = ChainWalker()
bash_rows = []
all_rows = []
for e in w.walk(max_entries=MAX):
    et = e.get("eventType") or e.get("event_type")
    d = ts(e)
    if d is None:
        continue
    p = payload(e) or {}
    all_rows.append((d, et))
    if et == "outcome" and (p.get("tool_name") == "Bash"):
        bash_rows.append(d)
bash_rows.sort()
lo, hi = all_rows and min(r[0] for r in all_rows), all_rows and max(r[0] for r in all_rows)
print(f"chain span: {lo.isoformat()} .. {hi.isoformat()}")
print(f"Bash outcome rows: {len(bash_rows)}   commits (all refs): {len(commits)}")

in_span = [c for c in commits if lo <= c[0] <= hi]
print(f"commits inside chain span: {len(in_span)}   tolerance: +/-{TOL}s\n")


def witnessed(d):
    for b in bash_rows:
        if abs((b - d).total_seconds()) <= TOL:
            return True
        if b > d + timedelta(seconds=TOL):
            break
    return False


hits = [c for c in in_span if witnessed(c[0])]
rate = len(hits) / len(in_span) if in_span else 0.0
print("=== BASE RATE ===")
print(f"  commits with a Bash outcome row within +/-{TOL}s: "
      f"{len(hits)}/{len(in_span)} = {rate*100:.1f}%")
print("  (upper bound: any Bash row counts, not necessarily the commit's own)")

# per-day, to see whether coverage is stable or drifts
byday = Counter()
okday = Counter()
for c in in_span:
    byday[c[0].date()] += 1
    if witnessed(c[0]):
        okday[c[0].date()] += 1
print("\n  per-day witness rate:")
for day in sorted(byday):
    n, k = byday[day], okday[day]
    print(f"    {day}  {k:4d}/{n:4d}  {100.0*k/n:5.1f}%")

print("\n=== the suspect windows ===")
for name, a, b in SUSPECT:
    cs = [c for c in commits if a <= c[0] <= b]
    br = [x for x in bash_rows if a <= x <= b]
    print(f"\n  {name}: {a.strftime('%m-%d %H:%M:%S')} -> {b.strftime('%H:%M:%S')}Z")
    print(f"    commits landed in window : {len(cs)}")
    print(f"    Bash outcome rows in window: {len(br)}")
    for d, sha, subj in cs:
        mark = "WITNESSED" if witnessed(d) else "*** UNWITNESSED ***"
        print(f"      {d.strftime('%H:%M:%S')}Z {sha} {mark}  {subj}")
