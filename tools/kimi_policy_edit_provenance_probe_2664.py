#!/usr/bin/env python3
"""Follow-up to kimi_chain_authorship_verify_2664: can the 23 authorless policy_edit
rows be forensically attributed via adjacent operator_gate provenance rows?

Basis (code, this repo):
  - core/src/server/http.rs: every /api/policy/* route sits behind the operator_gate
    middleware, which self-witnesses any non-LowReversible act as an `operator_gate`
    chain row, with operator provenance attached (attach_operator_provenance:
    actor/principal/authority) when a session exists.
  - The policy_edit append happens in the handler, AFTER the middleware row. So a
    policy_edit written through the gated HTTP surface should be immediately preceded
    by an operator_gate row naming the authority.

If that adjacency holds on the historical rows, the "no author, never was" claim
(reply-2662) weakens: the author may be recoverable one row back. If the middleware
postdates the June rows, the adjacency test will show it (no operator_gate neighbor,
or neighbor without provenance keys).

Run after kimi_chain_authorship_verify_2664.py (same transport, full walk).
"""

import time
from collections import Counter

from claude_chain_reexecution_audit import Daemon


def walk_all(d):
    win = d.window(5000)
    entries = win["entries"]
    entries.sort(key=lambda e: e["chainPosition"])
    walked = list(entries)
    cursor = entries[0]["prevHash"]
    while True:
        e = d.by_hash(cursor)
        if not e:
            return walked
        walked.append(e)
        cursor = e.get("prevHash")


def main():
    d = Daemon()
    t0 = time.time()
    walked = walk_all(d)
    walked.sort(key=lambda e: e["chainPosition"])
    by_pos = {e["chainPosition"]: e for e in walked}
    print(f"walked {len(walked)} in {time.time()-t0:.0f}s")

    pe = [e for e in walked if e["eventType"] == "policy_edit"]
    gr = [e for e in walked if e["eventType"] == "gate_ratified"]
    print(f"policy_edit rows: {len(pe)}, gate_ratified rows: {len(gr)}")

    og_positions = [e["chainPosition"] for e in walked if e["eventType"] == "operator_gate"]
    print(f"operator_gate rows: {len(og_positions)}, "
          f"span {min(og_positions) if og_positions else '-'}..{max(og_positions) if og_positions else '-'}")

    prov_keys = ("actor", "principal", "authority", "signers", "session_ref")
    print("\npolicy_edit adjacency (looking back up to 3 positions for operator_gate):")
    counts = Counter()
    for e in pe:
        p = e["chainPosition"]
        hit = None
        for back in (1, 2, 3):
            nb = by_pos.get(p - back)
            if nb and nb["eventType"] == "operator_gate":
                hit = nb
                break
        if not hit:
            counts["no-operator_gate-neighbor"] += 1
            print(f"  pos {p} @ {e['timestamp']}: no operator_gate within 3 back")
            continue
        ed = hit.get("eventData") or {}
        prov = {k: ed.get(k) for k in prov_keys if ed.get(k)}
        verdict = ed.get("verdict") or ed.get("outcome")
        act = ed.get("act")
        key = "neighbor-with-provenance" if prov else "neighbor-no-provenance"
        counts[key] += 1
        print(f"  pos {p} @ {e['timestamp']}: gate at {hit['chainPosition']} "
              f"act={act} verdict={verdict} prov={list(prov)}")
    print(f"\nsummary: {dict(counts)}")

    for e in gr:
        p = e["chainPosition"]
        print(f"\ngate_ratified pos {p} @ {e['timestamp']} keys={sorted((e['eventData'] or {}).keys())}")
        for back in (1, 2, 3):
            nb = by_pos.get(p - back)
            if nb:
                print(f"  -{back}: {nb['eventType']} @ {nb['timestamp']}")


if __name__ == "__main__":
    main()
