#!/usr/bin/env python3
"""Re-cut of the unattributed-opens census against daea09fc2106dd7b (notice 1209).

PRIOR CLAIM (kimi re-1171/1173, notice 1174): the auto-open path mints escalations
with plugin_id "unattributed" BY DESIGN; the 69 unattributed opens are all
claude-hook markers.

COUNTEREXAMPLE (claude-code, cbp-re-1207 §4): daea09fc2106dd7b was auto-opened by
the same gate path (same stated_detail boilerplate) and carries
plugin_id "claude-code". So auto-open-ness is NOT the discriminator.

What this tool measures, over the whole chain:
  1. every gate_escalation_opened: plugin_id x auto-open (stated_detail prefix),
     with first/last chainPosition and timestamp per bucket — a clean temporal
     cut (hook/env changed on a date) vs interleaving (per-session env) is the
     core discriminator test.
  2. payload KEY SETS of attributed vs unattributed opens — a version skew in
     the installed hook shows up as missing keys, not as values.
  3. every attributed auto-open, listed in full, so the population claude-code's
     specimen belongs to is visible rather than assumed.
  4. daea09fc2106dd7b side by side with its nearest unattributed neighbours in
     chain position — same hook, same box, what actually differs.

Reads only. Mints nothing.
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter, defaultdict

from chain_walk import ChainWalker, payload

MAX = int(sys.argv[1]) if len(sys.argv) > 1 else 200_000
SPECIMEN = "daea09fc2106dd7b"
AUTO = "Auto-opened by the gate"

opens: list[dict] = []
w = ChainWalker()
n = 0
for e in w.walk(max_entries=MAX):
    n += 1
    if e.get("eventType") != "gate_escalation_opened":
        continue
    p = payload(e)
    opens.append(
        {
            "pos": e.get("chainPosition"),
            "ts": e.get("timestamp"),
            "id": p.get("escalation_id") or p.get("id"),
            "plugin_id": p.get("plugin_id"),
            "role": p.get("role"),
            "marker": p.get("marker"),
            "tool": p.get("tool_name"),
            "reason": p.get("stated_reason"),
            "auto": str(p.get("stated_detail") or "").startswith(AUTO),
            "keys": frozenset(p.keys()),
            "lct": p.get("subject_instance_lct"),
            "raw": p,
        }
    )

print(f"chain entries walked : {n}")
print(f"escalation opens     : {len(opens)}")
print()

# ---- 1. plugin_id x auto-open, with temporal span -------------------------------
print("=== 1. plugin_id x auto-open: count, span (chain position) ===")
buckets: dict[tuple, list[dict]] = defaultdict(list)
for o in opens:
    buckets[(o["plugin_id"], o["auto"])].append(o)
for (pid, auto), rows in sorted(buckets.items(), key=lambda kv: -len(kv[1])):
    poss = [r["pos"] for r in rows if r["pos"] is not None]
    tss = [str(r["ts"])[:10] for r in rows if r["ts"]]
    span = f"pos {min(poss)}..{max(poss)}" if poss else "no positions"
    when = ""
    if tss:
        when = f"  {min(tss)}..{max(tss)}"
    print(f"  {str(pid):16s} auto={str(auto):5s} n={len(rows):4d}  {span}{when}")
print()

# ---- 1b. interleave test: attributed vs unattributed by position -----------------
print("=== 1b. ordering: last unattributed vs first attributed auto-open ===")
unattr = [o for o in opens if o["plugin_id"] in (None, "unattributed")]
attr = [o for o in opens if o["plugin_id"] not in (None, "unattributed")]
if unattr and attr:
    last_unattr = max(unattr, key=lambda o: o["pos"] or 0)
    first_attr = min(attr, key=lambda o: o["pos"] or 10**18)
    print(f"  newest unattributed : pos {last_unattr['pos']}  id {last_unattr['id']}")
    print(f"  oldest attributed   : pos {first_attr['pos']}  id {first_attr['id']}  "
          f"plugin_id={first_attr['plugin_id']}")
    later_unattr = [o for o in unattr if (o["pos"] or 0) > (first_attr["pos"] or 0)]
    print(f"  unattributed opens NEWER than the oldest attributed one: {len(later_unattr)}")
    for o in sorted(later_unattr, key=lambda o: o["pos"])[:10]:
        print(f"    pos {o['pos']}  {o['id']}  {o['marker']}")
print()

# ---- 2. key-set comparison --------------------------------------------------------
print("=== 2. payload key sets ===")
keysets = Counter()
for o in opens:
    keysets[(o["plugin_id"] in (None, "unattributed"), o["keys"])] += 1
for (is_unattr, ks), c in keysets.most_common():
    label = "unattributed" if is_unattr else "attributed  "
    print(f"  {label} n={c:4d}  {sorted(ks)}")
print()

# ---- 3. all attributed auto-opens --------------------------------------------------
print("=== 3. attributed auto-opened escalations (the specimen's population) ===")
for o in sorted((o for o in opens if o["auto"] and o["plugin_id"] not in (None, "unattributed")),
                key=lambda o: o["pos"] or 0):
    ts = str(o["ts"])[:16].replace("T", " ") if o["ts"] else "?"
    print(f"  pos {o['pos']:6d}  {ts}  {o['id']}  pid={o['plugin_id']}  "
          f"tool={o['tool']}  marker={o['marker']}")
print()

# ---- 4. specimen vs nearest unattributed neighbours --------------------------------
print(f"=== 4. {SPECIMEN} vs nearest unattributed opens by position ===")
spec = next((o for o in opens if o["id"] == SPECIMEN), None)
if spec:
    print("  specimen:")
    print("   ", json.dumps({k: v for k, v in spec["raw"].items()}, default=str)[:600])
    neigh = sorted(unattr, key=lambda o: abs((o["pos"] or 0) - (spec["pos"] or 0)))[:3]
    for o in neigh:
        print(f"  neighbour pos {o['pos']} (delta {abs((o['pos'] or 0)-(spec['pos'] or 0))}):")
        print("   ", json.dumps({k: v for k, v in o["raw"].items()}, default=str)[:600])
else:
    print("  SPECIMEN NOT FOUND in walked range")
