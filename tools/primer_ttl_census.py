#!/usr/bin/env python3
"""Which retained primers can no fire ever discharge? — the fold-free half of the guard.

`retry_stale_primers` re-fires a retained primer until a predicate says its debt is
settled. Two of the three predicates proposed for that job need the `unanswered` fold,
and on the seats that matter the fold does not fit in one argv string (#881/#819/#858),
so they abstain and everything fires. This census answers the part that needs NO fold
and NO RPC: a notice older than the daemon's inbox TTL has been DELETED from
`member_notices`, so a response bound to it is witnessed `binding_verified: false` and
nothing the woken member does discharges anything. Measured both directions on CBP:

    notice 7590, 3d old, present in `i_owe`    -> ack -> binding_verified: TRUE
    notice 5400, 8.4d old, absent from `i_owe` -> ack -> binding_verified: FALSE

A primer whose EVERY notice is past the TTL is therefore unrecoverable, not merely
unmeasurable — and the attempt budget, which exists for transient delivery failures,
cannot make it measurable again. Report the count and the wakes still budgeted to it.

Usage:  primer_ttl_census.py [--state DIR] [--ttl SECS] [--json] [seat ...]
Default state dir: HESTIA_MESH_STATE, else ~/.local/state/hestia-mesh
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import pathlib
import sys

INBOX_TTL_SECS = 604800  # core/src/storage/inbox.rs — 7d
STALE_MAX_ATTEMPTS = 3   # plugins/member-mesh/hestia-watch-member.sh


def queued_ages(primer: pathlib.Path, now: datetime.datetime) -> list[float] | None:
    """Ages in seconds of every notice in the primer, or None if unreadable/empty.

    Unreadable is NOT "no notices": the caller must not read a parse failure as an
    empty list, which would retire a work list on the strength of a broken file.
    """
    try:
        notices = json.loads(primer.read_text()).get("notices") or []
    except Exception:
        return None
    if not notices:
        return None
    ages = []
    for n in notices:
        try:
            q = datetime.datetime.fromisoformat(
                str(n.get("queued_at", "")).replace("Z", "+00:00"))
        except ValueError:
            return None
        ages.append((now - q).total_seconds())
    return ages


def attempts(primer: pathlib.Path) -> int:
    try:
        v = int(pathlib.Path(str(primer) + ".attempts").read_text().strip())
    except Exception:
        return 0
    return v if v >= 0 else 0


def census(seat_dir: pathlib.Path, ttl: int, now: datetime.datetime) -> dict:
    rows = []
    for p in sorted(seat_dir.glob("notice-*.json")):
        ages = queued_ages(p, now)
        att = attempts(p)
        rows.append({
            "primer": p.name,
            "notices": 0 if ages is None else len(ages),
            "attempts": att,
            "budget": max(0, STALE_MAX_ATTEMPTS - att),
            # `ages` is non-empty whenever it is not None, but an empty list must
            # still report None rather than raise: this row feeds a report, and a
            # crash here would take the whole seat census with it.
            "max_age_days": round(max(ages) / 86400, 2) if ages else None,
            # unreadable -> not expired: abstain, never retire on a broken read
            "all_past_ttl": bool(ages) and all(a > ttl for a in ages),
        })
    exp = [r for r in rows if r["all_past_ttl"]]
    return {
        "seat": seat_dir.name,
        "live_primers": len(rows),
        "unreadable": sum(1 for r in rows if r["notices"] == 0),
        "all_past_ttl": len(exp),
        "fire_budget_wakes": sum(r["budget"] for r in rows),
        "futile_budget_wakes": sum(r["budget"] for r in exp),
        "rows": rows,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("seats", nargs="*")
    ap.add_argument("--state", default=os.getenv(
        "HESTIA_MESH_STATE", os.path.expanduser("~/.local/state/hestia-mesh")))
    ap.add_argument("--ttl", type=int, default=INBOX_TTL_SECS)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--verbose", action="store_true")
    a = ap.parse_args()

    root = pathlib.Path(a.state) / "primers"
    if not root.is_dir():
        print(f"no primer store at {root}", file=sys.stderr)
        return 2
    seats = a.seats or sorted(d.name for d in root.iterdir() if d.is_dir())
    now = datetime.datetime.now(datetime.timezone.utc)
    out = [census(root / s, a.ttl, now) for s in seats]

    if a.json:
        print(json.dumps(out if a.verbose else
                         [{k: v for k, v in c.items() if k != "rows"} for c in out],
                         indent=2))
        return 0
    print(f"{'seat':<14}{'live':>6}{'past TTL':>10}{'budget':>8}{'futile':>8}")
    for c in out:
        print(f"{c['seat']:<14}{c['live_primers']:>6}{c['all_past_ttl']:>10}"
              f"{c['fire_budget_wakes']:>8}{c['futile_budget_wakes']:>8}")
    tot_b = sum(c["fire_budget_wakes"] for c in out)
    tot_f = sum(c["futile_budget_wakes"] for c in out)
    print(f"{'TOTAL':<14}{sum(c['live_primers'] for c in out):>6}"
          f"{sum(c['all_past_ttl'] for c in out):>10}{tot_b:>8}{tot_f:>8}")
    if tot_b:
        print(f"\n{tot_f} of {tot_b} budgeted agent fires ({100*tot_f/tot_b:.1f}%) are on "
              f"work lists no fire can discharge.")
    if a.verbose:
        for c in out:
            print(f"\n== {c['seat']}")
            for r in c["rows"]:
                print(f"  {r['primer']:<24} n={r['notices']:<3} att={r['attempts']} "
                      f"age={r['max_age_days']}d past_ttl={r['all_past_ttl']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
