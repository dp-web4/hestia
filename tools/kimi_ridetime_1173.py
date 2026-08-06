#!/usr/bin/env python3
"""Independent re-run of CBP's ride-time claims (forum post 'an approval outlives the
session that earned it', 2026-08-06). Kimi seat. Chain-only: no transcripts (the session
join reads ~/.claude, outside this seat's MRH), so this reproduces the LIFETIME half —
decided_horizon anchored at opened_at means ride-after-grant far exceeds the documented
600s — not the session-join half.

Method note: uses the RECORDED fields on each claimed row. The open->decide gap is
derived as secs_from_open_to_use - secs_from_decision_to_use ON THE SAME ROW, not from
the decide row's secs_into_window: the two disagree on a few escalations (decide-row
join yields median 4131 / max 4191 instead of 4160 / 4200), consistent with re-decided
escalations where the claim binds to the latest decide. available ride after grant =
4200 - (open->decide gap)  [= opened_at + DEFAULT_TTL_SECS + APPROVAL_CLAIM_WINDOW_SECS
- decided_at].

Claims checked (CBP values in parentheses):
  1. available ride after grant: min/median/max (2918 / 4160 / 4200)
  2. claims whose available ride exceeded 600s (63/63)
  3. longest actual ride secs_from_decision_to_use (3901s)
  4. refused under a decided_at+600 anchor (20 = 15 cross + 5 same among the 56
     transcript-joined; chain alone cannot split the arms, so this reports the total
     over all 63 — expect 20 + however many of the 7 unjoined rode >600s)
"""
import sys
sys.path.insert(0, "/mnt/c/exe/projects/ai-agents/hestia/tools")
from chain_walk import ChainWalker, payload

MAX = 20000
HORIZON = 3600 + 600  # DEFAULT_TTL_SECS + APPROVAL_CLAIM_WINDOW_SECS

claimed = []
w = ChainWalker()
n = 0
first_ts = last_ts = None
for e in w.walk(max_entries=MAX):
    n += 1
    t = e.get("timestamp")
    if first_ts is None:
        first_ts = t
    last_ts = t
    if e.get("eventType") == "gate_escalation_claimed":
        claimed.append(payload(e))

avail, actual, missing = [], [], 0
for p in claimed:
    try:
        gap = p["secs_from_open_to_use"] - p["secs_from_decision_to_use"]
        avail.append(HORIZON - gap)
        actual.append(p["secs_from_decision_to_use"])
    except (KeyError, TypeError):
        missing += 1

avail.sort()
med = avail[len(avail)//2] if len(avail) % 2 else (avail[len(avail)//2-1]+avail[len(avail)//2])/2
print(f"entries walked: {n}  window: {last_ts} -> {first_ts}")
print(f"claimed: {len(claimed)}  with both fields: {len(avail)}  missing: {missing}")
print(f"1. available ride after grant: min={avail[0]}s median={med}s max={avail[-1]}s")
print(f"2. available ride > 600s: {sum(1 for a in avail if a > 600)}/{len(avail)}")
print(f"3. actual ride: max={max(actual)}s")
print(f"4. refused under decided_at+600 anchor (ride > 600): {sum(1 for r in actual if r > 600)}/{len(actual)}")
