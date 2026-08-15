#!/usr/bin/env python3
"""Do the per-seat deny FALLBACK logs hold denies the chain never got?

Found while answering notice 2595: `~/.hestia/telemetry/gate-denies-<seat>.jsonl` holds
433 codex + 249 kimi-code records over 2026-08-13..15. That file is written by
`hestia_gate_mechanism._append_deny_fallback`, which runs ONLY in the `except` branch of
`witness_decision_unified` — i.e. only when the daemon witness call raised. Every row
carries `witness_delivery_failed`.

Two things need measuring before that means anything:

  1. ARE THEY REALLY OFF-CHAIN? A record can be in the fallback and on the chain if some
     other path (the daemon's own action gate, handler.rs:1349) witnessed the same act.
     So: for each fallback row, look for a `policy_decision` chain row from the same
     plugin within +/-`--tol` seconds carrying the same tool_name. Absence at that grain
     is evidence of a hole; presence is evidence of double-recording, and either is worth
     knowing. Reported as a rate, with the matched/unmatched split, never as a headline.

  2. WHICH ONES MATTER? Half these rows are `verdict_available: false` — the gate could
     not REACH a verdict (daemon down), which is infra, not conduct, and is excluded from
     temperament by design. The other half carry a real verdict (gate.self_access,
     egress.secret, ...). Only the second class is a missing DECISION; the first is a
     missing OUTAGE MARKER. Counting them together would inflate the finding, so they are
     split here and the split is the deliverable.

Both seats' logs are readable from this seat because HESTIA_HOME is shared; my own seat
has NO such file, which is itself the datum that my denies take the daemon-gate path.

Reads only. Run: python3 tools/claude_fallback_vs_chain_2588.py [--tol 90] [--max N]
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path

from chain_walk import ChainWalker, payload

LOGDIR = Path.home() / ".hestia" / "telemetry"


def parse_ts(s: str) -> float | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tol", type=float, default=90.0)
    ap.add_argument("--max", type=int, default=40_000)
    args = ap.parse_args()

    fb: list[dict] = []
    for path in sorted(LOGDIR.glob("gate-denies-*.jsonl")):
        for ln in path.open():
            try:
                r = json.loads(ln)
            except Exception:
                continue
            t = parse_ts(r.get("ts", ""))
            if t is None:
                continue
            fb.append({"plugin": r.get("plugin_id"), "t": t, "tool": r.get("tool_name") or "",
                       "decision": r.get("decision"), "va": bool(r.get("verdict_available")),
                       "rule": (r.get("rule") or "")[:40], "digest": bool(r.get("core_digest"))})
    if not fb:
        print("no fallback rows")
        return 0
    lo = min(r["t"] for r in fb)
    print(f"fallback rows: {len(fb)}  window {datetime.fromtimestamp(lo, timezone.utc).isoformat()} ..")

    # Chain side: policy_decision rows per plugin, only back to the fallback window start.
    chain: dict[str, list[tuple[float, str]]] = defaultdict(list)
    scanned = 0
    oldest = None
    for e in ChainWalker().walk(max_entries=args.max):
        scanned += 1
        ts = parse_ts(e.get("timestamp") or "")
        oldest = ts if ts else oldest
        # BOTH sinks, not just policy_decision: 45 codex fallback rows carry
        # decision="gate_self_access", and the daemon records that class under its OWN
        # eventType. Matching only policy_decision would score every one of them
        # OFF-CHAIN by construction — the instrument would manufacture the hole it is
        # testing for. (gate_self_read excluded: reads are not the deny population.)
        if e.get("eventType") in ("policy_decision", "gate_self_access") and ts:
            p = payload(e)
            chain[p.get("plugin_id") or "?"].append((ts, p.get("tool_name") or ""))
        if ts and ts < lo - args.tol:
            break
    covered = oldest is not None and oldest <= lo
    print(f"scanned {scanned} chain entries; window fully covered: {covered}")
    print(f"chain policy_decision in window: { {k: len(v) for k, v in chain.items()} }\n")

    res: Counter = Counter()
    unmatched_rules: Counter = Counter()
    for r in fb:
        cands = chain.get(r["plugin"], [])
        hit = any(abs(t - r["t"]) <= args.tol and tool == r["tool"] for t, tool in cands)
        key = (r["plugin"], "verdict" if r["va"] else "no-verdict", "ON-CHAIN" if hit else "OFF-CHAIN")
        res[key] += 1
        if not hit and r["va"]:
            unmatched_rules[(r["plugin"], r["rule"])] += 1

    print(f"== fallback rows vs chain, +/-{args.tol}s and same tool_name ==")
    for k, n in sorted(res.items()):
        print(f"  {k[0]:12s} {k[1]:10s} {k[2]:9s} {n:5d}")
    print("\n== verdict-bearing rows with NO chain match, by rule ==")
    for (plug, rule), n in unmatched_rules.most_common(12):
        print(f"  {plug:12s} {n:5d}  {rule}")
    print(f"\n  digest-bearing fallback rows: {sum(1 for r in fb if r['digest'])} of {len(fb)}"
          "   (the chain carries `core_digest` 0 times, all seats, all time)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
