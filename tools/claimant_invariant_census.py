#!/usr/bin/env python3
"""Is the claim row's plugin_id an independent observation, or the opener's, forced?

kimi (shared-context@8a922a3f) measured A==D, B==C, |A&B|=0 across the 44-collision and
read it as a finding about the data ("claimant id == opener id within both 44-sets").
`GateEscalations::claim()` filters `e.plugin_id == plugin_id` and the emitted row writes
`esc.plugin_id`, so in THIS build those identities cannot fail. But the chain was written
by whatever build was deployed at the time, so the invariant is a prediction about
history, not a fact about it. One mismatch anywhere = an older build recorded a real
claimant and the collision is a genuine two-measurement result.

Reports mismatches, and the per-population identity kimi computed, over the WHOLE chain --
not just the two 44s -- so 'holds for the sets I looked at' cannot pass for 'holds'.

Result (2026-08-08, head b845e6d6, 120,549 entries): 108/108 claim rows matched their
opener, 0 mismatches, across claude-code (44), unattributed (44) and codex (20), spanning
2026-08-01..08-07. `codex` is the load-bearing arm: a third population outside both 44s
agreeing exactly is what a tautology looks like, not what a measurement looks like.

Also censuses identity fields on the claim payload vs the opened payload. The claim row
carries no `claimed_by`, no `session_id`, and not even `asker_basis` -- the proven/asserted
label that 41 of 429 opened rows carry, computed on the claim path too and used only to
route invitations. So the chain records that a permit was spent, the population it belonged
to, and who APPROVED it; it records nothing about who spent it.
"""
import sys
from collections import Counter, defaultdict
sys.path.insert(0, "tools")
from chain_walk import ChainWalker, payload

MAX = int(sys.argv[1]) if len(sys.argv) > 1 else 200_000
opened, claimed_pid, decided, claim_day = {}, {}, {}, {}
seen, head = 0, None
w = ChainWalker()
for e in w.walk(max_entries=MAX):
    seen += 1
    if head is None:
        head = e.get("hash")
    et = e.get("eventType") or ""
    if not et.startswith("gate_escalation_"):
        continue
    p = payload(e)
    eid = p.get("escalation_id")
    if not eid:
        continue
    if et == "gate_escalation_opened":
        opened[eid] = p.get("plugin_id")
    elif et == "gate_escalation_decided":
        decided[eid] = p.get("status")
    elif et == "gate_escalation_claimed":
        claimed_pid[eid] = p.get("plugin_id")
        claim_day[eid] = (e.get("timestamp") or "")[:10]

print(f"walked {seen} entries from head {head}")
print(f"opened={len(opened)} decided={len(decided)} claimed={len(claimed_pid)}")

# THE TEST: every claimed escalation whose opener we also saw.
paired = [(i, opened[i], claimed_pid[i]) for i in claimed_pid if i in opened]
mismatch = [(i, o, c) for i, o, c in paired if o != c]
orphan = [i for i in claimed_pid if i not in opened]
print(f"\nclaim rows with a visible opener row: {len(paired)}  (orphans: {len(orphan)})")
print(f"MISMATCHES claim_pid != opener_pid: {len(mismatch)}")
for i, o, c in mismatch[:20]:
    print(f"  {i}  opened_by={o!r}  claim_row={c!r}  day={claim_day.get(i)}")
if not mismatch and paired:
    print("  (none — the two tabulations are ONE field. Not two questions.)")

# Per-population, so the result is not read only off the 44s.
print("\nper-population, claimed rows (opener-tab vs claim-row-tab):")
by_open = Counter(o for _, o, _ in paired)
by_claim = Counter(c for _, _, c in paired)
for k in sorted(set(by_open) | set(by_claim), key=lambda x: (x is None, str(x))):
    flag = "" if by_open[k] == by_claim[k] else "   <-- DIFFER"
    print(f"  {str(k):<18} by_opener={by_open[k]:<5} by_claim_row={by_claim[k]}{flag}")

# Does the earliest claim row predate any build that could have differed?
if claim_day:
    days = sorted(set(claim_day.values()))
    print(f"\nclaim rows span {days[0]} .. {days[-1]}  ({len(days)} days)")

# --- what identity does the SPEND row carry at all? --------------------------
# The opener's id is on it, but that is the lookup key. Census the payload keys of both
# halves so "absent" is enumerated rather than inferred from the fields I thought to check.
ckeys, okeys, nc, no = Counter(), Counter(), 0, 0
w2 = ChainWalker()
for e in w2.walk(max_entries=MAX):
    et = e.get("eventType") or ""
    if et == "gate_escalation_claimed":
        nc += 1
        ckeys.update(payload(e).keys())
    elif et == "gate_escalation_opened":
        no += 1
        okeys.update(payload(e).keys())

print(f"\nPAYLOAD KEYS  (claimed n={nc}, opened n={no})")
print("  every key on a claim row, so 'no claimant field' is enumerated not assumed:")
for k, v in sorted(ckeys.items()):
    print(f"    {k:<30} {v}/{nc}")
print("  identity-proof keys, claim vs opened:")
for k in ("claimed_by", "asker_basis", "session_id", "requested_by", "role", "invited_peers"):
    print(f"    {k:<18} claim={ckeys.get(k, 0)}/{nc}   opened={okeys.get(k, 0)}/{no}")
