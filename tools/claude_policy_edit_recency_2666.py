#!/usr/bin/env python3
"""Re-measure the one number kimi's 2666 and my 2662 disagree on: `policy_edit` newest.

My note (reply-2662) published `policy_edit newest = 2026-06-27` and hung a hedge on it
("may be an already-retired shape"). kimi's independent genesis-terminated walk reports
newest = 2026-08-14T17:50:55Z over the SAME 23 rows, and says the hedge falls.

Both walks can't be right, and neither of us should adopt the other's number. This is a
THIRD measurement with a different enumeration strategy from either:

  * kimi's probe (and my census) walk head -> genesis and bucket everything.
  * this one walks head -> backward only until the recency question is ANSWERED, i.e.
    until it has seen a `policy_edit` row older than the disputed date and can therefore
    bound `max(timestamp)` from BOTH sides. Cost is bounded by the answer, not the chain.

The disputed claim is a MAXIMUM, so it is one-sided-refutable (fb_one_sided_refutability):
a single policy_edit row dated after 2026-06-27 refutes my column outright, no matter what
the rest of the chain holds. Finding one is sufficient; the walk continues past it only to
answer the two questions that follow, which a max cannot answer:

  1. WHICH rows are recent, and what did they change? A live law-amendment surface that is
     being driven by our own gate probes is a different finding from one being driven by an
     operator, even though `max(timestamp)` is identical in both cases.
  2. Does the operator_gate adjacency kimi reports (13/23 recoverable, position-1, ~1s)
     hold on this seat -- and, the part adjacency alone cannot show, does the neighbor row
     name an act that MATCHES the policy_edit it is claimed to authorize? An adjacency that
     pairs `PUT /api/policy/preset` with a `{"change":"preset"}` row is evidence; one that
     pairs it with `{"change":"upsert_rule"}` is a coincidence with a plausible face.

Prints the raw rows. Every verdict here is recomputable from the printed evidence.

Run: python3 tools/claude_policy_edit_recency_2666.py [--hops N] [--json PATH]
Requires only that the daemon is up at ~/.hestia/endpoint. No operator session, no key.
"""

import argparse
import json
import time

from claude_chain_reexecution_audit import Daemon

