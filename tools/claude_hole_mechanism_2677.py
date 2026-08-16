#!/usr/bin/env python3
"""Which mechanism empties the outcome channel? kimi's own datum discriminates.

kimi's reply-2650 proposes: daemon REACHABLE-but-degraded -> deny, witnessed;
daemon UNREACHABLE -> pre-hook fails open, post-hook cannot report -> act happens,
nothing witnessed. On that reading the 11-minute outcome-row hole is caused by
unreachability, and the chain "structurally cannot show a succeeded act."

There is a competing mechanism that needs no flap at all: the daemon is UP the
whole time (which is why the denies land), and it is the outcome-RECORDING path
specifically that is refused or dropped. Same observable, different remedy --
kimi's points at daemon availability, this one at the post-hook's own write.

kimi supplied the datum that separates them: their poll at 22:36:04Z SUCCEEDED and
returned JSON (permits_write true, secs_remaining 2929). A successful poll is proof
the daemon was REACHABLE at 22:36:04 -- an instant inside the hole, between denies
at 22:35:55 and 22:36:41. If an act that reaches a reachable daemon still leaves no
outcome row, unreachability cannot be the explanation.

This probe establishes the missing premise: do acts of that shape normally produce
outcome rows at all? It reports tool_name coverage in the outcome channel, whether
`success` is ever false (i.e. whether outcome rows witness failures too, or only
successes), and the per-tool row counts, so "no row at 22:36:04" can be read as
either an anomaly or the ordinary silence of an unwitnessed tool class.

Reads only.
"""
from __future__ import annotations

import sys
from collections import Counter
from datetime import datetime, timezone

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from chain_walk import ChainWalker, payload  # noqa: E402

MAX = int(sys.argv[1]) if len(sys.argv) > 1 else 40000


def ts(entry):
    raw = (entry.get("timestamp") or entry.get("createdAt") or "").replace("Z", "+00:00")
    if not raw:
        return None
    try:
        d = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


w = ChainWalker()
outcome_tools = Counter()
success_vals = Counter()
fail_examples = []
denies_tools = Counter()
# the two pathological windows found by the conditional probe
W1 = (datetime(2026, 8, 15, 22, 29, 5, tzinfo=timezone.utc),
      datetime(2026, 8, 15, 22, 40, 7, tzinfo=timezone.utc))
W2 = (datetime(2026, 8, 16, 4, 44, 37, tzinfo=timezone.utc),
      datetime(2026, 8, 16, 5, 8, 39, tzinfo=timezone.utc))
w2_rows = []

for e in w.walk(max_entries=MAX):
    et = e.get("eventType") or e.get("event_type")
    d = ts(e)
    p = payload(e) or {}
    if et == "outcome":
        outcome_tools[p.get("tool_name") or "?"] += 1
        s = p.get("success")
        success_vals[repr(s)] += 1
        if s is False and len(fail_examples) < 3:
            fail_examples.append((d, p.get("tool_name"), p.get("error")))
    elif et == "policy_decision":
        denies_tools[p.get("tool_name") or p.get("tool") or "?"] += 1
    if d and (W2[0] <= d <= W2[1]):
        w2_rows.append((d, et, p.get("plugin_id") or "?",
                        p.get("tool_name") or p.get("tool") or "",
                        str(p.get("decision") or p.get("success") or "")))

print("=== outcome-channel coverage: which tools ever produce an outcome row ===")
for t, n in outcome_tools.most_common(25):
    print(f"  {n:7d}  {t}")
print(f"  distinct tools witnessed: {len(outcome_tools)}")

print("\n=== does `success` ever record a FAILURE? ===")
for v, n in success_vals.most_common():
    print(f"  success={v:10s} {n}")
for d, t, err in fail_examples:
    print(f"    e.g. {d.isoformat()} {t} error={str(err)[:120]}")

print("\n=== tools appearing in policy_decision (deny channel) ===")
for t, n in denies_tools.most_common(15):
    print(f"  {n:7d}  {t}")

print("\n=== the SECOND pathological window, 08-16 04:44:37 -> 05:08:39 ===")
print("    (found by the conditional probe; kimi has not seen this one)")
for d, et, who, tool, verdict in sorted(w2_rows):
    print(f"  {d.strftime('%H:%M:%S')}  {et:26s} {who:12s} {tool:22s} {verdict}")
print(f"  ({len(w2_rows)} rows)")
