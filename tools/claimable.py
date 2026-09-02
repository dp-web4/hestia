#!/usr/bin/env python3
"""Is this escalation's approval actually spendable? One reader, so nobody hand-rolls a sixth.

WHY THIS EXISTS. Twice now two members have spent a full mesh exchange arguing the
disposition of escalations neither had correctly evaluated. The first time it was the BAR
(five rows read as awaiting a sovereign act; all five were single_approver). The second
time, 2026-08-08, it was the CLOCK: three permits discussed across four notices as
"standing, and we are declining to spend them" had been unspendable since ~7 minutes
after they were granted. Every field a caller naturally reaches for says otherwise.

THE TRAP, precisely. `hestia_gate_escalation_poll` answers with `status`,
`permits_write` and `secs_remaining`. None of the three is claimability:

  * `permits_write` (handler.rs:11441) is `status.permits_write() && bar_met()` — TWO of
    `is_claimable`'s FOUR conjuncts (gate_escalation.rs:377). It drops
    `consumed_at.is_none()` and `now < decided_horizon()` — exactly the two that change
    AFTER the decision, i.e. the whole period during which anyone would think to ask.
  * `secs_remaining` is `expires_at - now`, and `expires_at` is OPEN-anchored
    (`opened_at + ttl_secs`, default 3600). The claim horizon has been GRANT-anchored
    since e5c0ff1 (2026-08-06): `decided_horizon = min(decided_at + 600, expires_at + 600)`.
    For a promptly-decided escalation those differ by nearly the whole TTL.
  * `status` never demotes an Approved row, so the misreport is permanent, not stale.

Measured live 2026-08-08T03:44:45Z on three real rows granted at 03:11:4x. Truth: dead
for ~24 minutes. Poll: all three `approved / permits_write: true / secs_remaining ~1500`,
i.e. it reported ~25 minutes REMAINING on permits that had ~25 minutes DEAD. The sign of
the error is the dangerous one — it invites a spend, it does not block one.

NOTE THE DIRECTION, because it is the reason this file exists rather than a footnote:
e5c0ff1 was a CORRECTNESS fix. It tightened the real window from ~4200s to 600s and did
not touch the convenience fields beside it. So the honest window shrank while the field
reporting it did not move: measured on these three rows, poll's countdown outruns the
real horizon by 3450 / 3474 / 3493 s — an over-report that GREW, from ~600s to ~58min,
as a result of the repair. A fix in one place widened the lie in the next place over.

Both prior recipes are superseded. "`decided_at + 4200 < now` proves past-horizon" is
still SOUND (one-sided) but ~7x too loose post-e5c0ff1; "`expires_at` confirms the
window" is simply the wrong clock.

Usage:
    python3 claimable.py 5b4f8f490e81b6d4 [more ids...]
    python3 claimable.py --all          # every decided escalation still in the chain window

Exit status is 0 always; read the VERDICT column. This tool mints nothing, claims
nothing, and makes no MCP call other than the chain read chain_walk.py already performs.
"""
from __future__ import annotations

import argparse
import calendar
import sys
import time
from typing import Any, Dict, Optional

from chain_walk import ChainWalker, payload

# Both from gate_escalation.rs. Kept here as named constants so a drift shows up as a
# diff on this line rather than as a wrong verdict — and re-read the source before
# trusting them, because that is the failure this whole file documents.
APPROVAL_CLAIM_WINDOW_SECS = 600
DEFAULT_TTL_SECS = 3600