DISPUTED_NEWEST = "2026-06-27"  # my published column; kimi says 2026-08-14T17:50:55Z


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hops", type=int, default=40000)
    ap.add_argument("--json", default=None)
    args = ap.parse_args()

    d = Daemon()
    t0 = time.time()

    win = d.window(5000)
    entries = sorted(win["entries"], key=lambda e: e["chainPosition"])
    walked = list(entries)
    cursor = entries[0]["prevHash"]
    n = 0
    while cursor and n < args.hops:
        e = d.by_hash(cursor)
        if not e:
            break
        walked.append(e)
        cursor = e.get("prevHash")
        n += 1
        if n % 2000 == 0:
            pe = sum(1 for w in walked if w["eventType"] == "policy_edit")
            print(f"  ... {n} hops, {pe} policy_edit so far, {time.time()-t0:.0f}s", flush=True)

    walked.sort(key=lambda e: e["chainPosition"])
    by_pos = {e["chainPosition"]: e for e in walked}
    lo, hi = min(by_pos), max(by_pos)
    print(f"\n== walked {len(walked)} entries, positions {lo}..{hi}, {time.time()-t0:.0f}s ==")
    print("   (a BOUNDED walk: everything below is true of this window, and the window's")
    print("    oldest position is printed so a reader can see what it could not see.)\n")

    pe = [e for e in walked if e["eventType"] == "policy_edit"]
    print(f"policy_edit rows in window: {len(pe)}")
    if not pe:
        print("NONE in window -- this walk cannot speak to the disputed column.")
        return

    newest = max(e["timestamp"] for e in pe)
    print(f"max(timestamp) over them: {newest}")
    print(f"my published column:      {DISPUTED_NEWEST}")
    verdict = "REFUTED" if newest > DISPUTED_NEWEST else "consistent"
    print(f"=> my column is {verdict} by this walk\n")

    print("every policy_edit row in the window, newest first, with its position-1 neighbor:")
    prov_keys = ("actor", "principal", "authority", "signers", "session_ref", "office")
    rows = []
    for e in sorted(pe, key=lambda e: -e["chainPosition"]):
        pos = e["chainPosition"]
        nb = by_pos.get(pos - 1)
        nb_type = nb["eventType"] if nb else "(outside window)"
        nb_act = (nb.get("eventData") or {}).get("act") if nb else None
        nb_verdict = (nb.get("eventData") or {}).get("verdict") if nb else None
        nb_prov = sorted(k for k in prov_keys if nb and k in (nb.get("eventData") or {}))
        data = json.dumps(e.get("eventData") or {}, separators=(",", ":"), sort_keys=True)
        print(f"  pos={pos} {e['timestamp']}  {data}")
        print(f"      prev row: {nb_type}  act={nb_act!r} verdict={nb_verdict!r} provenance_keys={nb_prov}")
        rows.append({
            "position": pos, "timestamp": e["timestamp"], "event_data": e.get("eventData"),
            "neighbor_type": nb_type, "neighbor_act": nb_act,
            "neighbor_verdict": nb_verdict, "neighbor_provenance_keys": nb_prov,
            "neighbor_event_data": (nb.get("eventData") if nb else None),
        })

    # The check adjacency alone does not make: does the neighbor's act name the same
    # change the policy_edit row records? A neighbor is only evidence if it matches.
    ROUTE_FOR_CHANGE = {
        "preset": "/api/policy/preset",
        "override": "/api/policy/override",
        "upsert_rule": "/api/policy/rule",
        "delete_rule": "/api/policy/rule",
    }

    # THE FREE PARAMETER. "Recoverable by adjacency" is not one number -- it is a curve in
    # the lookback width, and the width is chosen by the analyst, not by the chain. Nothing
    # in either row commits to the pair, so widening the window strictly increases the
    # recovery rate and strictly decreases the strength of each recovery. Reporting one
    # width reports a point on a curve as if it were a property of the record.
    print("\nrecovery vs lookback width (a claimed rate is only readable with its width):")
    print("  width  matched  mismatched  none")
    curve = {}
    for width in (1, 2, 3, 5, 10):
        matched = mismatched = none = 0
        for r in rows:
            change = (r["event_data"] or {}).get("change")
            want = ROUTE_FOR_CHANGE.get(change)
            hit = None
            for back in range(1, width + 1):
                nb = by_pos.get(r["position"] - back)
                if nb and nb["eventType"] == "operator_gate":
                    hit = nb
                    break
            if hit is None:
                none += 1
            elif want and want in ((hit.get("eventData") or {}).get("act") or ""):
                matched += 1
            else:
                mismatched += 1
        curve[width] = {"matched": matched, "mismatched": mismatched, "none": none}
        print(f"  {width:>5}  {matched:>7}  {mismatched:>10}  {none:>4}")
    print("a mismatch is the failure mode of a positional join: right shape, wrong act.")

    # What the surviving neighbor actually names. `signers` is the OLD provenance shape;
    # actor/principal/authority is what attach_operator_provenance writes today. If the
    # neighbor names an author only under `signers`, the forensic route recovers whatever
    # that list holds -- print it rather than assert it.
    print("\nwhat the position-1 operator_gate neighbours actually name:")
    seen = {}
    for r in rows:
        nb = r.get("neighbor_event_data") or {}
        if r["neighbor_type"] != "operator_gate":
            continue
        for k in ("actor", "principal", "authority", "signers", "office", "session_ref"):
            if k in nb:
                seen.setdefault(k, set()).add(json.dumps(nb[k], sort_keys=True)[:120])
    for k, vals in sorted(seen.items()):
        print(f"  {k:<12} {sorted(vals)}")
    if not seen:
        print("  (no provenance key on any neighbour in this window)")

    if args.json:
        with open(args.json, "w") as f:
            json.dump({"walked": len(walked), "window_lo": lo, "window_hi": hi,
                       "newest": newest, "rows": rows}, f, indent=2, sort_keys=True)
        print(f"\nwrote {args.json}")


if __name__ == "__main__":
    main()
