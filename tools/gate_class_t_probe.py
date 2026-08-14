#!/usr/bin/env python3
"""Class T pair-audit probe — PRD gate-consolidation §7.4 criterion 10's gauge.

Reads the reputation-deltas ledger over a window and reports, PER MEMBER:
  * gate denies split real-deny vs infra/timeout (fail-closed) — the visible arm;
  * positive verdict-reached evidence (outcome records) — the arm Class T needs,
    because a fully un-governed member produces NO denies and a CLEAN chain
    (docs/GATE_BYPASS_CATALOG.md §17: absence of refusals is also what a genuine fix
    produces; they must be told apart by evidence that verdicts are still REACHED).

Criterion 10 reading: with the box idle, the per-member timeout rate should be ≈0 and
EQUAL across members, while verdict-reached counts stay >0 for every active member.
A member with acts recorded but zero reached-verdicts is the Class T signature.

Usage: python3 tools/gate_class_t_probe.py [--hours 6] [--ledger PATH]
Read-only; no daemon required (the ledger is the daemon's own output).
"""
import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hours", type=float, default=6.0)
    ap.add_argument("--ledger", default=os.path.expanduser("~/.hestia/reputation-deltas.jsonl"))
    args = ap.parse_args()
    cutoff = datetime.now(timezone.utc) - timedelta(hours=args.hours)

    per = defaultdict(lambda: {"outcome": 0, "warn": 0, "deny_real": 0, "deny_infra": 0})
    with open(args.ledger, "rb") as fh:
        for raw in fh:
            try:
                row = json.loads(raw.decode("utf-8", "replace").strip("\x00").strip())
            except Exception:
                continue
            ts = row.get("timestamp", "")
            try:
                when = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except Exception:
                continue
            if when < cutoff:
                continue
            who = row.get("subject_lct", "?")[-12:]
            reason = row.get("reason", "")
            if reason.startswith("outcome:"):
                per[who]["outcome"] += 1
            elif reason.startswith("gate:warn"):
                per[who]["warn"] += 1
            elif reason.startswith("gate:deny"):
                # A deny that carries a rule id is a REACHED verdict; one without is the
                # fail-closed/no-verdict arm (infra), the Class T-adjacent signal.
                if row.get("rule_triggered"):
                    per[who]["deny_real"] += 1
                else:
                    per[who]["deny_infra"] += 1

    print(f"Class T probe — last {args.hours}h of {args.ledger}")
    print(f"{'member(lct tail)':16} {'reached':>8} {'warn':>6} {'deny':>6} {'infra':>6}  reading")
    for who, c in sorted(per.items()):
        reached = c["outcome"] + c["warn"] + c["deny_real"]
        if reached == 0 and (c["deny_infra"] or True):
            note = "NO REACHED VERDICTS — Class T signature if this member was active"
        elif c["deny_infra"] > max(3, reached // 10):
            note = "elevated infra fail-close rate (criterion 10 asymmetry)"
        else:
            note = "ok"
        print(f"{who:16} {reached:8} {c['warn']:6} {c['deny_real']:6} {c['deny_infra']:6}  {note}")
    if not per:
        print("  (no rows in window — a silent ledger is itself a finding: nothing is "
          "being scored, which is indistinguishable from nothing being governed)")


if __name__ == "__main__":
    main()