def _epoch(ts: str) -> Optional[int]:
    """Chain timestamps are RFC3339 with nanos and an explicit +00:00 offset.

    `timegm`, never `mktime`: mktime reads the struct as LOCAL and applies DST, which on
    this box put every horizon out by exactly one hour — a plausible, well-formed, wrong
    answer, which is the same failure mode as every trap chain_walk.py documents.
    """
    if not ts:
        return None
    try:
        return calendar.timegm(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S"))
    except ValueError:
        return None


def collect(ids: Optional[set], max_entries: int = 20000) -> Dict[str, Dict[str, Any]]:
    """Fold every escalation event in the window into one record per id.

    Deliberately reads the CHAIN and not the poll tool: the poll tool is the thing under
    suspicion. `opened`/`decided`/`claimed` are three separate events and the claimed one
    is the only witness to `consumed_at` — a reader that skips it cannot see conjunct 3.
    """
    rows: Dict[str, Dict[str, Any]] = {}
    walker = ChainWalker()
    for entry in walker.walk(max_entries=max_entries):
        etype = entry.get("eventType") or ""
        if not etype.startswith("gate_escalation_"):
            continue
        data = payload(entry)
        eid = str(data.get("escalation_id") or "")
        if not eid or (ids is not None and eid[:8] not in ids and eid not in ids):
            continue
        row = rows.setdefault(eid, {"id": eid})
        fold_event(row, etype, data, _epoch(entry.get("timestamp") or ""))
    return rows


def fold_event(row: Dict[str, Any], etype: str, data: Dict[str, Any], at: Optional[int]) -> None:
    """Fold ONE chain event into its escalation's row. Factored out so the fold is testable
    without a daemon.

    `_withdrawn` and `_expired` are terminal too. Until 2026-09-02 only `_decided` set
    `status`, so a self-withdrawn row (534ea5a4bff742aa, chain event
    `gate_escalation_withdrawn`, `decided_via: self_withdrawn`) read here as
    `status=undecided` — the right verdict (NO) for the wrong reason, and a wrong reason
    that invites a reader to think the petition still awaits a ruling. A withdrawn petition
    also REVIVES on daemon restart (#710), so "undecided" and "withdrawn" are not
    interchangeable to anyone deciding whether to re-issue.
    """
    if etype.endswith("_opened"):
        row["opened_at"] = at
        row["expires_at"] = data.get("expires_at")
        row["ttl_secs"] = data.get("ttl_secs")
        row["bar"] = data.get("bar")
        row["marker"] = data.get("marker")
        row["plugin_id"] = data.get("plugin_id")
    elif etype.endswith("_decided"):
        row["decided_at"] = at
        row["status"] = data.get("status") or data.get("decision")
        row["bar_met"] = data.get("bar_met")
    elif etype.endswith("_withdrawn"):
        row["decided_at"] = at
        row["status"] = "withdrawn"
        row["bar_met"] = data.get("bar_met")
        row["decided_via"] = data.get("decided_via")
    elif etype.endswith("_expired"):
        row["status"] = "expired"
    elif etype.endswith("_claimed"):
        row["consumed_at"] = at


def horizon(row: Dict[str, Any]) -> Optional[int]:
    """`decided_horizon()` — BOTH ceilings, min of the two. Grant anchor usually binds.

    There is NO fallback to `opened_at`. An undecided row has no grant, so it has no
    grant anchor; substituting the open time manufactures a horizon for a permit that was
    never issued, and the caller reads the leftover seconds as permission. That fallback
    was here until 2026-08-15 and it made `verdict()` answer YES on 81 of 82 never-decided
    rows during their first `APPROVAL_CLAIM_WINDOW_SECS` — i.e. exactly the window in
    which anyone asks, because you ask right after you are refused.
    """
    decided = row.get("decided_at")
    expires = row.get("expires_at")
    if decided is None:
        return None
    after_grant = decided + APPROVAL_CLAIM_WINDOW_SECS
    if expires is None:
        return after_grant
    return min(after_grant, expires + APPROVAL_CLAIM_WINDOW_SECS)


def verdict(row: Dict[str, Any], now: int) -> str:
    """All four conjuncts of `is_claimable`, and NAME the one that fails.

    Reporting which conjunct killed it is the point: "not claimable" sent two members
    looking at the TTL when the grant anchor was what had bitten.
    """
    if row.get("consumed_at"):
        return "NO — already consumed"
    status = (row.get("status") or "").lower()
    # Affirmative, not "not-disqualifying". `if status and status != "approved"` skipped
    # itself on the empty string an UNDECIDED row carries, and `bar_met is False` skipped
    # itself on that row's None — two sentinel-shaped guards in series, both stepped over
    # by the same absence, so a never-decided escalation reached the clock check and
    # reported YES. Approval must be present to pass, never merely un-contradicted.
    if status != "approved":
        return f"NO — status={status or 'undecided'}"
    if row.get("bar_met") is False:
        return "NO — bar not met (peer conjunct)"
    h = horizon(row)
    if h is None:
        return "UNKNOWN — approved with no decided_at (malformed row)"
    if now >= h:
        return f"NO — past horizon by {now - h}s"
    return f"YES — {h - now}s left"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("ids", nargs="*", help="escalation ids (full or 8-char prefix)")
    ap.add_argument("--all", action="store_true", help="every escalation in the window")
    ap.add_argument("--max", type=int, default=20000)
    args = ap.parse_args()

    if not args.ids and not args.all:
        ap.error("give at least one id, or --all")

    wanted = None if args.all else {i[:8] for i in args.ids}
    rows = collect(wanted, max_entries=args.max)
    if not rows:
        print("no matching escalation events in the window", file=sys.stderr)
        return 0

    now = int(time.time())
    print(f"{'id':18} {'bar':21} {'verdict'}")
    for eid, row in sorted(rows.items(), key=lambda kv: kv[1].get("decided_at") or 0):
        print(f"{eid:18} {str(row.get('bar')):21} {verdict(row, now)}")
        h = horizon(row)
        if h is not None:
            expires = row.get("expires_at")
            slack = (expires + APPROVAL_CLAIM_WINDOW_SECS - h) if expires else 0
            # The gap between what `secs_remaining` shows and the truth. This is the
            # number the poll tool over-reports by, per row.
            print(f"{'':18} horizon anchored at grant; poll over-reports by ~{slack}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
