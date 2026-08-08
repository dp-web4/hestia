#!/usr/bin/env python3
"""Which identity field do real `member_notice` rows carry?

Decides whether the fixture at handler.rs:9818 (`"plugin_id": "codex"`) tests a shape
production can produce. Answer measured 2026-08-08: 0 of 1644 rows carry `plugin_id`;
1646/1646 carry `from_plugin_id`. The only append_chain("member_notice") call site in
the crate is the test itself.

Reads only. Mints nothing.
"""
from __future__ import annotations
import sys
from collections import Counter
from chain_walk import ChainWalker, payload

MAX = int(sys.argv[1]) if len(sys.argv) > 1 else 500_000
rows = 0
keys: Counter = Counter()
senders: Counter = Counter()
for e in ChainWalker().walk(max_entries=MAX):
    if e.get("eventType") != "member_notice":
        continue
    rows += 1
    p = payload(e)
    keys.update(p.keys())
    senders[p.get("from_plugin_id")] += 1

print(f"member_notice rows: {rows}")
print(f"  top-level `plugin_id`: {keys.get('plugin_id', 0)}   <- fixture's key")
print(f"  `from_plugin_id`     : {keys.get('from_plugin_id', 0)}   <- production's key")
print("senders:")
for k, v in senders.most_common():
    print(f"  {v:>5}  {k}")
sys.exit(0 if keys.get("plugin_id", 0) == 0 else 1)
