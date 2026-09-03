#!/usr/bin/env python3
"""Who FILED a peer factor vs whose PETITION it sits on — from a walk dump, both keyings.

Why this exists (2026-09-02):

`grounds_vs_acts.py` (kimi/self-consistency-instrument @6ac8e85) builds its "conduct
register" with

    if (d.get("plugin_id") or d.get("by")) == seat: factors.append(e)

on `gate_escalation_corroborated` events. That payload has NO `by` key, and its
`plugin_id` is the ASKER's (the handler writes `"plugin_id": updated.plugin_id` and the
filer as `"corroborated_by": arb.plugin_id`, core/src/server/handler.rs). So every
per-seat number the instrument printed counts factors filed ON the seat's petitions BY
OTHERS, not factors the seat filed. Measured on the same 212,550-hop dump:

    keyed on plugin_id (asker)        keyed on corroborated_by (filer)
    claude-code 168 (116 post)        claude-code  89 (49 post)
    kimi-code   104 ( 57 post)        kimi-code   120 (90 post)
    codex        23 ( 15 post)        codex        85 (49 post)

`plugin_id == corroborated_by` holds for 0 of 295 events — the two keys never agree, so
the swap is total, not partial. The "57 vs 7454's 55" agreement the instrument's writeup
cited as validation was a coincidence between two different populations.

This script prints both keyings side by side so the next reader sees which one a claim
used. It also reconciles decided-row `factors_present` (the decider's snapshot) against
the corroborated event log by (escalation_id, filer) — the three quantities of kimi's
8879 amendment plus a classification the amendment did not make: snapshot factors with an
event BEFORE the decision, with an event AFTER it (append lag), or with NO event at all.

Input: a dump written by `grounds_vs_acts.py --cache-out` (any walk that keeps the
`gate_escalation_*` entries with `eventData`). Read-only; touches no daemon.

Usage:
    python3 tools/factor_attribution_census.py /tmp/walk.json
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from datetime import datetime

TERMINAL = ("gate_escalation_decided", "gate_escalation_expired", "gate_escalation_withdrawn")


def ts(e):
    t = e.get("timestamp") or ""
    try:
        return datetime.fromisoformat(t[:26] + "+00:00")
    except ValueError:
        return None


def main(path: str) -> int:
    dump = json.load(open(path))
    ev = dump["events"]
    print(f"walk: complete={dump.get('complete')} hops={dump.get('walked_hops')} "
          f"events={len(ev)} span={dump.get('span')}")

    corr = [e for e in ev if e["eventType"] == "gate_escalation_corroborated"]
    keys = Counter(k for e in corr for k in (e.get("eventData") or {}))
    print(f"corroborated events: {len(corr)}; events carrying a 'by' key: {keys.get('by', 0)}; "
          f"carrying 'plugin_id': {keys.get('plugin_id', 0)}; carrying 'corroborated_by': "
          f"{keys.get('corroborated_by', 0)}")
    same = sum(1 for e in corr
               if e["eventData"].get("plugin_id") == e["eventData"].get("corroborated_by"))
    print(f"plugin_id == corroborated_by on {same} of {len(corr)} events")

    terminal = {}
    decided = {}
    for e in ev:
        d = e.get("eventData") or {}
        eid = d.get("escalation_id")
        if not eid:
            continue
        if e["eventType"] in TERMINAL:
            terminal[eid] = e
        if e["eventType"] == "gate_escalation_decided":
            decided[eid] = e

    for key, label in (("plugin_id", "ASKER (whose petition)"),
                       ("corroborated_by", "FILER (who wrote the factor)")):
        tab: dict[str, Counter] = defaultdict(Counter)
        for e in corr:
            d = e["eventData"]
            seat = d.get(key)
            t = terminal.get(d.get("escalation_id"))
            te, tc = (ts(t) if t else None), ts(e)
            if t is None or te is None or tc is None:
                tab[seat]["no_terminal"] += 1
            elif (tc - te).total_seconds() <= 0:
                tab[seat]["pre"] += 1
            else:
                tab[seat]["post"] += 1
        print(f"\nkeyed on {key} = {label}:")
        for s, c in sorted(tab.items(), key=lambda x: str(x[0])):
            print(f"    {s!s:14} total={sum(c.values()):4}  pre={c['pre']:3}  post={c['post']:3}  "
                  f"no_terminal={c['no_terminal']:3}")

    # Snapshot register vs event register (8879's three quantities + the missing split).
    by_esc = defaultdict(list)
    for e in corr:
        by_esc[e["eventData"].get("escalation_id")].append(e)
    q1 = 0
    rows = 0
    cls = Counter()
    for eid, e in decided.items():
        fs = (e["eventData"].get("factors_present") or [])
        peers = [f for f in fs if f.get("channel") == "peer_member"]
        if peers:
            rows += 1
        q1 += len(peers)
        dts = ts(e)
        for f in peers:
            cands = [c for c in by_esc.get(eid, [])
                     if c["eventData"].get("corroborated_by") == f.get("by")]
            if not cands:
                cls["no_event"] += 1
            elif any(ts(c) and dts and ts(c) <= dts for c in cands):
                cls["event_before_decision"] += 1
            else:
                cls["event_after_decision"] += 1
    q2 = sum(1 for eid, cs in by_esc.items() if eid in decided
             for c in cs if ts(c) and ts(decided[eid]) and ts(c) <= ts(decided[eid]))
    q3 = sum(1 for eid, cs in by_esc.items() if eid in terminal
             for c in cs if ts(c) and ts(terminal[eid]) and ts(c) <= ts(terminal[eid]))
    print(f"\npeer factors in decided snapshots (factors_present): {q1} across {rows} rows")
    print(f"  matched to an event by (escalation, filer): {dict(cls)}")
    print(f"corroborated events <= decision: {q2}")
    print(f"corroborated events <= any terminal: {q3}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/walk.json"))
