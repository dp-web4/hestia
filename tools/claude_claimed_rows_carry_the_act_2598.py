#!/usr/bin/env python3
"""Every `gate_escalation_claimed` row in the chain window: does it name the act it spent?

WHY. PR #383 (merged 2026-08-12) makes the claimed row carry `attempted_act` and
`host_session_id`, EXPLICITLY null when unsent, so that "which act consumed this
approval" stops being adjacency reconstruction. It was verified merged-but-NOT-in-force
at chain @134972 (2026-08-13 18:44:45Z) — the daemon had not been restarted. This
instrument answers the deploy question by reading the rows themselves rather than any
process listing: a shape change is in force exactly when the rows carry the shape.

Reports, per claimed row: escalation id, tool_name, whether the two #383 keys are
PRESENT (with their values, including explicit null), and the decision->use latency the
row already carried pre-#383. Key-present and value-null are different rows to a census
and are printed differently here on purpose.

Mints nothing, claims nothing: one chain read, same as chain_walk.py.
"""
from __future__ import annotations

import sys

from chain_walk import ChainWalker, payload

CLAIMED = "gate_escalation_claimed"
NEW_KEYS = ("attempted_act", "host_session_id")


def main() -> int:
    walker = ChainWalker()
    rows = []
    for entry in walker.walk(max_entries=20000):
        # The type lives on the ENTRY as `eventType` (camelCase), not in the payload and
        # not as `event_type`. Reading the payload for it returns None for every row and
        # the census prints a clean, wrong zero — the same shape as every "none found"
        # that indicts the instrument rather than the population.
        if (entry.get("eventType") or "") != CLAIMED:
            continue
        rows.append((entry, payload(entry) or {}))

    print(f"claimed rows in window: {len(rows)}")
    if not rows:
        return 0

    present = {k: 0 for k in NEW_KEYS}
    nonnull = {k: 0 for k in NEW_KEYS}
    print()
    hdr = f"{'escalation':18} {'tool':10} {'s_dec->use':>10}  #383 keys"
    print(hdr)
    print("-" * len(hdr))
    for entry, p in rows[-40:]:
        esc = str(p.get("escalation_id") or p.get("id") or "?")[:16]
        tool = str(p.get("tool_name") or "-")[:10]
        lat = p.get("secs_from_decision_to_use")
        marks = []
        for k in NEW_KEYS:
            if k in p:
                present[k] += 1
                v = p[k]
                if v is None:
                    marks.append(f"{k}=<explicit null>")
                else:
                    nonnull[k] += 1
                    marks.append(f"{k}={str(v)[:60]!r}")
            else:
                marks.append(f"{k} ABSENT")
        print(f"{esc:18} {tool:10} {str(lat):>10}  " + "; ".join(marks))

    print()
    for k in NEW_KEYS:
        print(f"{k}: key present on {present[k]}/{len(rows)} rows, non-null on {nonnull[k]}")
    print()
    print(
        "in force  = key PRESENT (null or not) on rows written after the restart.\n"
        "not in force = key ABSENT: the daemon writing these rows predates the merge."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
