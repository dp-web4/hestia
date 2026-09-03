#!/usr/bin/env python3
"""Same-act re-opens: how many petitions did ONE act cost, and what state was the prior
petition in when the gate asked again?  (#668 — the number PR "one act, one ruling" is sized by.)

Why this exists
---------------
`gate_escalation_opened` carries `act_digest` (since #539). Grouping opens by
(plugin_id, marker, act_digest) and ordering by time gives, for every re-open, the state of
the LATEST prior open of the same act at the moment the gate asked again:

  prior PENDING                 -> the class `open_or_coalesce` retires: nothing distinguished
                                   the second ask from the first, and the operator paid twice
  prior approved + SPENT        -> a real second act (single-use grant already consumed)
  prior approved, LIVE unspent  -> a claim-door leak (a matching claim should have spent it)
  prior approved, STALE (>600s) -> a legitimate new ask
  prior DENIED / EXPIRED-unruled-> a refusal the member re-petitioned

Measured on CBP 2026-09-01 over 120,000 chain entries (2026-08-02 .. 2026-09-01):
210 digested opens, 161 distinct acts (1.30x), 49 re-opens: 25 prior-PENDING, 11 spent<=600s,
6 spent>600s, 7 stale, 0 live-unspent.

Usage
-----
    python3 tools/reopen_census.py [--max 120000] [--endpoint URL]
    python3 tools/reopen_census.py --from-jsonl events.jsonl   # re-grade a saved walk

Prints the grade table and writes nothing. Walk cost is contention-dependent (~1 ms/hop idle
on CBP, 10x under load) — run a 120k walk in the background. `--max` is a WINDOW, not the
population: the span it covered is printed so the reader can see what was and was not read.
"""
import argparse
import collections
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chain_walk import ChainWalker, payload  # noqa: E402

CLAIM_WINDOW_SECS = 600
KINDS = {"gate_escalation_opened", "gate_escalation_decided", "gate_escalation_claimed"}


def ts(s):
    return datetime.fromisoformat(str(s).replace("Z", "+00:00")).timestamp()


def collect(walker, max_entries):
    out = []
    for e in walker.walk(max_entries=max_entries):
        t = e.get("eventType") or e.get("event_type") or ""
        if t in KINDS:
            p = dict(payload(e) or {})
            p["_t"] = t
            p["_ts"] = e.get("timestamp")
            out.append(p)
    return out


def grade(rows):
    rows = sorted(rows, key=lambda r: r["_ts"])
    opened, decided, claimed = {}, {}, {}
    for r in rows:
        {"gate_escalation_opened": opened, "gate_escalation_decided": decided,
         "gate_escalation_claimed": claimed}[r["_t"]][r.get("escalation_id")] = r
    groups = collections.defaultdict(list)
    for r in opened.values():
        if r.get("act_digest"):
            groups[(r.get("plugin_id"), r.get("marker"), r["act_digest"])].append(r)
    grades = collections.Counter()
    per_seat = collections.Counter()
    gaps = []
    for key, v in groups.items():
        for idx in range(1, len(v)):
            r, prior = v[idx], v[idx - 1]
            t, pid = ts(r["_ts"]), prior["escalation_id"]
            dec, cl = decided.get(pid), claimed.get(pid)
            gaps.append(t - ts(prior["_ts"]))
            per_seat[key[0]] += 1
            if dec is None or t < ts(dec["_ts"]):
                g = "prior PENDING" if t < prior.get("expires_at", 0) else "prior EXPIRED-unruled"
            elif dec.get("status") != "approved":
                g = "prior DENIED"
            elif cl and ts(cl["_ts"]) < t:
                g = "prior approved+SPENT (%s)" % ("<=600s" if t - ts(dec["_ts"]) <= CLAIM_WINDOW_SECS else ">600s")
            elif t - ts(dec["_ts"]) <= CLAIM_WINDOW_SECS:
                g = "prior approved, LIVE unspent grant (claim-door leak)"
            else:
                g = "prior approved, STALE (>600s)"
            grades[g] += 1
    with_digest = sum(len(v) for v in groups.values())
    return {
        "span": (rows[0]["_ts"][:19] if rows else None, rows[-1]["_ts"][:19] if rows else None),
        "opened": len(opened), "decided": len(decided), "claimed": len(claimed),
        "opened_with_digest": with_digest, "distinct_acts": len(groups),
        "ids_per_act": round(with_digest / len(groups), 2) if groups else None,
        "reopens": sum(grades.values()), "grades": dict(grades.most_common()),
        "reopens_per_seat": dict(per_seat),
        "reopen_gap_secs": {"median": sorted(gaps)[len(gaps) // 2], "max": max(gaps)} if gaps else None,
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=120_000)
    ap.add_argument("--endpoint", default=None)
    ap.add_argument("--from-jsonl", default=None)
    a = ap.parse_args()
    if a.from_jsonl:
        rows = [json.loads(l) for l in open(a.from_jsonl) if l.strip()]
        rows = [r for r in rows if r.get("_t") in KINDS]
    else:
        w = ChainWalker(a.endpoint) if a.endpoint else ChainWalker()
        rows = collect(w, a.max)
    print(json.dumps(grade(rows), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
