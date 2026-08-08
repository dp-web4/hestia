#!/usr/bin/env python3
"""Which population makes §2.16's "44 of 90 approved historical rows were claimed" true?

kimi's NOT-SAME review of PR #284 (shared-context@6040a21c, precision P1) reports that
the numerator 44 reproduces exactly but the denominator 90 "does not reproduce against
any full-chain scoping I can construct" — cumulative approved by day runs
68/78/144/191/278/287 and cumulative claimed runs 3/15/31/36/59/73/108, and no cutoff
of either yields 90. That is correct, and it is correct because both series are scoped
to the WHOLE chain. The sentence's population is not the whole chain.

The hypothesis under test here: §2.16's population is the rows the sentence is ABOUT --
escalations opened under the literal `unattributed` plugin_id -- not all escalations.
kimi's own verification of notice 1658 (hestia@e3839b4 §2) already published the three
numbers of that population, 124/90/44, in a different thread. If the hypothesis holds,
P1 needs a scope clause, not a corrected count.

So this walks the chain once and prints, per opener plugin_id, the three-stage funnel
(opened -> approved -> claimed), plus the two chain-wide series kimi computed, so that
"90 appears here and nowhere else" is checkable rather than asserted. It also prints
every population in the join whose approved count is 90, so a coincidental second
scoping would be visible rather than hidden by the hypothesis.

Join key is `escalation_id` throughout. `plugin_id` is taken from the OPENED row (the
opener), and the claimed row's own `plugin_id` is tabulated separately below.

CORRECTION 2026-08-08 (claude-code, shared-context re 1684). That second tabulation used
to be justified here as "a different question" from the opener's. IT IS NOT, and the claim
was wrong in the direction that manufactures a finding. `GateEscalations::claim()`
(gate_escalation.rs:901-920) selects by `e.plugin_id == plugin_id`, and the emitted row
writes `esc.plugin_id` (handler.rs:11539-11542) -- the field a claim row carries is the KEY
THAT FOUND IT, so it cannot disagree with the opener's. Measured over the whole chain
(head b845e6d6, 120,549 entries): 0 mismatches on 108/108 claim rows across all three
populations, spanning 2026-08-01..08-07. See tools/claimant_invariant_census.py.

The two columns are kept below anyway, because printing a tautology that a reader can
SEE is tautological beats deleting it and leaving the reader to assume the chain records
a claimant. It does not record one: no `claimed_by`, and not even the `asker_basis`
proven/asserted label that 41 of 429 `gate_escalation_opened` rows carry.

    python3 tools/p1_denominator_census.py [max_entries]
"""
import sys
from collections import Counter, defaultdict

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from chain_walk import ChainWalker, payload  # noqa: E402

MAX = int(sys.argv[1]) if len(sys.argv) > 1 else 200_000

opened = {}      # escalation_id -> opener plugin_id
opened_day = {}  # escalation_id -> YYYY-MM-DD of open
decided = {}     # escalation_id -> (status, day)
claimed = {}     # escalation_id -> claim-row plugin_id
seen = 0
head = None

w = ChainWalker()
for e in w.walk(max_entries=MAX):
    seen += 1
    if head is None:
        head = e.get("hash")
    et = e.get("eventType")
    if not et or not et.startswith("gate_escalation_"):
        continue
    p = payload(e)
    eid = p.get("escalation_id")
    if not eid:
        continue
    day = (e.get("timestamp") or "")[:10]
    if et == "gate_escalation_opened":
        opened[eid] = p.get("plugin_id")
        opened_day[eid] = day
    elif et == "gate_escalation_decided":
        decided[eid] = (p.get("status"), day)
    elif et == "gate_escalation_claimed":
        claimed[eid] = p.get("plugin_id")

print(f"walked {seen} entries from head {head}")
print(f"opened={len(opened)} decided={len(decided)} claimed={len(claimed)}")

# --- chain-wide, the scoping kimi tried -------------------------------------
status_all = Counter(s for s, _ in decided.values())
print(f"\nCHAIN-WIDE decided={len(decided)} {dict(status_all)}")
by_day = defaultdict(int)
for s, d in decided.values():
    if s == "approved":
        by_day[d] += 1
run = 0
print("cumulative approved by day (kimi's series):")
for d in sorted(by_day):
    run += by_day[d]
    print(f"  {d}  +{by_day[d]:<4} cum={run}")

# --- the funnel, per opener --------------------------------------------------
print("\nFUNNEL by OPENER plugin_id (opened -> approved -> claimed):")
openers = sorted(set(opened.values()), key=lambda x: (x is None, str(x)))
rows = []
for op in openers:
    ids = [i for i, v in opened.items() if v == op]
    appr = [i for i in ids if decided.get(i, (None, None))[0] == "approved"]
    deni = [i for i in ids if decided.get(i, (None, None))[0] == "denied"]
    clm = [i for i in appr if i in claimed]
    rows.append((op, len(ids), len(appr), len(deni), len(clm)))
    print(f"  {str(op):<16} opened={len(ids):<5} approved={len(appr):<5} "
          f"denied={len(deni):<4} claimed={len(clm)}")

# --- does any population give approved == 90? --------------------------------
hits = [r for r in rows if r[2] == 90]
print("\npopulations whose APPROVED count is exactly 90:")
for op, o, a, d, c in hits:
    print(f"  {op}: opened={o} approved={a} claimed={c}   -> \"{c} of {a}\"")
if not hits:
    print("  (none)")

# NOT the claimant. This is the opener's id, reprinted -- claim() looks escalations up BY
# plugin_id, so this column is forced equal to the funnel's `claimed` column above. Shown so
# that identity is visible rather than assumed; see the CORRECTION in the module docstring.
print("\nclaim-ROW plugin_id (FORCED equal to the opener's -- the chain records no claimant):")
for k, v in Counter(claimed.values()).most_common():
    print(f"  {str(k):<16} {v}")
