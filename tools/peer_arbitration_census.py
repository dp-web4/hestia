#!/usr/bin/env python3
"""Who has ever RULED an escalation on this chain, when did they stop, and why not.

WHY THIS EXISTS. #264 measured "0 of 215 escalations ever ruled by an agent" over a
trailing 25,000-entry window on 2026-08-07 and concluded the driver was never built. A
walk of the COMPLETE chain on 2026-09-07 (238,542 hops, genesis 2026-05-16) found 23
peer rulings, the earliest two on 2026-07-31 — one week older than the issue, and just
outside its window. The capability had run for 24 days and then REGRESSED on
2026-08-24T02:40:01Z. A recent window manufactures false "nevers", and the cost here was
an open issue arguing to build a thing that already existed.

So this file is the standing instrument, not a one-off: run it before making any claim
about whether agents rule, and it will state its own horizon in the same breath as its
numbers.

WHAT IT REPORTS

  1. `decided_via` census over the whole chain: `operator_session` vs `peer_member`, and
     `decided_by` per seat, with each seat's first and last ruling.
  2. open -> decide LATENCY either side of the boundary. This exists because the obvious
     explanation — the operator got faster, so a peer on a ~2-minute wake cadence lost the
     race — is testable and FALSE: median 97 s before vs 105 s after, <=60 s 41% vs 37%.
     The window did not shrink. Re-run this before proposing that hypothesis again.
  3. Peer fire-log health per day: fires, and fires whose log carries no out-of-credits
     error. Credit exhaustion is real (both peers are dark as of 2026-09-05) but it is
     NOT the cause: codex fired credit-clean until 2026-09-04 and kimi until 2026-09-03,
     eleven days after the last peer ruling.

TWO PROXIES THAT LOOK CONVINCING AND ARE WRONG. Both were tried on 2026-09-07 and
withdrawn before publication; they are named here so the next reader does not spend the
same hour:

  * grepping a fire log for `hestia_gate_arbitrate_escalation` counts the seat READING
    gate source and tests (`core/src/gate_cli.rs`, `member_presence_census.rs`,
    `docs/PRD_GOVERNANCE.md`), not calling the tool. A tool named in a file being read is
    indistinguishable from a tool being called, by grep.
  * classifying a wake summary as "ruled" on the string `gate deny` matches the
    SELF-WITHDRAWAL verb (`hestia gate deny <id> --as <self>`), which is the opposite of a
    ruling.

WHAT IS STILL UNKNOWN. Four hypotheses are eliminated (credits, invitation text, the
race, peer absence) and the cause of the 2026-08-24 regression is not among them. Full
argument and data: #264.

Usage:
    python3 tools/peer_arbitration_census.py                # all three sections
    python3 tools/peer_arbitration_census.py --max 60000    # bounded walk, horizon stated
    python3 tools/peer_arbitration_census.py --boundary 2026-08-24T02:40:00+00:00
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import re
import statistics
import sys
import time
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chain_walk import ChainWalker, payload  # noqa: E402

# The last peer_member ruling on CBP's chain. Everything after it is operator-only.
DEFAULT_BOUNDARY = "2026-08-24T02:40:01+00:00"
OUT_OF_CREDITS = re.compile(r"out of credits", re.I)


def _ts(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def walk(max_entries: int) -> dict:
    """One pass, both questions. Two passes would double the daemon load for nothing."""
    w = ChainWalker()
    by_decider: Counter = Counter()
    by_via: Counter = Counter()
    newest: dict = {}
    oldest_seen: dict = {}
    opened: dict = {}
    decided: dict = {}
    n = 0
    horizon = None
    t0 = time.time()
    for e in w.walk(max_entries=max_entries):
        n += 1
        horizon = e.get("timestamp") or horizon
        et = e.get("eventType")
        if et == "gate_escalation_opened":
            p = payload(e)
            if p.get("escalation_id"):
                opened[p["escalation_id"]] = e.get("timestamp")
        elif et == "gate_escalation_decided":
            p = payload(e)
            who = p.get("decided_by") or p.get("decider") or "(none-recorded)"
            by_decider[who] += 1
            by_via[p.get("decided_via") or "(none)"] += 1
            ts = e.get("timestamp")
            newest.setdefault(who, ts)      # the walk runs newest -> oldest
            oldest_seen[who] = ts
            if p.get("escalation_id"):
                decided[p["escalation_id"]] = (ts, who)
    return {
        "walked": n, "horizon": horizon, "elapsed_s": round(time.time() - t0, 1),
        "by_decider": by_decider, "by_via": by_via,
        "newest": newest, "oldest": oldest_seen,
        "opened": opened, "decided": decided,
    }


def report_rulings(r: dict) -> None:
    total = sum(r["by_decider"].values())
    print(f"\n== 1. WHO RULED  ({total} decisions; {r['walked']} hops walked, "
          f"horizon {r['horizon']}, {r['elapsed_s']}s)")
    print("   decided_via:", dict(r["by_via"]))
    for who, cnt in r["by_decider"].most_common():
        print(f"   {who:14} {cnt:5d}   first {r['oldest'].get(who)}   last {r['newest'].get(who)}")
    if r["walked"] and not r["by_via"].get("peer_member"):
        print("   NOTE: zero peer rulings IN THIS WINDOW. That is not 'never' unless the")
        print("         walk reached genesis — check the horizon above before saying so.")


def report_latency(r: dict, boundary: str) -> None:
    b = _ts(boundary)
    before, after = [], []
    for eid, (dts, _who) in r["decided"].items():
        a, z = _ts(r["opened"].get(eid)), _ts(dts)
        if a is None or z is None:
            continue
        (before if a < b else after).append(z - a)
    print(f"\n== 2. OPEN -> DECIDE LATENCY  (boundary {boundary})")
    print(f"   {'group':22} {'n':>5} {'median':>8} {'p25':>7} {'p75':>7} "
          f"{'<=60s':>7} {'<=120s':>7} {'<=300s':>7}")
    for name, grp in (("before boundary", before), ("since boundary", after)):
        if not grp:
            print(f"   {name:22} {0:>5}")
            continue
        L = sorted(grp)
        n = len(L)

        def q(f, L=L, n=n):
            return L[min(n - 1, int(f * n))]

        def pct(t, L=L, n=n):
            return f"{100 * sum(1 for x in L if x <= t) / n:.0f}%"

        print(f"   {name:22} {n:>5} {statistics.median(L):>7.0f}s {q(.25):>6.0f}s "
              f"{q(.75):>6.0f}s {pct(60):>7} {pct(120):>7} {pct(300):>7}")
    print("   A peer wakes on the watcher's cadence. If these two rows match, the peers")
    print("   had the same window on both sides and 'they lost the race' is not the answer.")


def report_fire_health(logs_dir: Path) -> None:
    print(f"\n== 3. PEER FIRE HEALTH  ({logs_dir})")
    if not logs_dir.is_dir():
        print("   no mesh log directory on this box — section skipped")
        return
    for seat in ("codex", "kimi", "claude"):
        per_day: dict = defaultdict(lambda: [0, 0])
        for p in sorted(glob.glob(str(logs_dir / f"{seat}-*.log"))):
            day = os.path.basename(p).split("-")[1][:8]
            try:
                txt = Path(p).read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            per_day[day][0] += 1
            if not OUT_OF_CREDITS.search(txt):
                per_day[day][1] += 1
        if not per_day:
            continue
        days = sorted(per_day)
        clean_days = [d for d in days if per_day[d][1] > 0]
        fires = sum(v[0] for v in per_day.values())
        print(f"   {seat:7} {fires:5d} fires over {len(days)} days; "
              f"last day with a credit-clean fire: {clean_days[-1] if clean_days else 'NEVER'}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--max", type=int, default=400000,
                    help="max hops; the default walks to genesis on CBP (~238k, ~7 min)")
    ap.add_argument("--boundary", default=DEFAULT_BOUNDARY)
    ap.add_argument("--json", metavar="PATH", help="also dump the raw census")
    args = ap.parse_args()

    r = walk(args.max)
    report_rulings(r)
    report_latency(r, args.boundary)
    home = os.getenv("HOME")
    if home:
        report_fire_health(Path(home) / ".local" / "state" / "hestia-mesh" / "logs")
    if args.json:
        Path(args.json).write_text(json.dumps({
            "walked": r["walked"], "horizon": r["horizon"],
            "by_decider": dict(r["by_decider"]), "by_via": dict(r["by_via"]),
            "first_ruling": r["oldest"], "last_ruling": r["newest"],
        }, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
