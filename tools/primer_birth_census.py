#!/usr/bin/env python3
"""Date a wake primer by its filesystem BIRTH time, not by its key set.

Why this exists
---------------
`findings/refire-contaminates-the-primer-series-2026-09-03.md` dated a primer's
producer from its key set, and endorsed the wake banner's inference that a
missing `open_petitions` key means "its producer predates the petitions fold
(2026-08-19)".  That held for the specimen it was written from (`4ur02s`, born
08-18).  It does not hold in general, and this tool is the falsifier.

Two facts it measures, over the whole primary store rather than one file:

  1. `open_petitions` is present in 1 of 923 primers, born 2026-09-02.  Primers
     born 09-02 and 09-03 lack it too, so its ABSENCE dates nothing.
  2. The fallback key set `evicted,notices,peeked,total` spans 07-25 -> 09-03 --
     the entire corpus.  It marks a composition FALLBACK (a condition), not a
     vintage.

What does date a primer, exactly and per-file, is birth time: `statx.btime`,
exposed by coreutils as `stat -c %W`.  All 923 primers carry one.  mtime is the
(re-)fire; birth is the composition.  This works for every primer in the primary
store, including the 856 no longer present in the retry store -- where the
retry-store-mtime method used by the earlier finding cannot reach.

`for_plugin` is the one key that does bracket a file: present 07-31..08-31 and
never after.  Its presence bounds a file; its absence still dates nothing.

Usage:
    python3 tools/primer_birth_census.py [--primary DIR] [--retry DIR]
"""
from __future__ import annotations

import argparse
import collections
import datetime
import glob
import json
import os
import statistics
import subprocess

UTC = datetime.timezone.utc
PRIMARY = os.path.expanduser("~/.claude/hestia-mesh-primers")
RETRY = os.path.expanduser("~/.local/state/hestia-mesh/primers/claude-code")

# The key the wake banner reasons about, and the date it attributes to it.
PETITIONS_FOLD_LANDED = "2026-08-19"


def birth_and_mtime(paths: list[str]) -> dict[str, tuple[int, int]]:
    """Return {path: (birth_epoch, mtime_epoch)} via `stat -c '%W %Y %n'`.

    Python's os.stat() exposes no st_birthtime on Linux, so shell out once for
    the whole population rather than per file.  %W is 0 on filesystems that do
    not record a birth time; callers must treat 0 as "unknown", not as epoch.
    """
    out: dict[str, tuple[int, int]] = {}
    if not paths:
        return out
    for chunk in (paths[i:i + 500] for i in range(0, len(paths), 500)):
        res = subprocess.run(
            ["stat", "-c", "%W %Y %n", *chunk],
            capture_output=True, text=True, check=False,
        )
        for line in res.stdout.splitlines():
            b, m, p = line.split(None, 2)
            out[p] = (int(b), int(m))
    return out


def load_keys(path: str) -> tuple[set[str], list[dict]] | None:
    try:
        with open(path) as fh:
            d = json.load(fh)
    except Exception:
        return None
    if not isinstance(d, dict):
        return None
    return set(d.keys()), d.get("notices", []) or []


def day(epoch: int) -> str:
    return datetime.datetime.fromtimestamp(epoch, UTC).strftime("%Y-%m-%d")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--primary", default=PRIMARY)
    ap.add_argument("--retry", default=RETRY)
    args = ap.parse_args()

    paths = sorted(glob.glob(os.path.join(args.primary, "*.json")))
    times = birth_and_mtime(paths)
    no_birth = [p for p in paths if times.get(p, (0, 0))[0] == 0]

    rows = []
    for p in paths:
        got = load_keys(p)
        if got is None:
            continue
        birth, mtime = times.get(p, (0, 0))
        if birth == 0:
            continue  # unknown birth: cannot date, do not guess
        keys, notices = got
        rows.append((birth, mtime, p, keys, notices))

    print(f"primary store        : {len(paths)} files")
    print(f"  unreadable/no birth: {len(paths) - len(rows)}"
          f" (of which {len(no_birth)} lack a birth time)")

    # --- Claim 1: open_petitions absence dates nothing -----------------
    withp = [r for r in rows if "open_petitions" in r[3]]
    print(f"\n[1] `open_petitions` present in {len(withp)} of {len(rows)} primers")
    for birth, _, p, _, _ in withp:
        print(f"      {os.path.basename(p)} born {day(birth)}")
    after = [r for r in rows if day(r[0]) > PETITIONS_FOLD_LANDED
             and "open_petitions" not in r[3]]
    print(f"    primers born AFTER {PETITIONS_FOLD_LANDED} that still lack it: {len(after)}")
    print("    => absence does NOT imply the producer predates the fold."
          if after else "    => absence is consistent with the fold date.")

    # --- Claim 2: which key sets actually bracket a date ---------------
    byset: dict[str, list[int]] = collections.defaultdict(list)
    for birth, _, _, keys, _ in rows:
        byset[",".join(sorted(keys))].append(birth)
    print(f"\n[2] key set vs birth-date span ({len(byset)} distinct sets)")
    print(f"    {'KEY SET':<62}{'n':>5}  {'first':<11}{'last':<11}dates?")
    for ks, births in sorted(byset.items(), key=lambda kv: -len(kv[1])):
        lo, hi = day(min(births)), day(max(births))
        spans_all = lo <= "2026-07-26" and hi >= "2026-09-02"
        print(f"    {ks:<62}{len(births):>5}  {lo:<11}{hi:<11}"
              f"{'NO (spans corpus)' if spans_all else 'brackets'}")

    # --- Claim 3: birth vs mtime separates composition from re-fire ----
    refired = [r for r in rows if r[1] - r[0] >= 2]
    print(f"\n[3] re-fires (mtime - birth >= 2s): {len(refired)} of {len(rows)}"
          f" = {100 * len(refired) / len(rows):.1f}%")
    if refired:
        gaps = sorted(r[1] - r[0] for r in refired)
        print(f"    lag: median {statistics.median(gaps) / 86400:.1f} d,"
              f" max {max(gaps) / 86400:.1f} d")

    # --- The live backlog: what is still queued to re-fire -------------
    live = sorted(glob.glob(os.path.join(args.retry, "*.json")))
    if live:
        lt = birth_and_mtime(live)
        now = datetime.datetime.now(UTC).timestamp()
        ages, attempts = [], collections.Counter()
        notices_queued = 0
        for p in live:
            b, _ = lt.get(p, (0, 0))
            if b:
                ages.append((now - b) / 86400)
            try:
                with open(p + ".attempts") as fh:
                    attempts[int(fh.read().strip())] += 1
            except Exception:
                attempts[0] += 1
            got = load_keys(p)
            if got:
                notices_queued += len(got[1])
        print(f"\n[4] live retry queue : {len(live)} primers, {notices_queued} notices")
        if ages:
            print(f"    age since composition: median {statistics.median(ages):.1f} d,"
                  f" max {max(ages):.1f} d")
        print(f"    .attempts histogram  : {dict(sorted(attempts.items()))}")
    else:
        print(f"\n[4] live retry queue : none found at {args.retry}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
