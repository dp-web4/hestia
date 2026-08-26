#!/usr/bin/env python3
"""Date a deployment's IN-FORCE time from the chain, not from git.

WHY THIS EXISTS. #606/#607/#509 all rest on "nothing names the vintage the mesh is
actually executing." That is true of the mesh fire scripts, which the watchers exec by
argv path out of a shared dev tree parked on a branch. It is NOT true of anything whose
change alters a CHAIN PAYLOAD, because the chain records what the running code emitted.

A field that a known commit adds to a payload PARTITIONS the chain: absent below the
cutover, present above it. Find the boundary and you have the deployment's in-force
timestamp, to the resolution of traffic — no installer, no restart log, no self-report.
Self-report is the failure mode #567's own guard fell into: it pinned SOURCE and printed
"all checks passed" while the RENDER was broken.

Worked example, the one this tool was extracted from (2026-08-26, CBP):

    $ python3 tools/vintage_from_wire.py gate_escalation_opened act_digest --hops 9000
    gate_escalation_opened: 63 rows over 2026-08-24T03:16:05 -> 2026-08-26T04:12:30
      without 'act_digest': 15   (newest 2026-08-25T05:17:03)
      with    'act_digest': 48   (oldest 2026-08-25T17:38:30)
      interleaved: 0  -> CLEAN PARTITION
      IN FORCE BETWEEN 2026-08-25T05:17:03 AND 2026-08-25T17:38:30

`act_digest` and the claim-side comparison that reads it landed in ONE commit (419dbcc,
#539 step 1), so that boundary is also when act binding started DECIDING. The
checked-out tree at the time (5cf6773, 08-19) carried neither — which is how a peer
reading claim() out of that tree concluded the digest was "never consulted" and was
wrong against the daemon actually running.

INTERLEAVING IS THE WHOLE TEST. A clean partition means one cutover. A nonzero
interleave count means either (a) more than one daemon is writing this chain, (b) the
field is conditional on something other than vintage, or (c) you picked a field that
predates the commit you think added it. In all three cases the boundary is NOT a
deployment date and this tool says so rather than printing a plausible timestamp.

ABSENCE NEEDS A DENOMINATOR. `--hops` bounds the walk; if the OLDEST row reached still
carries the field, the cutover is below the window and the answer is "not found in N
hops", never "always present". Same for the other end.

Usage:
    python3 tools/vintage_from_wire.py <eventType> <field> [--hops N] [--json]
"""
import argparse
import json
import os
import sys

# The PUBLIC walker, vendored from this same repository (codex review of #614, finding 3).
# The first draft imported a host-specific private checkout by absolute path, which made
# both the tool and its tests unrunnable in any public checkout — the same defect codex
# raised against #615. `tools/` is on the path because this file lives in it.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chain_walk import ChainWalker, payload  # noqa: E402


def partition(event_type, field, hops=9000, walker=None):
    """Walk the chain, split `event_type` rows on PRESENCE of `field`.

    PRESENCE, NOT TRUTHINESS (codex review of #614, finding 1). The first draft tested
    `p.get(field) is not None`, which classifies an explicitly-null value as absent. A
    schema that emits the key with a null — exactly what a partially-deployed writer
    does — would then manufacture a deployment boundary that never happened. `field in p`
    is the presence test; null-valued rows are counted SEPARATELY and reported, because
    they are evidence about the writer rather than about the cutover.

    ORDER IS `chainPosition`, NOT A TRUNCATED TIMESTAMP (finding 2). The first draft
    sorted and compared on `timestamp[:19]`, discarding subsecond precision, and compared
    with a strict `>`. A present row followed in the SAME SECOND by an absent row then
    scored zero interleaving and printed CLEAN PARTITION over a contradiction. The chain
    position is the chain's own total order and has no such collision.
    """
    c = walker or ChainWalker()
    with_f, without_f, null_valued = [], [], []
    walked = 0
    for e in c.walk(max_entries=hops):
        walked += 1
        if e.get("eventType") != event_type:
            continue
        p = payload(e)
        row = {"ts": e.get("timestamp"), "pos": e.get("chainPosition"),
               "plugin": p.get("plugin_id")}
        if field in p:
            with_f.append(row)
            if p[field] is None:
                null_valued.append(row)
        else:
            without_f.append(row)

    key = lambda r: (r["pos"] if r["pos"] is not None else -1, r["ts"] or "")
    with_f.sort(key=key)
    without_f.sort(key=key)
    # One cutover means: no row LACKING the field sits above the oldest row CARRYING it,
    # in chain order. `>=` rather than `>` so a same-position tie cannot hide a conflict.
    inter = []
    if with_f and without_f:
        first = key(with_f[0])
        inter = [r for r in without_f if key(r) >= first]
    return {
        "event_type": event_type, "field": field, "hops_walked": walked,
        "rows": len(with_f) + len(without_f),
        "with": with_f, "without": without_f, "interleaved": inter,
        "null_valued": null_valued,
    }


def report(r):
    n = r["rows"]
    if n == 0:
        return f"no {r['event_type']} rows in {r['hops_walked']} hops — widen --hops"
    w, wo = r["with"], r["without"]
    allrows = sorted(w + wo, key=lambda x: (x["pos"] if x["pos"] is not None else -1))
    span = f"{allrows[0]['ts']} -> {allrows[-1]['ts']}"
    out = [f"{r['event_type']}: {n} rows over {span}",
           f"  without {r['field']!r}: {len(wo):<4} (newest {wo[-1]['ts'] if wo else '-'})",
           f"  with    {r['field']!r}: {len(w):<4} (oldest {w[0]['ts'] if w else '-'})",
           f"  interleaved: {len(r['interleaved'])}"
           + ("  -> CLEAN PARTITION" if not r["interleaved"] else
              "  -> NOT A DEPLOYMENT BOUNDARY (multiple writers, a conditional field, "
              "or the wrong commit)")]
    if r["null_valued"]:
        out.append(f"  {len(r['null_valued'])} rows carry {r['field']!r} as an explicit "
                   f"NULL — the key is present, so these do NOT date a cutover; they say "
                   f"the writer emits the field without a value")
    if not wo:
        out.append(f"  field present on the OLDEST row reached — cutover is below "
                   f"{r['hops_walked']} hops, not 'always present'")
    elif not w:
        out.append(f"  field absent from the NEWEST row reached — not deployed, or this "
                   f"chain has no traffic since it was")
    elif not r["interleaved"]:
        out.append(f"  IN FORCE BETWEEN {wo[-1]['ts']} AND {w[0]['ts']}")
    return "\n".join(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("event_type")
    ap.add_argument("field")
    ap.add_argument("--hops", type=int, default=9000)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()
    res = partition(a.event_type, a.field, a.hops)
    print(json.dumps(res, indent=2) if a.json else report(res))
