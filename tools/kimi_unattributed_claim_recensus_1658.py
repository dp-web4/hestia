#!/usr/bin/env python3
"""Independent re-derivation of decision-0013 correction #1 (notice 1658, re 1649).

CLAIM UNDER REVIEW (claude-code, commit 89939ef, re-deriving kimi's 1649 numbers):
  - 124 gate_escalation_opened rows carry plugin_id "unattributed"
  - 90 of those were approved
  - 44 were CLAIMED and spent (join is (plugin_id, marker), gate_escalation.rs:901)
  - last claim: hash prefix abbe8f6a90fbc4be at 16:17:47Z
  - after 16:17Z, zero of the next 8 approved unattributed escalations were ever claimed

Method note: counts CLAIMED events by plugin_id and cross-checks per-marker, since the
claim join cannot tell which open a claim binds to (that is the defect under discussion).

Reads only. Mints nothing.
"""
from __future__ import annotations

import sys
from collections import Counter

from chain_walk import ChainWalker, payload

MAX = int(sys.argv[1]) if len(sys.argv) > 1 else 500_000

opened = []   # (id, plugin_id, marker, ts, pos)
decided = []  # (id, status, ts, pos)
claimed = []  # (plugin_id, marker, ts, hash, pos)

for e in ChainWalker().walk(max_entries=MAX):
    et = e.get("eventType")
    p = payload(e)
    if et == "gate_escalation_opened":
        opened.append((p.get("escalation_id") or p.get("id"), p.get("plugin_id"),
                       p.get("marker"), e.get("timestamp"), e.get("chainPosition")))
    elif et == "gate_escalation_decided":
        decided.append((p.get("escalation_id") or p.get("id"), p.get("status"),
                        e.get("timestamp"), e.get("chainPosition")))
    elif et == "gate_escalation_claimed":
        claimed.append((p.get("plugin_id"), p.get("marker"), e.get("timestamp"),
                        e.get("hash"), e.get("chainPosition")))

unattr_open = [o for o in opened if o[1] in (None, "unattributed")]
unattr_ids = {o[0] for o in unattr_open}
approved = [d for d in decided if d[0] in unattr_ids and d[1] == "approved"]
unattr_claims = [c for c in claimed if c[0] in (None, "unattributed")]

print(f"opened total / unattributed      : {len(opened)} / {len(unattr_open)}")
print(f"approved decisions on unattr ids : {len(approved)}")
print(f"claimed rows by unattributed     : {len(unattr_claims)}")
print(f"decided-status census on unattr  : {dict(Counter(d[1] for d in decided if d[0] in unattr_ids))}")

last = max(unattr_claims, key=lambda c: c[4] or 0) if unattr_claims else None
if last:
    print(f"last unattributed claim          : {last[3]} at {last[2]} (pos {last[4]})")
    cut = last[4] or 0
    later_approved = [d for d in approved if (d[3] or 0) > cut]
    # claimable markers the later approvals could have joined on
    later_markers = {o[2] for o in unattr_open if o[0] in {d[0] for d in later_approved}}
    later_claims = [c for c in unattr_claims if (c[4] or 0) > cut and c[1] in later_markers]
    print(f"approved unattributed AFTER last claim pos: {len(later_approved)}")
    print(f"unattributed claims AFTER last claim pos  : {len([c for c in unattr_claims if (c[4] or 0) > cut])}"
          f" (on later-approved markers: {len(later_claims)})")

print("\nclaim marker census (unattributed):", dict(Counter(c[1] for c in unattr_claims)))
