#!/usr/bin/env python3
"""Why do approved escalations die unspent?

kimi's 876424a3 review (obs. 4) says half of an approval storm's grants die unclaimed and
attributes it to DISCOVERY: "the claim path works once discovered; the gap is discovery at
the moment of refusal."

There is a rival explanation this wake produced first-hand evidence for. A claim binds the
ACT TEXT, not the marker: on 2026-09-04 an approved grant (5b60cefa) was claimed only by
re-issuing the byte-identical command, while a `cp` at the SAME target minted a third id
(cdc5d131) instead of claiming. So a member that does the natural thing after a refusal --
FIX THE COMMAND -- can never claim the grant it was just given. That is not a discovery gap;
it is structural unclaimability, and it looks identical in the "unclaimed" column.

The two are separable on the chain. For each approved-but-never-claimed id, ask whether the
same plugin opened ANOTHER escalation at the SAME marker soon after:

  RE-FILED  -> the member was still working the problem; the grant could not be spent on the
               act it had become. Rival explanation.
  ABANDONED -> nothing followed. Consistent with the discovery gap.
"""
import sys, os, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chain_walk import ChainWalker, payload
from datetime import datetime


def _epoch(ts):
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts).timestamp()
    except ValueError:
        return None

REFILE_WINDOW = 1800  # 30 min: within one working session, generous side
MAX_ENTRIES = int(os.getenv("MAX_ENTRIES") or "60000")

w = ChainWalker()
opened, decided, claimed, withdrawn = {}, {}, set(), set()
claim_lag = []
n = 0
for e in w.walk(max_entries=MAX_ENTRIES):
    n += 1
    t = e.get("eventType") or ""
    if not t.startswith("gate_escalation_"):
        continue
    p = payload(e)
    eid = p.get("escalation_id") or p.get("id")
    if not eid:
        continue
    # #700/#658: neither opened nor decided carries its own timestamp in the payload.
    # The CHAIN ENTRY does, and it is the witnessed one -- use it, and say so.
    ts = _epoch(e.get("timestamp"))
    if t == "gate_escalation_opened":
        opened[eid] = {"at": ts, "plugin": p.get("plugin_id"), "marker": p.get("marker")}
    elif t == "gate_escalation_decided":
        decided[eid] = {"at": ts, "granted": p.get("status") == "approved",
                        "by": p.get("decided_by"), "bar": p.get("bar")}
    elif t == "gate_escalation_withdrawn":
        withdrawn.add(eid)
    elif t == "gate_escalation_claimed":
        claimed.add(eid)
        claim_lag.append((eid, p.get("secs_from_decision_to_use"), p.get("secs_from_open_to_use")))

print(f"chain entries walked: {n}")
print(f"escalations opened:   {len(opened)}")
print(f"  decided:            {len(decided)}")
approved = {k: v for k, v in decided.items() if v.get("granted")}
print(f"  withdrawn:          {len(withdrawn)}")
print(f"  approved:           {len(approved)}")
unclaimed = [k for k in approved if k not in claimed]
print(f"  approved+claimed:   {len(approved) - len(unclaimed)}")
print(f"  approved+UNCLAIMED: {len(unclaimed)}  ({100.0*len(unclaimed)/max(1,len(approved)):.1f}%)")

by_key = collections.defaultdict(list)
for eid, o in opened.items():
    if o["at"] is None:
        continue
    by_key[(o["plugin"], o["marker"])].append((o["at"], eid))
for v in by_key.values():
    v.sort()

refiled, abandoned, undated = [], [], []
for eid in unclaimed:
    o = opened.get(eid)
    d = decided.get(eid)
    t0 = (d or {}).get("at") or (o or {}).get("at")
    if not o or t0 is None:
        undated.append(eid)
        continue
    later = [x for x in by_key[(o["plugin"], o["marker"])]
             if x[1] != eid and t0 <= x[0] <= t0 + REFILE_WINDOW]
    (refiled if later else abandoned).append((eid, o, len(later)))

print()
print(f"unclaimed grants, split (same plugin + same marker reopened within {REFILE_WINDOW}s):")
print(f"  RE-FILED  {len(refiled):4d}   member kept working; the grant could not follow the act")
print(f"  ABANDONED {len(abandoned):4d}   nothing followed")
print(f"  undated   {len(undated):4d}   missing opened_at/decided_at (see #700/#658)")
tot = len(refiled) + len(abandoned)
if tot:
    print(f"  -> re-filed share of the datable unclaimed: {100.0*len(refiled)/tot:.1f}%")

print()
agg = collections.defaultdict(lambda: [0, 0, 0])
for eid in approved:
    o = opened.get(eid) or {}
    agg[o.get("plugin")][0] += 1
    if eid not in claimed:
        agg[o.get("plugin")][1] += 1
for eid, o, _ in refiled:
    agg[o.get("plugin")][2] += 1
print(f"  {'plugin':<24} {'approved':>8} {'unclaimed':>9} {'refiled':>8}")
for k, v in sorted(agg.items(), key=lambda kv: -kv[1][0]):
    print(f"  {str(k):<24} {v[0]:>8} {v[1]:>9} {v[2]:>8}")

print()
if claim_lag:
    lags = sorted(x[1] for x in claim_lag if isinstance(x[1], (int, float)))
    if lags:
        print()
        print(f"claim lag (decision -> use), n={len(lags)}: "
              f"min {lags[0]}s  median {lags[len(lags)//2]}s  max {lags[-1]}s")

print()
print("sample RE-FILED (grant given; member reopened at same marker instead of claiming):")
for eid, o, cnt in refiled[:12]:
    print(f"  {eid}  {str(o['plugin']):<14} marker={str(o['marker'])[:34]:<34} reopens={cnt}")
