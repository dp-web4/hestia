#!/usr/bin/env python3
"""Extend claude-code's tools/return_to_act_census.py (branch claude/return-to-act-census):

  1. Re-run the return-to-act census over the CURRENT chain head.
  2. For each return pair, print the second petition's outcome (status / decided_by / claimed).
  3. Dump every petition in the dc868c1a digest family (the postscript's "three petitions"
     lineage) to settle whether ffce7cbb.. and ac58c702.. are distinct rows.
  4. Dump the digest family of escalation a75b93ca5fdffddd (notice 13474) and classify it.
"""
import sys, os, json, collections, datetime
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chain_walk import ChainWalker, payload

MAX = int(sys.argv[1]) if len(sys.argv) > 1 else 200000

def epoch(iso):
    return datetime.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()

opened, decided, claimed = {}, {}, {}
event_types = collections.Counter()
n = 0
first_ts = last_ts = None
for e in ChainWalker().walk(max_entries=MAX):
    n += 1
    ts = e.get("timestamp")
    if first_ts is None: first_ts = ts
    last_ts = ts
    t = e.get("eventType", "")
    if not t.startswith("gate_escalation_"):
        continue
    event_types[t] += 1
    p = payload(e)
    eid = p.get("escalation_id")
    if not eid:
        continue
    if t == "gate_escalation_opened":
        opened[eid] = dict(plugin_id=p.get("plugin_id"), act_digest=p.get("act_digest"),
                           ts=ts, marker=p.get("marker"), tool=p.get("tool_name"))
    elif t == "gate_escalation_decided":
        decided[eid] = dict(status=p.get("status"), bar_met=p.get("bar_met"),
                            decided_at=p.get("decided_at"), ts=ts, by=p.get("decided_by"))
    elif t == "gate_escalation_claimed":
        claimed[eid] = ts

print(f"walked {n} entries  {last_ts} .. {first_ts}")
print(f"event types: {dict(event_types)}")
print(f"opened={len(opened)} decided={len(decided)} claimed={len(claimed)}")

def outcome(eid):
    d = decided.get(eid)
    return dict(status=d["status"] if d else "undecided",
                by=(d["by"] if d else "-"),
                claimed=eid in claimed)

# --- census, same construction as return_to_act_census.py -------------------
pool = []
for eid, o in opened.items():
    d = decided.get(eid)
    if not d or d["status"] != "approved" or not d["bar_met"]:
        continue
    if eid in claimed or not o["act_digest"]:
        continue
    dt = d["decided_at"] if d["decided_at"] is not None else epoch(d["ts"])
    pool.append((eid, o, d, dt))
print(f"\nAPPROVED + bar_met + NEVER CLAIMED, digest present: {len(pool)}")

by_key = collections.defaultdict(list)
for eid, o in opened.items():
    if o["act_digest"]:
        by_key[(o["plugin_id"], o["act_digest"])].append((epoch(o["ts"]), eid))
for k in by_key: by_key[k].sort()

rows = []
for eid, o, d, dt in pool:
    later = [(t, i) for (t, i) in by_key[(o["plugin_id"], o["act_digest"])] if i != eid and t > dt]
    if not later:
        continue
    t, i = later[0]
    rows.append((t - dt, eid, i, o["plugin_id"]))

rows.sort()
print(f"\nreturn pairs (n={len(rows)}):")
oc = collections.Counter()
for gap, a, b, pid in rows:
    o2 = outcome(b)
    oc[(o2["status"], o2["claimed"])] += 1
    print(f"  +{gap:8.0f}s  {a[:8]} -> {b}  {pid:14s} status={o2['status']} by={o2['by']} claimed={o2['claimed']}")
print(f"second-petition outcomes: {dict(oc)}")
cl = [epoch(claimed[b]) - epoch(decided[b]['ts']) for _, _, b, _ in rows
      if b in claimed and b in decided and decided[b]['status'] == 'approved']
if cl:
    cl.sort()
    print(f"claimed second grants: n={len(cl)} median={cl[len(cl)//2]:.0f}s min={cl[0]:.0f}s max={cl[-1]:.0f}s")

# --- dc868c1a family ---------------------------------------------------------
print("\n=== digest family dc868c1a* ===")
for eid, o in sorted(opened.items(), key=lambda kv: kv[1]["ts"]):
    if o["act_digest"] and o["act_digest"].startswith("dc868c1a"):
        oo = outcome(eid)
        print(f"  {o['ts']}  {eid}  {o['plugin_id']:14s} status={oo['status']} by={oo['by']} claimed={oo['claimed']} marker={o['marker']} digest={o['act_digest'][:16]}")

# --- a75b93ca5fdffddd family -------------------------------------------------
print("\n=== a75b93ca5fdffddd and its digest family ===")
tgt = next((eid for eid in opened if eid.startswith("a75b93ca")), None)
if not tgt:
    print("  NOT FOUND in walked window")
else:
    o = opened[tgt]
    print(f"  target: {tgt} plugin={o['plugin_id']} digest={o['act_digest']} marker={o['marker']} opened={o['ts']} outcome={outcome(tgt)}")
    fam = [(eid2, o2) for eid2, o2 in opened.items()
           if o2["act_digest"] and o2["act_digest"] == o["act_digest"] and o2["plugin_id"] == o["plugin_id"]]
    for eid2, o2 in sorted(fam, key=lambda kv: kv[1]["ts"]):
        oo = outcome(eid2)
        print(f"    {o2['ts']}  {eid2}  status={oo['status']} by={oo['by']} claimed={oo['claimed']} marker={o2['marker']}")
