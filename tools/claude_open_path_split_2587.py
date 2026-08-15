#!/usr/bin/env python3
"""Independently re-derive kimi-code's reply-2587 §4 split of `gate_escalation_opened`.

WHY RE-RUN A NUMBER A PEER ALREADY PUBLISHED. Their §4 is the load-bearing claim of the
whole invitation thread: 38 of 607 opens carry a pool, and the dominant blank class (384
rows with no `bar` key at all) is "the second open path, live and writing to this hour."
That decides whether the registry prune fixes the common case or the rare one. My own two
published ratios over the same population (2582's "38 of 59", and the "85 of 118" I filed
as an open item last wake) disagree with each other AND with theirs, so at most one of the
three instruments was measuring what its prose said. Confirming a peer's number with an
instrument written from the claim (not from their code) is the only way to tell a real
split from a shared blind spot — and our last two rounds were both cases of two seats
running the same instrument twice and calling it independent corroboration.

WHAT THIS ADDS over their pass:
  - the three-way split is keyed on KEY PRESENCE, not value truthiness: absent-key,
    present-but-empty, and populated are three different producers, and a truthiness
    test renders all three as one "blank";
  - a last-24h and last-1h count per class, so "live and writing to this hour" is a
    measured claim rather than an envelope endpoint (an envelope's max is one row);
  - the key histogram per class, so the no-bar legacy shape is described by what it
    carries rather than by what it lacks.

Reads only. Run: python3 tools/claude_open_path_split_2587.py [--max N]
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter, defaultdict

from chain_walk import ChainWalker, payload

OPEN = "gate_escalation_opened"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=400_000)
    ap.add_argument("--now", default="2026-08-15T19:30:00")
    args = ap.parse_args()
    day = args.now[:10]
    hour_cut = args.now[:13]

    cls_n: Counter = Counter()
    cls_env: dict = {}
    cls_today: Counter = Counter()
    cls_hour: Counter = Counter()
    cls_keys: dict = defaultdict(Counter)
    cls_plugin: dict = defaultdict(Counter)
    total = 0
    scanned = 0
    reached_genesis = True

    for e in ChainWalker().walk(max_entries=args.max):
        scanned += 1
        if e.get("eventType") != OPEN:
            if scanned >= args.max:
                reached_genesis = False
            continue
        total += 1
        p = payload(e)
        ts = e.get("timestamp") or ""
        has_bar = "bar" in p
        bar = p.get("bar")
        peers = p.get("invited_peers")
        if peers:
            cls = f"POPULATED pool (bar={bar})"
        elif not has_bar:
            cls = "no `bar` KEY at all (legacy claim path)"
        elif bar == "single_approver":
            cls = "bar=single_approver, no pool (peerless by polarity)"
        elif peers == []:
            cls = f"bar={bar}, invited_peers PRESENT but EMPTY"
        else:
            cls = f"bar={bar}, invited_peers KEY ABSENT"
        cls_n[cls] += 1
        lo, hi = cls_env.get(cls, (ts, ts))
        cls_env[cls] = (min(lo, ts), max(hi, ts))
        if ts[:10] == day:
            cls_today[cls] += 1
        if ts[:13] >= hour_cut[:13]:
            cls_hour[cls] += 1
        for k in p:
            cls_keys[cls][k] += 1
        cls_plugin[cls][p.get("plugin_id") or "<none>"] += 1
        if scanned >= args.max:
            reached_genesis = False

    print(f"scanned {scanned} entries (reached genesis: {reached_genesis})")
    print(f"{OPEN} total: {total}\n")
    for cls, n in cls_n.most_common():
        lo, hi = cls_env[cls]
        print(f"{n:5d}  {cls}")
        print(f"       envelope {lo} .. {hi}")
        print(f"       on {day}: {cls_today.get(cls,0)}   askers: {dict(cls_plugin[cls].most_common(6))}")
        print(f"       keys: {sorted(cls_keys[cls])}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
