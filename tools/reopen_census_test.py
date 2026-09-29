#!/usr/bin/env python3
"""Pins for `reopen_census.grade` -- the grader that sizes "one act, one ruling" (#668).

The whole finding rests on ONE classification: at the moment the gate re-asked for an act
already on file, what state was the prior petition in? A grader that put a spent grant in
the PENDING bucket would size the fold by a population it does not retire; one that put a
pending twin in STALE would say the fold retires nothing. Each bucket gets a fixture here,
built from the real event shapes (`gate_escalation_opened` with `act_digest`/`expires_at`,
`gate_escalation_decided` with `status`, `gate_escalation_claimed`), timestamps synthetic.

House style: module-scope assertions, exit 1 on any failure (tools/ci_selfexec_test.py).
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from reopen_census import grade  # noqa: E402

FAILS = []


def check(cond, msg):
    if not cond:
        FAILS.append(msg)


def iso(secs):
    return "2026-09-01T06:%02d:%02dZ" % (secs // 60, secs % 60)


def opened(i, at, digest="d1", plugin="claude-code", marker="m", ttl=3600):
    return {"_t": "gate_escalation_opened", "_ts": iso(at), "escalation_id": i,
            "plugin_id": plugin, "marker": marker, "act_digest": digest,
            "expires_at": 1788243000 + at + ttl}


def decided(i, at, status="approved"):
    return {"_t": "gate_escalation_decided", "_ts": iso(at), "escalation_id": i, "status": status}


def claimed(i, at):
    return {"_t": "gate_escalation_claimed", "_ts": iso(at), "escalation_id": i}


# opened() encodes expires_at against a fixed epoch while _ts is a wall clock; make the
# PENDING test independent of that by keeping every re-open inside a generous ttl.

# 1. the retirable class: re-asked while the first is still undecided (b4b410f1 / 4ec27c68)
g = grade([opened("a", 0), opened("b", 9)])
check(g["grades"] == {"prior PENDING": 1}, f"pending twin: {g['grades']}")
check(g["ids_per_act"] == 2.0 and g["distinct_acts"] == 1, f"inflation: {g}")

# 2. spent inside the window: a real second act, NOT retirable
g = grade([opened("a", 0), decided("a", 20), claimed("a", 40), opened("b", 100)])
check(g["grades"] == {"prior approved+SPENT (<=600s)": 1}, f"spent<=600: {g['grades']}")

# 3. spent, then re-asked much later
g = grade([opened("a", 0), decided("a", 20), claimed("a", 40), opened("b", 1000)])
check(g["grades"] == {"prior approved+SPENT (>600s)": 1}, f"spent>600: {g['grades']}")

# 4. approved, never spent, re-asked after the claim window: a legitimate new ask
g = grade([opened("a", 0), decided("a", 20), opened("b", 700)])
check(g["grades"] == {"prior approved, STALE (>600s)": 1}, f"stale: {g['grades']}")

# 5. approved, unspent, re-asked INSIDE the window: the claim-door leak (0 observed on CBP)
g = grade([opened("a", 0), decided("a", 20), opened("b", 100)])
check(g["grades"] == {"prior approved, LIVE unspent grant (claim-door leak)": 1},
      f"live-unspent: {g['grades']}")

# 6. denied, re-petitioned
g = grade([opened("a", 0), decided("a", 20, "denied"), opened("b", 100)])
check(g["grades"] == {"prior DENIED": 1}, f"denied: {g['grades']}")

# 7. the grader compares to the LATEST prior open, not the first: a->b (pending), b->c
#    after b was spent. Two re-opens, two different buckets.
g = grade([opened("a", 0), opened("b", 9), decided("b", 30), claimed("b", 50), opened("c", 200)])
check(g["reopens"] == 2 and g["grades"].get("prior PENDING") == 1
      and g["grades"].get("prior approved+SPENT (<=600s)") == 1, f"latest-prior: {g['grades']}")

# 8. a different digest, marker, or seat is a different act -- no re-open counted
g = grade([opened("a", 0), opened("b", 9, digest="d2"), opened("c", 10, marker="other"),
           opened("d", 11, plugin="kimi-code")])
check(g["reopens"] == 0 and g["distinct_acts"] == 4, f"keys: {g}")

# 9. opens without a digest (pre-#539 rows) are counted but never grouped
g = grade([opened("a", 0), {"_t": "gate_escalation_opened", "_ts": iso(5), "escalation_id": "z",
                            "plugin_id": "claude-code", "marker": "m", "act_digest": None}])
check(g["opened"] == 2 and g["opened_with_digest"] == 1, f"no-digest: {g}")

if FAILS:
    for f in FAILS:
        print("FAIL:", f)
    sys.exit(1)
print("ok: reopen_census.grade pinned on 9 fixtures")
