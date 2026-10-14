#!/usr/bin/env python3
"""#1290 — how often does a peer-approved ONCE scope grant get spent?

The bind is `scope_act_digest` = sha256(tool, input, cwd, host_session_id). The peer
channel is asynchronous: the ruling arrives minutes later, usually after the asker's
wake (and host session) has ended — so the re-issued "identical act" mints a FRESH
request instead of spending the approval. The issue has the mechanism and three
specimens; this census supplies the population.

Join over the chain (newest-first walk, bounded):
  scope_requested  (request_id, plugin_id, host_session_id, act_digest, expires_at)
  scope_granted    (request_id, once?, decided_by, timestamp)
  scope_once_spent (request_id, timestamp)
  scope_refused    (request_id)

Reports: once-approved -> spent/unspent; decision latency vs the 600s claim window;
and for unspent rows, whether a LATER scope_requested for the same (plugin_id, path)
appeared after the grant — the observable shape of "the re-issue minted a new request".

Read-only. Usage: python3 tools/scope_once_spend_census.py [MAX_ENTRIES]
"""
from __future__ import annotations

import json
import sys
from collections import defaultdict
from datetime import datetime, timezone

from chain_walk import ChainWalker, payload

MAX = int(sys.argv[1]) if len(sys.argv) > 1 else 120_000
KINDS = frozenset({"scope_requested", "scope_granted", "scope_refused", "scope_once_spent"})


def epoch(ts):
    if not isinstance(ts, str):
        return None
    try:
        return datetime.fromisoformat(ts).timestamp()
    except ValueError:
        return None


def main() -> int:
    w = ChainWalker()
    reqs, grants, spends, refuses = {}, {}, {}, set()
    walked = 0
    for entry in w.walk(max_entries=MAX):
        walked += 1
        if entry.get("eventType") not in KINDS:
            continue
        d = payload(entry)
        # The single-claim door writes `request_id`; the atomic batch door
        # (`_spend_scope`, one commit for every path the act needed) writes
        # `request_ids` — plural. Both are spends.
        rids = ([d["request_id"]] if d.get("request_id") else []) + list(d.get("request_ids") or [])
        at = epoch(entry.get("timestamp"))
        et = entry["eventType"]
        for rid in rids:
            if et == "scope_requested":
                reqs.setdefault(rid, {"plugin": d.get("plugin_id"), "path": d.get("path"),
                                      "session": d.get("host_session_id"),
                                      "digest": d.get("act_digest"), "at": at,
                                      "expires_at": d.get("expires_at")})
            elif et == "scope_granted":
                grants.setdefault(rid, {"once": bool(d.get("once")),
                                        "by": d.get("granted_by") or d.get("decided_by"), "at": at})
            elif et == "scope_once_spent":
                spends.setdefault(rid, at)
            elif et == "scope_refused":
                refuses.add(rid)

    once = {r: g for r, g in grants.items() if g["once"]}
    spent = {r: s for r, s in spends.items() if r in once}
    unspent = [r for r in once if r not in spends]

    lat = sorted(g["at"] - reqs[r]["at"] for r, g in once.items()
                 if r in reqs and reqs[r]["at"] is not None and g["at"] is not None)
    med = lat[len(lat) // 2] if lat else None

    reasks = 0
    reask_rows = []
    by_pp = defaultdict(list)
    for r, q in reqs.items():
        by_pp[(q["plugin"], q["path"])].append((q["at"], r))
    for r in unspent:
        q, g = reqs.get(r), grants[r]
        if not q:
            continue
        later = [rid for (t, rid) in by_pp[(q["plugin"], q["path"])]
                 if t is not None and g["at"] is not None and t > g["at"] and rid != r]
        if later:
            reasks += 1
            reask_rows.append({"request_id": r, "later_requests": later})

    out = {
        "walked": walked,
        "scope_requested": len(reqs),
        "granted_total": len(grants),
        "granted_once": len(once),
        "once_spent": len(spent),
        "once_unspent": len(unspent),
        "once_unspent_with_later_reask_same_path": reasks,
        "reask_rows": reask_rows,
        "refused": len(refuses),
        "decision_latency_secs_median": med,
        "decision_latency_secs_max": (lat[-1] if lat else None),
        "decision_latency_over_600s": sum(1 for v in lat if v > 600),
        "deciders_once": sorted({g["by"] for g in once.values() if g["by"]}),
        "unspent_rows": [
            {"request_id": r,
             "plugin": (reqs.get(r) or {}).get("plugin"),
             "decided_by": once[r]["by"],
             "decision_latency_s": (once[r]["at"] - reqs[r]["at"]
                                    if reqs.get(r) and reqs[r]["at"] and once[r]["at"] else None)}
            for r in sorted(unspent)
        ],
    }
    json.dump(out, sys.stdout, indent=1)
    print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
