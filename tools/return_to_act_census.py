#!/usr/bin/env python3
"""Census the RETURN-TO-ACT class: an approved grant that went unclaimed, whose asker
later re-opened an escalation for the SAME act_digest.

#536 measured attention BEFORE the ruling (acts between ask and grant) and concluded the
clock is not the binding constraint. This asks the complement: after the ruling, did the
asker come BACK to the same act -- and if so, how long after? A return inside the
decided-anchored horizon that still opened a NEW record is a claim-path failure; a return
after it is a member whose attention was demonstrably on the act, refused by the clock alone.
"""
import sys, json, collections
sys.path.insert(0, '/home/dp/ai-workspace/hestia/tools')
from chain_walk import ChainWalker, payload

MAX = int(sys.argv[1]) if len(sys.argv) > 1 else 40000

opened, decided, claimed = {}, {}, {}
order = []
n = 0
w = ChainWalker()
first_ts = last_ts = None
for e in w.walk(max_entries=MAX):
    n += 1
    ts = e.get("timestamp")
    if first_ts is None: first_ts = ts
    last_ts = ts
    t = e.get("eventType", "")
    if not t.startswith("gate_escalation_"):
        continue
    p = payload(e)
    eid = p.get("escalation_id")
    if not eid:
        continue
    if t == "gate_escalation_opened":
        opened[eid] = dict(plugin_id=p.get("plugin_id"), act_digest=p.get("act_digest"),
                           opened_at=p.get("opened_at"), ts=ts, marker=p.get("marker"),
                           tool=p.get("tool_name"), reason=p.get("stated_reason"),
                           answers_deny=p.get("answers_deny"), opened_via=p.get("opened_via"))
        order.append(eid)
    elif t == "gate_escalation_decided":
        decided[eid] = dict(status=p.get("status"), bar_met=p.get("bar_met"),
                            decided_at=p.get("decided_at"), ts=ts, by=p.get("decided_by"))
    elif t == "gate_escalation_claimed":
        claimed[eid] = ts

print(f"walked {n} entries  {last_ts} .. {first_ts}")
print(f"opened={len(opened)} decided={len(decided)} claimed={len(claimed)}")

# field-presence guard (#977: a field can be named and never valued)
have_digest = sum(1 for v in opened.values() if v["act_digest"])
have_decided_at = sum(1 for v in decided.values() if v["decided_at"] is not None)
print(f"opened rows carrying act_digest: {have_digest}/{len(opened)}")
print(f"decided rows carrying decided_at: {have_decided_at}/{len(decided)}")

import datetime
def epoch(iso):
    return datetime.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()

# approved + bar_met + never claimed, with a digest
pool = []
for eid, o in opened.items():
    d = decided.get(eid)
    if not d or d["status"] != "approved" or not d["bar_met"]:
        continue
    if eid in claimed:
        continue
    if not o["act_digest"]:
        continue
    dt = d["decided_at"] if d["decided_at"] is not None else epoch(d["ts"])
    pool.append((eid, o, d, dt))
print(f"\nAPPROVED + bar_met + NEVER CLAIMED, digest present: {len(pool)}")

# index later opens by (plugin_id, act_digest)
by_key = collections.defaultdict(list)
for eid, o in opened.items():
    if o["act_digest"]:
        by_key[(o["plugin_id"], o["act_digest"])].append((epoch(o["ts"]), eid, o))
for k in by_key: by_key[k].sort()

buckets = collections.Counter()
rows = []
for eid, o, d, dt in pool:
    later = [(t, i, oo) for (t, i, oo) in by_key[(o["plugin_id"], o["act_digest"])]
             if i != eid and t > dt]
    if not later:
        buckets["no return"] += 1
        continue
    t, i, oo = later[0]
    gap = t - dt
    b = "return INSIDE horizon (<=600s)" if gap <= 600 else "return AFTER horizon (>600s)"
    buckets[b] += 1
    rows.append((gap, eid, i, o["plugin_id"], o["tool"], o["marker"]))

print("\n=== RETURN-TO-ACT ===")
for k, v in buckets.most_common():
    print(f"  {v:5d}  {k}")
rows.sort()
print(f"\nreturn pairs (n={len(rows)}), soonest first:")
for gap, a, b, pid, tool, marker in rows[:40]:
    print(f"  +{gap:8.0f}s  {a[:8]} -> {b[:8]}  {pid:14s} {tool} {str(marker)[:40]}")
