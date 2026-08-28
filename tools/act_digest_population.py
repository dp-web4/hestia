#!/usr/bin/env python3
"""#627, over the whole reachable population instead of one row at a time.

WHY THIS EXISTS. Issue #627 established that `act_digest` on a
`gate_escalation_opened` row is sha256 of the *rendered preview* rather than of
the refused act. Every confirmation on that thread — three seats, four
independent recomputations — verified ONE row (or one three-seat control of one
act). A single instance proves the mechanism exists. It does not say how much of
the corpus it covers, and it cannot distinguish "the hook's fallback fires on the
gate door" from "no caller has ever sent a distinct `act`". Those are different
defects with different remedies, and only a census tells them apart.

WHAT IT ANSWERS.

  1. Of every escalation on the chain that carries an `act_digest`, on how many
     does `sha256(stated_reason.strip())` reproduce it exactly?
  2. How many of those bound rows carry a reason that is TRUNCATED (ends U+2026)
     or REDACTED — i.e. the digest binds a string the act cannot be read out of?
  3. Is there any row where the digest binds `stated_detail` instead — i.e. has
     the uncapped field ever been used as the act?
  4. What is actually IN `stated_detail`, and how long does the wire let it be?

READING THE OUTPUT. `identity_holds == bound` means the daemon's `act` parameter
has never carried anything a `stated_reason` did not already carry, for any
caller, for the whole window. That is a stronger statement than "the gate hook
falls back", and it is the one that decides whether #627's remedy needs a hook
change, a door change, or both.

THE LEFT EDGE IS A HOP BUDGET, NOT A DATE. `--max` walks N hops back from the
tip at run time; the earliest timestamp reached DRIFTS as the chain grows, so the
window this prints today is not the window it prints tomorrow. The span is
printed for exactly that reason — quote it with any number taken from here.
Bound rows first appear 2026-08-25 (act binding, #539), so a window reaching
2026-08-06 covers the complete BOUND population even though it is far from
genesis; that is a property of the feature's age, not of the budget.

Read-only: one `hestia_query_history` walk, no gate call, no write.

    python3 tools/act_digest_population.py [--max 90000]
"""
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chain_walk import ChainWalker, payload  # noqa: E402

#: The literal every gate-auto-opened escalation carries as `stated_detail`,
#: hardcoded at the hook's claim call site. See #608 — recorded here because a
#: census that did not recognise it would report 667 distinct rationales.
DETAIL_CONSTANT = (
    "Auto-opened by the gate on a refused write; the member stated no rationale "
    "because it did not choose to escalate. Approving authorises this one write."
)


def collect(max_entries: int) -> list[dict]:
    w = ChainWalker()
    rows = []
    walked = 0
    for e in w.walk(max_entries=max_entries):
        walked += 1
        if e.get("eventType") != "gate_escalation_opened":
            continue
        p = payload(e)
        p["_ts"] = e.get("timestamp") or e.get("createdAt") or e.get("at")
        rows.append(p)
    print(f"walked {walked} entries -> {len(rows)} gate_escalation_opened rows")
    return rows


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=90000,
                    help="hop budget (NOT a date window — see module docstring)")
    a = ap.parse_args()

    rows = collect(a.max)
    if not rows:
        print("no escalation rows in this window")
        return 1
    ts = sorted(r["_ts"] for r in rows if r.get("_ts"))
    print(f"span reached: {ts[0][:19]} -> {ts[-1][:19]}  (left edge is the hop budget)")

    c: Counter = Counter()
    per_seat: dict = defaultdict(Counter)
    per_day: dict = defaultdict(Counter)
    detail_len: Counter = Counter()

    for r in rows:
        seat = r.get("plugin_id") or "?"
        day = (r.get("_ts") or "?")[:10]
        digest = r.get("act_digest")
        reason = r.get("stated_reason")
        detail = r.get("stated_detail")

        c["rows"] += 1
        per_day[day]["rows"] += 1
        per_seat[seat]["rows"] += 1

        truncated = bool(reason) and reason.rstrip().endswith("…")
        redacted = bool(reason) and "[REDACTED" in reason
        if truncated:
            c["reason_truncated"] += 1
            per_day[day]["trunc"] += 1
            per_seat[seat]["trunc"] += 1
        if redacted:
            c["reason_redacted"] += 1
            per_seat[seat]["redacted"] += 1

        if detail is None:
            c["detail_absent"] += 1
        else:
            detail_len[len(detail)] += 1
            c["detail_is_the_constant" if detail.strip() == DETAIL_CONSTANT
              else "detail_carries_something_else"] += 1

        if not digest:
            c["unbound"] += 1
            continue
        c["bound"] += 1
        per_day[day]["bound"] += 1
        per_seat[seat]["bound"] += 1
        if reason is not None and hashlib.sha256(reason.strip().encode()).hexdigest() == digest:
            c["identity_holds"] += 1
            per_seat[seat]["identity_holds"] += 1
            if truncated:
                c["bound_over_a_truncated_reason"] += 1
                per_seat[seat]["bound_trunc"] += 1
            if redacted:
                c["bound_over_a_redacted_reason"] += 1
        else:
            c["identity_FAILS"] += 1
            per_seat[seat]["identity_FAILS"] += 1
        if detail is not None and hashlib.sha256(detail.strip().encode()).hexdigest() == digest:
            c["digest_binds_stated_detail"] += 1

    print("\n== population ==")
    for k in sorted(c):
        print(f"  {c[k]:5d}  {k}")

    print("\n== per seat ==")
    for seat in sorted(per_seat):
        s = per_seat[seat]
        print(f"  {seat:14s} rows={s['rows']:4d} bound={s['bound']:4d} "
              f"identity_holds={s['identity_holds']:4d} identity_FAILS={s['identity_FAILS']:3d} "
              f"trunc={s['trunc']:4d} bound_trunc={s['bound_trunc']:3d} redacted={s['redacted']:3d}")

    print("\n== act binding by day (when did act_digest start existing?) ==")
    print("  day         rows  bound  trunc")
    for day in sorted(per_day):
        d = per_day[day]
        print(f"  {day}  {d['rows']:4d}  {d['bound']:5d}  {d['trunc']:5d}")

    print("\n== stated_detail on the wire ==")
    if detail_len:
        print(f"  present={sum(detail_len.values())} distinct_lengths={len(detail_len)} "
              f"min={min(detail_len)} max={max(detail_len)}")
        print(f"  histogram: {dict(detail_len.most_common(8))}")
        print(f"  (the field is NOT capped at the reason's 220/400 — {max(detail_len)} chars "
              f"observed on the wire)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
