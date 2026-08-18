#!/usr/bin/env python3
"""Does the new `gate_escalation_expired` record distinguish REVIEWED from UNASKED?

#310 asked for expiry to become an event so that "nobody answered" would be a measurable
outcome rather than an absence. The event now exists and is live. This asks the next
question, which #310's acceptance criteria never posed: among rows that lapsed, can a
reader tell the ones a peer actually answered from the ones nobody was ever asked?

Three things are measured, all from the one chain, so the answer is reproducible from any
seat:

  1. Every `gate_escalation_expired` row, joined to its `gate_escalation_opened` row and
     to every `gate_escalation_corroborated` row that names it. Prints invited-peer count,
     factor count, dissent count, and whether the `note` is byte-identical across rows.
     A constant note over a varying join is a gauge that cannot move.

  2. Whether each corroboration landed BEFORE the deadline it is being compared against.
     A dissent filed after `expires_at` would make "the deadline passed with no decision"
     literally true, and the finding would be mine to withdraw.

  3. Invitation dispatch by bar over the WHOLE chain, not a window. This replicates
     PR#455's 123-vs-46 at the full denominator; c9e49be already carries the fix and is
     blocked on the registry prune (#454). Reported here because it is the other half of
     why these rows lapsed, and because a replication at a wider denominator is cheap.

Usage:  python3 tools/claude_lapse_record_discriminates_nothing_2988.py [max_entries]
"""
import json
import sys
from collections import Counter, defaultdict

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from chain_walk import ChainWalker, payload  # noqa: E402

MAX = int(sys.argv[1]) if len(sys.argv) > 1 else 200_000

opened, expired = {}, []
corr = defaultdict(list)
walked = 0

for e in ChainWalker().walk(max_entries=MAX):
    walked += 1
    t, p = e.get("eventType"), payload(e)
    if t == "gate_escalation_opened":
        opened[p.get("escalation_id")] = p
    elif t == "gate_escalation_corroborated":
        corr[p.get("escalation_id")].append(p)
    elif t == "gate_escalation_expired":
        expired.append(p)

print(f"walked {walked} entries; opened={len(opened)} expired={len(expired)}")

# --- 1. the terminal record, joined to what actually happened -----------------
notes = Counter(x.get("note") for x in expired)
print(f"\n[1] distinct `note` strings across {len(expired)} expired rows: {len(notes)}")
for n, c in notes.items():
    print(f"    {c}x {n[:96]}...")

print(f"\n{'escalation':18s} {'bar':20s} {'invited':>7s} {'factors':>7s} "
      f"{'dissents':>8s} {'waited_s':>8s}")
answered = 0
for x in sorted(expired, key=lambda r: r.get("lapsed_at", 0)):
    i = x["escalation_id"]
    o, cs = opened.get(i, {}), corr.get(i, [])
    d = sum(1 for c in cs if c.get("dissent"))
    answered += 1 if cs else 0
    print(f"{i:18s} {o.get('bar','<pre-bar>'):20s} "
          f"{len(o.get('invited_peers') or []):7d} {len(cs):7d} {d:8d} "
          f"{x.get('lapsed_at',0) - x.get('opened_at',0):8d}")
print(f"\n    answered-then-lapsed: {answered}/{len(expired)}   "
      f"never-invited: {sum(1 for x in expired if not (opened.get(x['escalation_id'],{}).get('invited_peers') or []))}"
      f"/{len(expired)}")
print("    the terminal record carries neither number; its keys are:")
if expired:
    print(f"      {sorted(expired[0].keys())}")

# --- 2. control: did the answer beat the deadline? ---------------------------
print("\n[2] every corroboration on a lapsed row, vs the deadline it lapsed against")
for x in expired:
    i = x["escalation_id"]
    for c in corr.get(i, []):
        for f in c.get("factors_present") or []:
            at, exp = f.get("at"), x.get("expires_at")
            if at is None or exp is None:
                print(f"    {i} {f.get('by')}: MISSING timestamp — cannot judge")
                continue
            print(f"    {i} {f.get('by'):8s} dissent={bool(f.get('dissent'))!s:5s} "
                  f"{exp - at:+6d}s before expiry  ({'BEFORE' if at < exp else 'AFTER'})")

# --- 3. invitation dispatch by bar, whole chain ------------------------------
tab = defaultdict(Counter)
for i, o in opened.items():
    b = o.get("bar", "<pre-bar>")
    tab[b]["opened"] += 1
    tab[b]["invited>0"] += 1 if (o.get("invited_peers") or []) else 0
    tab[b]["peer_answered"] += 1 if corr.get(i) else 0
print(f"\n[3] {'bar':20s} {'opened':>7s} {'invited>0':>10s} {'peer_answered':>14s}")
for b, c in sorted(tab.items(), key=lambda kv: -kv[1]["opened"]):
    print(f"    {b:20s} {c['opened']:7d} {c['invited>0']:10d} {c['peer_answered']:14d}")
