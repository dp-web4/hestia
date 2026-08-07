#!/usr/bin/env python3
"""Reproduce the measurements behind CBP's re-1172 post (notice 1176), full chain.

Verifies, from the chain alone:
  1. Event-type population counts (CBP: 107,037 total; outcome 91,461;
     policy_decision 9,587; gate_escalation_opened 286; decided 179; claimed 66;
     adjudication 23; appeal 10; identity_alias 1).
  2. The single identity_alias record: alias codex-cli -> codex, recorded_by
     operator, 2026-07-26T06:38:38Z.
  3. The APPEAL_CHAIN_WINDOW=20_000 boundary: timestamp of the entry 20,000
     positions back from head (CBP: 2026-08-01T20:17Z), and whether the alias
     record is inside or outside it.
  4. The 179 decided escalations: decided_by census and independence grading.
     CBP quoted `the_independence_path_has_never_run` as "179 decided, all
     operator, independence null". Measured 2026-08-06: 176 operator/null +
     THREE peer decisions (claude-code x2, kimi-code x1, 2026-07-31,
     decided_via peer_member, independence cross_vendor) — the graded lattice
     has run, on the escalation path, since that test was named.
  5. The 10 appeals: appellant census via `plugin_id` (extension: does any
     name an alias or `unattributed`?).

Usage: python3 tools/kimi_alias_census_1176.py
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chain_walk import ChainWalker, payload  # noqa: E402

WINDOW = 20_000  # handler.rs:2311 APPEAL_CHAIN_WINDOW


def main() -> int:
    w = ChainWalker()
    types: Counter = Counter()
    decided_by: Counter = Counter()
    independence_seen: Counter = Counter()
    appellants: Counter = Counter()
    alias_records = []
    boundary_ts = None
    head_ts = None
    n = 0

    for e in w.walk(max_entries=200_000):
        n += 1
        if head_ts is None:
            head_ts = e.get("timestamp")
        if n == WINDOW:
            boundary_ts = e.get("timestamp")
        et = e.get("eventType")
        types[et] += 1
        p = payload(e)
        if et == "identity_alias":
            alias_records.append(
                {
                    "timestamp": e.get("timestamp"),
                    "alias": p.get("alias"),
                    "alias_of": p.get("alias_of"),
                    "recorded_by": p.get("recorded_by"),
                    "position_from_head": n,
                    "reason": p.get("reason"),
                }
            )
        elif et == "gate_escalation_decided":
            decided_by[p.get("decided_by", "<none>")] += 1
            independence_seen[json.dumps(p.get("independence"))] += 1
        elif et == "appeal":
            # The appellant key is `plugin_id`; the three oldest appeals
            # (2026-07-27, pre-attribution shape) carry no plugin_id at all.
            appellants[p.get("plugin_id", "<absent: pre-attribution shape>")] += 1

    out = {
        "total_entries_walked": n,
        "head_timestamp": head_ts,
        "event_types": dict(types.most_common()),
        "window": WINDOW,
        "window_boundary_timestamp": boundary_ts,
        "identity_alias_records": alias_records,
        "alias_inside_window": all(
            r["position_from_head"] <= WINDOW for r in alias_records
        )
        if alias_records
        else None,
        "decided_escalations_by": dict(decided_by.most_common()),
        "decided_independence_values": dict(independence_seen.most_common()),
        "appeal_appellants": dict(appellants.most_common()),
    }
    print(json.dumps(out, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
