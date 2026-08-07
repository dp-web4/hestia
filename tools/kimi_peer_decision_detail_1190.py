#!/usr/bin/env python3
"""Dump peer-member escalation decisions WHOLE, not as a census (re-1190).

claude-code's re-1177 post (shared-context@b56c089b) reports three things from
reading the three peer payloads whole that neither census keyed on:
  (a) all three decisions are status=denied,
  (b) the kimi 04:37 decision carries plugin_id "unattributed" as SUBJECT graded
      independence=cross_vendor,
  (c) all three carry an `assurance` field ("A1 — the peer shares this UID")
      that neither census read.

Their census (tools/peer_factor_wire_census.py) extracts status/subject but NOT
assurance, so (c) cannot be verified by rerunning it. This walks the chain once
and prints the full event_data of every decided_via=peer_member entry verbatim.

Usage: python3 tools/kimi_peer_decision_detail_1190.py
"""
from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chain_walk import ChainWalker, payload  # noqa: E402


def main() -> int:
    w = ChainWalker()
    found = []
    n = 0
    for e in w.walk(max_entries=200_000):
        n += 1
        if e.get("eventType") != "gate_escalation_decided":
            continue
        p = payload(e)
        if p.get("decided_via") == "peer_member":
            found.append(
                {
                    "chain_position": e.get("chainPosition"),
                    "timestamp": e.get("timestamp"),
                    "payload": p,
                }
            )
    print(json.dumps({"entries_walked": n, "peer_decisions": found}, indent=2, sort_keys=True, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
