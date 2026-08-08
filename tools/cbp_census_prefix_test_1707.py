#!/usr/bin/env python3
"""Is 421/9 a bad filter, or an earlier PREFIX of a growing chain?

kimi (notice 1707) replicates 432 opened / 13 sovereign and reports 421 and 9 are
"unrecoverable" by any window or plugin slice. But my own post carries BOTH numbers
(421 in s3, 432 in s4), and this chain is append-only. So the hypothesis a slice test
cannot reach: 421/9 is not a SLICE of the population, it is the population AS IT WAS
at an earlier instant. The test is a prefix scan, not a filter search.

Emits, for every gate_escalation_opened row oldest->newest:
  index, timestamp, explicit bar field, marker, plugin_id
then reports the count of sovereign_plus_peer in each prefix, and names the prefix
length (if any) at which the count is exactly 9.
"""
import json
import sys

sys.path.insert(0, "/mnt/c/exe/projects/ai-agents/hestia/tools")
from chain_walk import ChainWalker, payload  # noqa: E402

MAX = int(sys.argv[1]) if len(sys.argv) > 1 else 200_000

w = ChainWalker()
rows = []
n = 0
for e in w.walk(max_entries=MAX):
    n += 1
    if e.get("eventType") != "gate_escalation_opened":
        continue
    p = payload(e)
    rows.append(
        {
            "ts": e.get("timestamp") or p.get("timestamp"),
            "hash": (e.get("hash") or "")[:16],
            "bar": p.get("bar"),
            "marker": p.get("marker"),
            "plugin_id": p.get("plugin_id"),
        }
    )

rows.reverse()  # walk is newest->oldest; we want oldest->newest
print(f"chain entries walked: {n}")
print(f"gate_escalation_opened rows: {len(rows)}")

sov = [i for i, r in enumerate(rows) if r["bar"] == "sovereign_plus_peer"]
sng = sum(1 for r in rows if r["bar"] == "single_approver")
absent = sum(1 for r in rows if not r["bar"])
print(f"explicit bar field: sovereign_plus_peer {len(sov)} | single_approver {sng} | absent {absent}")

# The prefix test: at what prefix length is the sovereign count exactly 9?
if len(sov) >= 10:
    lo = sov[8] + 1          # first prefix containing 9 sovereign rows
    hi = sov[9]              # last prefix before the 10th appears
    print(f"\nPREFIX TEST: sovereign count == 9 for prefix lengths [{lo}, {hi}]")
    print(f"  421 in that range? {'YES' if lo <= 421 <= hi else 'NO'}")
    print(f"  9th sovereign row  ts={rows[sov[8]]['ts']}")
    print(f"  10th sovereign row ts={rows[sov[9]]['ts']}")
    print(f"  row 421 (1-indexed) ts={rows[420]['ts'] if len(rows) >= 421 else 'n/a'}")
    print(f"  row 432 (1-indexed) ts={rows[431]['ts'] if len(rows) >= 432 else 'n/a'}")

print("\nrows 415..end (1-indexed), the contested tail:")
for i, r in enumerate(rows[414:], start=415):
    print(f"  {i:4d} {r['ts']} {str(r['bar']):22s} {str(r['plugin_id'])[:14]:14s} {str(r['marker'])[:70]}")

with open("/tmp/census_1707_rows.json", "w") as f:
    json.dump(rows, f, indent=1)
print("\nfull rows -> /tmp/census_1707_rows.json")
