#!/usr/bin/env python3
"""Which chain rows name the session of the party they are ABOUT? (2026-09-18)

WHY. `handler::disposition_obligation` derives the recipient of every return edge
(disposition notice) from ONE chain row: the terminal ruling. It addresses the
SUBJECT of that row. So whether a ruling can be delivered to the session that
asked — rather than to a seat NAME several concurrent sessions share — is a
property of which identity fields the ruling row happens to carry.

This walks the chain and answers that per event type, so the claim
"provenance is written where it was proven, never where it will be read" is a
table and not an impression. Findings:
`findings/every-ruling-names-the-actor-never-the-subject-2026-09-18.md`.

Usage:
    python3 tools/session_provenance_census.py [--max 12000]

Reads only. Bulk act rows (`outcome`, `policy_decision`, `agent_inventory`,
`gate_self_*`, `egress_forwarded`, `member_notice`) are excluded by default:
they are per-act records whose actor IS their subject, which is the case that
was never in question.
"""
from __future__ import annotations

import argparse
import os
import sys
from collections import Counter, defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chain_walk import ChainWalker, payload  # noqa: E402

# Every spelling of "a party" this chain uses, session keys first. Listed
# explicitly rather than discovered, so a NEW spelling shows up as a gap in the
# `other identity` column instead of being silently counted as coverage.
SESSION_KEYS = ("host_session_id", "session_id", "adjudicator_session")
NAME_KEYS = (
    "plugin_id", "subject_plugin_id", "corroborated_by", "decided_by",
    "granted_by", "attested_by", "requested_by", "adjudicator", "routed_to",
)
BULK = {
    "outcome", "policy_decision", "agent_inventory", "gate_self_read",
    "gate_self_access", "egress_forwarded", "member_notice",
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=12000)
    ap.add_argument("--include-bulk", action="store_true")
    args = ap.parse_args()

    walker = ChainWalker()
    totals: Counter[str] = Counter()
    have: dict[str, Counter[str]] = defaultdict(Counter)
    keys_seen: dict[str, set[str]] = defaultdict(set)
    first = last = None
    walked = 0

    for entry in walker.walk(max_entries=args.max):
        walked += 1
        ts = entry.get("timestamp")
        if last is None:
            last = ts
        first = ts
        etype = entry.get("eventType") or "?"
        if etype in BULK and not args.include_bulk:
            continue
        body = payload(entry)
        totals[etype] += 1
        keys_seen[etype] |= set(body)
        for key in SESSION_KEYS + NAME_KEYS:
            if body.get(key) not in (None, ""):
                have[etype][key] += 1

    print(f"walked {walked} entries, {first} -> {last}")
    print(f"{'event type':34} {'N':>5} " + " ".join(f"{k:>18}" for k in SESSION_KEYS) + "   names present")
    for etype, n in totals.most_common():
        cells = " ".join(f"{have[etype][k]:>18}" for k in SESSION_KEYS)
        names = ",".join(k for k in NAME_KEYS if have[etype][k])
        print(f"{etype:34} {n:>5} {cells}   {names}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
