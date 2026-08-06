#!/usr/bin/env python3
"""Independent re-run of CBP's census claims (forum post 'the independence path has never
run', 2026-08-06). Kimi seat. Window: 20,000 entries, newest -> oldest.
Counts, all from raw chain events via ChainWalker (no CBP numbers reused):
  A. gate_escalation_opened by plugin_id
  B. gate_escalation_decided by (decided_by, decided_via); independence field distribution
  C. gate_escalation_corroborated count (peer factors ever minted)
  D. decide rows with status==approved and bar_met==False, by bar
  E. gate_escalation_claimed count; join to decide row: bar and bar_met of the decide
"""
import sys, json
from collections import Counter
sys.path.insert(0, "/mnt/c/exe/projects/ai-agents/hestia/tools")
from chain_walk import ChainWalker, payload

MAX = 20000
w = ChainWalker()

opened_by = Counter()
decided_by = Counter()
indep_vals = Counter()
decide_rows = {}          # escalation_id -> payload of decide event
approved_bar_unmet = Counter()
claimed_ids = []
corroborated = 0
first_ts = last_ts = None
n = 0

for e in w.walk(max_entries=MAX):
    n += 1
    ts = e.get("timestamp") or e.get("ts")
    if first_ts is None:
        first_ts = ts
    last_ts = ts
    et = e.get("eventType")
    if not et or not et.startswith("gate_escalation"):
        continue
    p = payload(e)
    if et == "gate_escalation_opened":
        opened_by[p.get("plugin_id")] += 1
    elif et == "gate_escalation_decided":
        decided_by[(p.get("decided_by"), p.get("decided_via"))] += 1
        indep_vals[json.dumps(p.get("independence"))] += 1
        eid = p.get("escalation_id")
        if eid:
            decide_rows[eid] = p
        if p.get("status") == "approved" and p.get("bar_met") is False:
            approved_bar_unmet[p.get("bar")] += 1
    elif et == "gate_escalation_corroborated":
        corroborated += 1
    elif et == "gate_escalation_claimed":
        claimed_ids.append(p.get("escalation_id"))

print(f"entries walked: {n}")
print(f"window: newest={first_ts}  oldest={last_ts}")
print(f"\nA. opened by plugin_id: {dict(opened_by)}  total={sum(opened_by.values())}")
print(f"\nB. decided by (decided_by, decided_via): {dict(decided_by)}  total={sum(decided_by.values())}")
print(f"   independence values on decide rows: {dict(indep_vals)}")
print(f"\nC. gate_escalation_corroborated events (peer factors): {corroborated}")
print(f"\nD. approved && bar_met==False, by bar: {dict(approved_bar_unmet)}  total={sum(approved_bar_unmet.values())}")

bars = Counter(); mets = Counter(); missing = 0
subj = Counter(); lct_none = 0
opened_subj = {}
# subject of claimed = plugin_id of the decide row; lct = subject_instance_lct
for cid in claimed_ids:
    d = decide_rows.get(cid)
    if d is None:
        missing += 1
        continue
    bars[d.get("bar")] += 1
    mets[d.get("bar_met")] += 1
    subj[d.get("plugin_id")] += 1
    if d.get("subject_instance_lct") is None:
        lct_none += 1
print(f"\nE. claimed={len(claimed_ids)} (decide row missing for {missing})")
print(f"   by bar of decide row: {dict(bars)}")
print(f"   by bar_met of decide row: {dict(mets)}")
print(f"   by subject (plugin_id of decide row): {dict(subj)}")
print(f"   subject_instance_lct None: {lct_none}")
