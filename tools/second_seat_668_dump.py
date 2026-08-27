#!/usr/bin/env python3
"""Dump escalation lifecycle events 2026-08-17..2026-08-27 for the #668 refutation check."""
import json, sys
sys.path.insert(0, "/mnt/c/exe/projects/ai-agents/hestia/tools")
from chain_walk import ChainWalker, payload

START = "2026-08-08T00:00:00"
TYPES = ("gate_escalation_opened", "gate_escalation_decided",
         "gate_escalation_claimed", "gate_escalation_expired",
         "gate_escalation_corroborated")

w = ChainWalker()
rows = []
hops = 0
oldest = newest = None
for e in w.walk(max_entries=200000):
    t = e.get("timestamp") or ""
    if t and t < START:
        break
    hops += 1
    if newest is None:
        newest = t
    oldest = t
    if e.get("eventType") in TYPES:
        rows.append({"type": e["eventType"], "ts": t,
                     "pos": e.get("chainPosition"), "payload": payload(e)})
json.dump({"rows": rows, "hops": hops, "oldest": oldest, "newest": newest},
          open("/tmp/668_esc_corpus_wide.json", "w"))
print(json.dumps({"hops": hops, "rows": len(rows), "oldest": oldest, "newest": newest}))
