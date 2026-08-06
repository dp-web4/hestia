#!/usr/bin/env python3
"""Census the `outcome` event class — the fleet's largest evidence body, never read.

WHY. Eight mesh notices between 2026-07-31 and 2026-08-06 audited the escalation /
appeal / permit machinery. The lifetime chain census (2026-08-06) put that machinery
behind **10 appeals ever** and **0 peer factors ever**, against ~91k `outcome` rows
nobody had opened. Attention followed the notice graph, not the traffic. This walks the
traffic.

The question is not "how many acts" (known) but "does an outcome row carry evidence a
governance surface could use, or is it a degenerate log?" So every field is profiled for
CONSTANCY: a field with one distinct value over 91k rows records nothing, however
well-schema'd it looks.

Second question, from the permit thread: `outcome` rows carry `instance_lct` and
`session_id`. `gate_escalation_opened` rows are the ones whose attribution is missing
(31/63 spent permits name no member). If the witness path already records the instance
for every act while the escalation path does not, the identity fix kimi and I priced as
a larger change is partly already-collected data.

Usage: python3 outcome_traffic_census.py [--max N] [--out report.json]
Reads via chain_walk.ChainWalker (the one correct reader; see its docstring for the
four traps in hestia_query_history).
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict

from chain_walk import ChainWalker, payload

# Fields profiled for constancy on `outcome`. A field whose distinct-count is 1 over the
# whole population is reported as CONSTANT — that is the finding, not a footnote.
SCALAR_FIELDS = (
    "success", "magnitude", "intent", "plugin_id", "role_lct", "tool_name",
    "closure_claims_schema", "signer_hint",
)
# Identity fields: the census cares whether they are PRESENT and how many distinct
# values they take, not what they are.
ID_FIELDS = ("instance_lct", "session_id", "host_session_id", "action_id")

# The escalation events whose attribution gap started this thread. Compared on the same
# fields so the asymmetry is measured, not asserted.
ESC_TYPES = ("gate_escalation_opened", "gate_escalation_decided", "gate_escalation_claimed")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=200_000)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    w = ChainWalker()
    n = 0
    types = Counter()
    # outcome profile
    scalars = {f: Counter() for f in SCALAR_FIELDS}
    ids = {f: Counter() for f in ID_FIELDS}
    id_missing = Counter()
    closure_nonempty = 0
    closure_examples = []
    err_nonnull = 0
    err_examples = Counter()
    fail_rows = []           # success is not True
    key_shapes = Counter()   # the exact key SET, to catch schema drift across 82 days
    outcome_n = 0
    per_plugin_success = defaultdict(Counter)
    # instance/session cardinality per plugin — the identity question
    plugin_instances = defaultdict(set)
    plugin_sessions = defaultdict(set)
    first_ts = last_ts = None
    # escalation-side comparison
    esc_n = Counter()
    esc_field_present = defaultdict(Counter)

    for e in w.walk(max_entries=args.max):
        n += 1
        et = e.get("eventType")
        types[et] += 1
        ts = e.get("timestamp")
        if ts:
            if last_ts is None:
                last_ts = ts
            first_ts = ts
        d = payload(e) or {}

        if et in ESC_TYPES:
            esc_n[et] += 1
            for f in ID_FIELDS + ("plugin_id", "decided_at", "subject_lct", "member_lct"):
                esc_field_present[et]["present" if d.get(f) not in (None, "") else "absent"] += 0
                esc_field_present[et][f + (":present" if d.get(f) not in (None, "") else ":absent")] += 1
            continue

        if et != "outcome":
            continue
        outcome_n += 1
        key_shapes[",".join(sorted(d.keys()))] += 1
        for f in SCALAR_FIELDS:
            v = d.get(f, "<<absent>>")
            scalars[f][json.dumps(v) if not isinstance(v, str) else v] += 1
        for f in ID_FIELDS:
            v = d.get(f)
            if v in (None, ""):
                id_missing[f] += 1
            else:
                ids[f][v] += 1
        pid = d.get("plugin_id") or "<<none>>"
        if d.get("instance_lct"):
            plugin_instances[pid].add(d["instance_lct"])
        if d.get("session_id"):
            plugin_sessions[pid].add(d["session_id"])
        sc = d.get("success")
        per_plugin_success[pid][json.dumps(sc)] += 1
        if sc is not True:
            fail_rows.append({
                "ts": ts, "plugin_id": pid, "tool": d.get("tool_name"),
                "success": sc, "error": d.get("error"),
                "target": (d.get("target") or "")[:200],
            })
        if d.get("error") not in (None, ""):
            err_nonnull += 1
            err_examples[str(d.get("error"))[:120]] += 1
        cc = d.get("closure_claims")
        if cc:
            closure_nonempty += 1
            if len(closure_examples) < 5:
                closure_examples.append({"ts": ts, "claims": cc})

    def profile(counter: Counter, cap: int = 8) -> dict:
        return {
            "distinct": len(counter),
            "constant": len(counter) == 1,
            "top": counter.most_common(cap),
        }

    report = {
        "walked": n,
        "span": {"oldest": first_ts, "newest": last_ts},
        "event_types": types.most_common(20),
        "outcome_n": outcome_n,
        "key_shapes": {"distinct": len(key_shapes), "top": key_shapes.most_common(5)},
        "scalar_fields": {f: profile(scalars[f]) for f in SCALAR_FIELDS},
        "id_fields": {
            f: {"present": sum(ids[f].values()), "missing": id_missing[f],
                "distinct": len(ids[f])}
            for f in ID_FIELDS
        },
        "success": {
            "not_true_count": len(fail_rows),
            "per_plugin": {k: dict(v) for k, v in per_plugin_success.items()},
            "examples": fail_rows[:20],
        },
        "error_field": {"nonnull": err_nonnull, "top": err_examples.most_common(10)},
        "closure_claims": {"nonempty": closure_nonempty, "examples": closure_examples},
        "identity_cardinality": {
            p: {"instances": len(plugin_instances.get(p, ())),
                "sessions": len(plugin_sessions.get(p, ()))}
            for p in sorted(set(plugin_instances) | set(plugin_sessions))
        },
        "escalation_side": {
            "counts": dict(esc_n),
            "field_presence": {k: dict(v) for k, v in esc_field_present.items()},
        },
    }
    out = json.dumps(report, indent=1, sort_keys=True)
    if args.out:
        with open(args.out, "w") as fh:
            fh.write(out)
    print(out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
