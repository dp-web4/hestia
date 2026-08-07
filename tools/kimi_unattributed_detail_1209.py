#!/usr/bin/env python3
"""Detail dump for notice 1209 — the rows the recut census pointed at.

Prints, over the whole chain:
  1. EVERY unattributed auto-open (stated_detail starts "Auto-opened by the gate"),
     full stated_reason — the recut found 6, all 2026-08-06, and the 3 nearest to
     daea09fc2106dd7b all carry operator/deploy/test-shaped Bash commands. If all 6
     are that shape, the discriminator (member-session env pin vs bare process) is
     fully visible from the chain.
  2. The single lifetime kimi-code open (pos 76324 per the recut) — my re-1171/1173
     claim measured a window and said 0; the lifetime count is 1 and this is what it was.
  3. First/last attributed auto=False open, to bound the interleave claim.

Reads only. Mints nothing.
"""
from __future__ import annotations

import json
import sys

from chain_walk import ChainWalker, payload

MAX = int(sys.argv[1]) if len(sys.argv) > 1 else 200_000
AUTO = "Auto-opened by the gate"

w = ChainWalker()
n = 0
unattr_auto: list[dict] = []
kimi_opens: list[dict] = []
attr_nonauto_first = None
attr_nonauto_last = None
for e in w.walk(max_entries=MAX):  # newest -> oldest
    n += 1
    if e.get("eventType") != "gate_escalation_opened":
        continue
    p = payload(e)
    pid = p.get("plugin_id")
    auto = str(p.get("stated_detail") or "").startswith(AUTO)
    row = {"pos": e.get("chainPosition"), "ts": e.get("timestamp"), "p": p}
    if pid in (None, "unattributed") and auto:
        unattr_auto.append(row)
    if pid == "kimi-code":
        kimi_opens.append(row)
    if pid not in (None, "unattributed") and not auto:
        if attr_nonauto_first is None:
            attr_nonauto_first = row  # newest first
        attr_nonauto_last = row

print(f"chain entries walked: {n}")
print()
print("=== 1. ALL unattributed auto-opens (newest first) ===")
for r in unattr_auto:
    p = r["p"]
    print(f"pos {r['pos']}  {str(r['ts'])[:19]}")
    print(f"  id     : {p.get('escalation_id')}")
    print(f"  marker : {p.get('marker')}")
    print(f"  role   : {p.get('role')}")
    print(f"  reason : {p.get('stated_reason')}")
print()
print("=== 2. lifetime kimi-code opens ===")
for r in kimi_opens:
    print(f"pos {r['pos']}  {str(r['ts'])[:19]}")
    print(json.dumps(r["p"], indent=1, default=str)[:900])
print()
print("=== 3. attributed auto=False span ===")
for label, r in (("oldest", attr_nonauto_last), ("newest", attr_nonauto_first)):
    if r:
        print(f"  {label}: pos {r['pos']}  {str(r['ts'])[:19]}  pid={r['p'].get('plugin_id')}")
