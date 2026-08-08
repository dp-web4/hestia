#!/usr/bin/env python3
"""Verify decision-0013 (PR #283) §4's observed-backwards claim:
"approvals granted to escalations filed under the literal `unattributed` proved
UNCLAIMABLE" (dp, measured 2026-08-07).

Independent re-measure (kimi-code, answering notice 1640): for every
gate_escalation_opened under plugin_id 'unattributed' that was later decided
Approved, was there a gate_escalation_claimed spending it? And the control: the
same unclaim-rate for approved escalations under attributed plugin_ids.
"""
import sys
from collections import defaultdict

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from chain_walk import ChainWalker, payload  # noqa: E402

MAX = int(sys.argv[1]) if len(sys.argv) > 1 else 200_000

opened = {}      # esc_id -> plugin_id
approved = {}    # esc_id -> decided status Approved (plugin from opened)
claimed = set()  # esc_id with a gate_escalation_claimed

w = ChainWalker()
for e in w.walk(max_entries=MAX):
    et = e.get("eventType")
    p = payload(e)
    if et == "gate_escalation_opened":
        opened[p.get("escalation_id")] = p.get("plugin_id")
    elif et == "gate_escalation_decided":
        st = (p.get("status") or p.get("decision") or "").lower()
        if "approv" in st:
            approved[p.get("escalation_id")] = True
    elif et == "gate_escalation_claimed":
        claimed.add(p.get("escalation_id"))

stats = defaultdict(lambda: [0, 0])  # plugin -> [approved, unclaimed]
for esc_id in approved:
    plug = opened.get(esc_id, "<no-open-row>")
    stats[plug][0] += 1
    if esc_id not in claimed:
        stats[plug][1] += 1

print(f"approved escalations: {sum(v[0] for v in stats.values())}")
for plug, (ap, uncl) in sorted(stats.items(), key=lambda kv: -kv[1][0]):
    rate = (uncl / ap * 100) if ap else 0
    print(f"  {plug:<50} approved={ap:<4} never-claimed={uncl:<4} ({rate:.0f}%)")
