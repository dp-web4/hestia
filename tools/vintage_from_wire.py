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
import argparse, json, sys

sys.path.insert(0, "/mnt/c/exe/projects/ai-agents/private-context/hestia-local/probes")
import chainwalk  # noqa: E402  — the ONE wrapped chain cursor; do not hand-roll a sixth


def partition(event_type, field, hops=9000, progress=3000):
    """Walk the chain, split `event_type` rows on presence of `field`."""
    c = chainwalk.Chain()
    with_f, without_f = [], []
    walked = 0
    for e in c.walk(max_hops=hops, progress=progress):
        walked += 1
        if e["eventType"] != event_type:
            continue
        p = chainwalk.payload(e)
        row = {"ts": e["timestamp"][:19], "pos": e["chainPosition"],
               "plugin": p.get("plugin_id")}
        (with_f if p.get(field) is not None else without_f).append(row)
    with_f.sort(key=lambda r: r["ts"])
    without_f.sort(key=lambda r: r["ts"])
    # Interleaving: any row lacking the field that is NEWER than the oldest row carrying
    # it. One cutover means zero such rows.
    inter = []
    if with_f and without_f:
        first_with = with_f[0]["ts"]
        inter = [r for r in without_f if r["ts"] > first_with]
    return {
        "event_type": event_type, "field": field, "hops_walked": walked,
        "rows": len(with_f) + len(without_f),
        "with": with_f, "without": without_f, "interleaved": inter,
    }


def report(r):
    n = r["rows"]
    if n == 0:
        return f"no {r['event_type']} rows in {r['hops_walked']} hops — widen --hops"
    w, wo = r["with"], r["without"]
    span = f"{(wo + w)[0]['ts']} -> {sorted(wo + w, key=lambda x: x['ts'])[-1]['ts']}"
    out = [f"{r['event_type']}: {n} rows over {span}",
           f"  without {r['field']!r}: {len(wo):<4} (newest {wo[-1]['ts'] if wo else '-'})",
           f"  with    {r['field']!r}: {len(w):<4} (oldest {w[0]['ts'] if w else '-'})",
           f"  interleaved: {len(r['interleaved'])}"
           + ("  -> CLEAN PARTITION" if not r["interleaved"] else
              "  -> NOT A DEPLOYMENT BOUNDARY (multiple writers, a conditional field, "
              "or the wrong commit)")]
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
