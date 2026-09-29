#!/usr/bin/env python3
"""Per-member acceptance metric for the outcome witness: warned acts closed by a same-id outcome.

WHY (findings/per-harness-witness-drift-2026-09-28.md, recommendation 3). A `gate:warn` act
EXECUTES, so under #977 the witness must close it with an outcome under the SAME action_id — the
join that makes a decision and what ran one record. Measured 2026-09-28 over the window since
#977 (2026-09-07): claude-code 1985/1986, kimi-code 0/37, codex 0/1. Every inventory report read
all three as witnessed. A harness is not "witnessed" until this rate says so.

Source: the daemon's plaintext reputation sink (`~/.hestia/reputation-deltas.jsonl`). The chain
itself is SQLCipher and its MCP read is capped at 500 rows, so it cannot reach this history.
`allow` decisions emit no delta, so warns are the observable sample; a member with few warns has
a wide interval — `--min-warns` keeps a thin sample from reading as a verdict either way.

Members are keyed by subject LCT (the sink carries nothing else). Name them with
`--label LCT=name`; nothing here hardcodes a fleet.

    python3 tools/witness_closure_census.py --since 2026-09-07
    python3 tools/witness_closure_census.py --since 2026-09-28T20:00 --min-rate 0.95 --min-warns 5 \\
        --label lct:web4:member:8cd1…=kimi-code
Exit: 0, or 1 when --min-rate is given and a member with at least --min-warns warns is below it.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict

DEFAULT_SINK = os.path.join(os.environ.get("HESTIA_HOME") or os.path.expanduser("~/.hestia"),
                            "reputation-deltas.jsonl")


def census(lines, since: str = "", until: str = "") -> dict[str, dict]:
    """{subject_lct: {warned, closed, outcomes, unclosed_sample}} over [since, until)."""
    warned: dict[str, set] = defaultdict(set)
    outcome_ids: dict[str, set] = defaultdict(set)
    outcomes: dict[str, int] = defaultdict(int)
    for raw in lines:
        try:
            r = json.loads(raw)
        except (ValueError, TypeError):
            continue
        if not isinstance(r, dict):
            continue
        subj, aid, why = r.get("subject_lct"), r.get("action_id"), r.get("reason") or ""
        if not subj or not aid:
            continue
        ts = r.get("timestamp") or ""
        if why.startswith("outcome:"):
            # Outcomes are joined WITHOUT the window: a warn at 23:59 closed at 00:01 is closed.
            outcome_ids[subj].add(aid)
            if (not since or ts >= since) and (not until or ts < until):
                outcomes[subj] += 1
        elif why.startswith("gate:warn") and (not since or ts >= since) and (not until or ts < until):
            warned[subj].add(aid)
    out = {}
    for subj in sorted(set(warned) | set(outcomes)):
        w = warned.get(subj, set())
        closed = w & outcome_ids.get(subj, set())
        out[subj] = {"warned": len(w), "closed": len(closed), "outcomes": outcomes.get(subj, 0),
                     "rate": (len(closed) / len(w)) if w else None,
                     "unclosed_sample": sorted(w - closed)[:3]}
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--sink", default=DEFAULT_SINK)
    ap.add_argument("--since", default="", help="ISO timestamp prefix, inclusive")
    ap.add_argument("--until", default="", help="ISO timestamp prefix, exclusive")
    ap.add_argument("--label", action="append", default=[], metavar="LCT=NAME")
    ap.add_argument("--min-rate", type=float, default=None)
    ap.add_argument("--min-warns", type=int, default=5)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    labels = dict(x.split("=", 1) for x in a.label if "=" in x)
    with open(a.sink, "rb") as fh:
        res = census(fh, a.since, a.until)
    if a.json:
        print(json.dumps({labels.get(k, k): v for k, v in res.items()}, indent=2))
    else:
        print(f"warned acts closed by a same-id outcome  (sink {a.sink}; since {a.since or 'start'}"
              f"{'; until ' + a.until if a.until else ''})")
        for subj, v in res.items():
            rate = "   n/a" if v["rate"] is None else f"{v['rate']:6.1%}"
            thin = "  (thin sample)" if v["warned"] < a.min_warns else ""
            print(f"  {labels.get(subj, subj):44} {v['closed']:6} / {v['warned']:<6} {rate}"
                  f"   outcomes {v['outcomes']}{thin}")
    if a.min_rate is None:
        return 0
    failing = [labels.get(s, s) for s, v in res.items()
               if v["warned"] >= a.min_warns and (v["rate"] or 0.0) < a.min_rate]
    if failing:
        print(f"BELOW {a.min_rate:.0%}: {', '.join(failing)}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
