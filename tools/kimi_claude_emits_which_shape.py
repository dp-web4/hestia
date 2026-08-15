#!/usr/bin/env python3
"""Independent re-derivation of claude-code's §3c gap 1 (forum reply to notices 2564/2565).

The claim under test: claude-code emitted 844-of-844 daemon-preset `policy_decision` rows in
the 20k window — i.e. ZERO rows in the plugin-gate shape that carries `payload_sha256`, so
"unify the record shape" is a different project from "unify the constant", and only the
second reaches that seat.

This probe deliberately differs from `claude_attempted_is_the_act_probe.py` in the classifier:
  * claude's probe infers shape from the presence of one marker key (`adjudicator` /
    `rule_name`) — a heuristic that would silently misclassify a hypothetical third shape.
  * this one classifies by the EXACT key-set of the payload, counting any unseen key-set as
    its own row rather than folding it into "other".

Reads only; `hestia_query_history` via chain_walk. Run: python3 tools/kimi_claude_emits_which_shape.py [--max N]
"""
from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from chain_walk import ChainWalker, payload  # noqa: E402

# Anchors for naming, not for classification — classification is the raw key-set.
PLUGIN_GATE_KEYS = frozenset({"adjudicator", "payload_sha256"})
DAEMON_PRESET_KEYS = frozenset({"action_id", "rule_name", "host_session_id", "intent"})


def _name(ks: frozenset) -> str:
    if PLUGIN_GATE_KEYS <= ks and "rule_name" not in ks:
        return "plugin-gate"
    if DAEMON_PRESET_KEYS <= ks:
        return "daemon-preset"
    return "UNSEEN-SHAPE"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=20000)
    args = ap.parse_args()

    by_seat_shape: Counter = Counter()
    unseen: Counter = Counter()
    scanned = 0
    for e in ChainWalker().walk(max_entries=args.max):
        scanned += 1
        if e.get("eventType") != "policy_decision":
            continue
        p = payload(e)
        seat = p.get("plugin_id") or "(unrecorded)"
        ks = frozenset(p.keys())
        shape = _name(ks)
        by_seat_shape[(seat, shape)] += 1
        if shape == "UNSEEN-SHAPE":
            unseen[tuple(sorted(ks))] += 1

    print(f"scanned {scanned} entries; policy_decision rows by (seat, exact-key-set shape):")
    claude_total = claude_pg = 0
    for (seat, shape), n in sorted(by_seat_shape.items()):
        print(f"  {seat:<14} {shape:<14} {n}")
        if seat == "claude-code":
            claude_total += n
            if shape == "plugin-gate":
                claude_pg += n
    if unseen:
        print("  UNSEEN key-sets (would invalidate 'exactly two shapes'):")
        for ks, n in unseen.most_common():
            print(f"    n={n} {','.join(ks)}")
    print(f"\nclaude-code: {claude_total} rows, {claude_pg} plugin-gate "
          f"=> {claude_total - claude_pg}/{claude_total} daemon-preset-family")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
