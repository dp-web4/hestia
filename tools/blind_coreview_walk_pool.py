#!/usr/bin/env python3
"""Pass 1 of the blind co-review draw: walk the whole chain, keep ONLY pre-decision data.

Kept: every gate_escalation_opened payload (the act as asked), the filer + timestamp of
every gate_escalation_corroborated, and the escalation ids that reached a terminal event
with that event's TIMESTAMP only. The terminal event's type and payload are never stored:
decided vs withdrawn vs expired is part of the outcome, and the drawer is also a reviewer.
gate_escalation_claimed rows (they carry decided_by) are skipped entirely.
"""
import json, sys, time
sys.path.insert(0, sys.path[0])
from chain_walk import ChainWalker, payload
TERMINAL = {"gate_escalation_decided", "gate_escalation_expired", "gate_escalation_withdrawn"}
out = {"opened": {}, "factors": [], "terminal_at": {}, "head": None, "walked": 0}
t0 = time.time()
for e in ChainWalker(timeout=60).walk(max_entries=10**8):
    out["walked"] += 1
    if out["head"] is None:
        out["head"] = {"hash": e["hash"], "timestamp": e["timestamp"]}
    et = e["eventType"]
    if not et.startswith("gate_escalation"):
        continue
    d = payload(e); eid = d.get("escalation_id")
    if not eid:
        continue
    if et == "gate_escalation_opened":
        out["opened"].setdefault(eid, dict(d, _ts=e["timestamp"]))
    elif et == "gate_escalation_corroborated":
        out["factors"].append({"eid": eid, "by": d.get("corroborated_by"), "ts": e["timestamp"]})
    elif et in TERMINAL:
        out["terminal_at"][eid] = min(e["timestamp"], out["terminal_at"].get(eid, e["timestamp"]))
out["tail"] = {"timestamp": e["timestamp"]}
json.dump(out, open(sys.argv[1], "w"))
print(f"walked {out['walked']} in {time.time()-t0:.0f}s; opened={len(out['opened'])} "
      f"factors={len(out['factors'])} terminal={len(out['terminal_at'])}")
