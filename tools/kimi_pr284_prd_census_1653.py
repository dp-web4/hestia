#!/usr/bin/env python3
"""Full-genesis verification for hestia PR #284 @ 40cdf261 (decision-0013 PRD update).

Claims under test (PRD_GOVERNANCE.md §2.16, §8.2, Sprint 2.5 contract 5):
  A. answers_deny empty for 425/425 historical escalation opens
  B. 44 of 90 approved historical rows claimed; delivered to literal "unattributed"
  C. 215 of 215 escalation decisions decided_by operator (scoped to a sample)
"""
import json
import sys
from collections import Counter

sys.path.insert(0, "/mnt/c/exe/projects/ai-agents/hestia/tools")
from chain_walk import ChainWalker, payload

w = ChainWalker()

opens_total = 0
opens_with_answers = 0
decided_status = Counter()
decided_by = Counter()
decided_via = Counter()
claimed_total = 0
claimed_plugin = Counter()
# join: escalation_id -> decided approved? ; claimed ids
approved_ids = {}     # esc_id -> plugin_id
claimed_ids = {}      # esc_id -> plugin_id (on the claimed event)

walked = 0
for e in w.walk(max_entries=200_000):
    walked += 1
    et = e.get("eventType")
    p = payload(e)
    if et == "gate_escalation_opened":
        opens_total += 1
        if p.get("answers_deny"):
            opens_with_answers += 1
    elif et == "gate_escalation_decided":
        st = p.get("status") or "<absent>"
        decided_status[st] += 1
        decided_by[p.get("decided_by") or "<absent>"] += 1
        decided_via[p.get("decided_via") or "<absent>"] += 1
        if st == "approved":
            approved_ids[p.get("escalation_id")] = p.get("plugin_id")
    elif et == "gate_escalation_claimed":
        claimed_total += 1
        claimed_plugin[p.get("plugin_id") or "<absent>"] += 1
        claimed_ids[p.get("escalation_id")] = p.get("plugin_id")

approved_and_claimed = Counter()
for eid in claimed_ids:
    if eid in approved_ids:
        approved_and_claimed[approved_ids[eid]] += 1

out = {
    "walked_entries": walked,
    "A_escalation_opens_total": opens_total,
    "A_opens_with_answers_deny": opens_with_answers,
    "A_prd_claim": "425/425 empty",
    "C_decided_status": dict(decided_status),
    "C_decided_by": dict(decided_by),
    "C_decided_via": dict(decided_via),
    "B_approved_total": len(approved_ids),
    "B_claimed_total": claimed_total,
    "B_claimed_by_escalation_plugin": dict(claimed_plugin),
    "B_approved_and_claimed_by_plugin": dict(approved_and_claimed),
    "B_prd_claim": "44 of 90 approved rows claimed, delivered to literal 'unattributed'",
}
print(json.dumps(out, indent=2))
with open("/mnt/c/exe/projects/ai-agents/hestia/.kimi-target/verify_0013_counts_full.json", "w") as f:
    json.dump(out, f, indent=2)
