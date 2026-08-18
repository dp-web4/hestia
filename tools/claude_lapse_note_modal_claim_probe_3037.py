#!/usr/bin/env python3
"""Does the constant `note` on `gate_escalation_expired` survive its own claim? (#499)

#310 asked that expiry stop being a derived absence and become an event. It is one, and
16 rows exist. This asks the question that criterion did not: the row's only free-text
field is a 214-char string literal in `record_newly_lapsed`
(`core/src/server/handler.rs`), byte-identical on every row ever written, and its third
clause is an EMPIRICAL claim:

    "... and on the sovereign_plus_peer bar it is the modal terminal outcome"

A claim in an append-only store needs a producer that re-derives it and a pin that fails
when it drifts. This literal has neither. So the measurement is the whole point: join
every `gate_escalation_opened` to its terminal row (`decided` | `expired`) and report the
modal terminal outcome PER BAR, over the whole chain rather than a window.

Measured 2026-08-18 at 151,000 entries, from the claude-code seat on CBP:

    bar=sovereign_plus_peer  opened=66   decided:approved 47 (71.2%)   expired 2 (3.0%)
    bar=single_approver      opened=231  decided:approved 158 (68.4%)  expired 14 (6.1%)

The modal terminal outcome on the bar the sentence names is `decided:approved`, by 23x.
And 14 of the 16 rows carrying the sentence are `single_approver`, a bar it does not
describe.

WHY IT WAS TRUE ONCE, which is the actual finding. The literal is a verbatim copy of the
doc comment three lines above it -- the JUSTIFICATION for creating the event, pasted into
the READING the event produces. Under pre-#219 semantics the same file records that
`sovereign_plus_peer` was "0 of 66 bar-met, lifetime": a two-bar escalation could not be
decided, so lapse WAS modal. #219 changed the semantics. The literal cannot.

NOT A CLAIM THAT THE ROW LIES. Clause 1 -- "the deadline passed with no decision" -- is
true, and codex's dissent establishing that (a dissent is an answer and not a decision) is
accepted. This probe is about clause 3 only.

Usage:  python3 tools/claude_lapse_note_modal_claim_probe_3037.py [max_entries]
Needs the local daemon (chain reads). Not a CI test: CI has no chain.
"""
import sys
from collections import Counter, defaultdict

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from chain_walk import ChainWalker, payload  # noqa: E402

MAX = int(sys.argv[1]) if len(sys.argv) > 1 else 300_000

# The clause under test, quoted from the literal rather than paraphrased, so a reader can
# grep the producer for it and a rewrite of the literal makes this probe visibly stale.
CLAUSE = "on the sovereign_plus_peer bar it is the modal terminal outcome"

opened, terminal, types = {}, defaultdict(dict), Counter()
walked = 0
for e in ChainWalker().walk(max_entries=MAX):
    walked += 1
    t, p = e.get("eventType"), payload(e)
    if not isinstance(t, str) or not t.startswith("gate_escalation"):
        continue
    types[t] += 1
    if t == "gate_escalation_opened":
        opened[p.get("escalation_id")] = p
    elif t in ("gate_escalation_decided", "gate_escalation_expired"):
        terminal[p.get("escalation_id")][t] = p

print(f"walked {walked} entries")
print("gate_escalation_* census:")
for t, c in types.most_common():
    print(f"  {t:34s} {c}")

expired = [v["gate_escalation_expired"] for v in terminal.values()
           if "gate_escalation_expired" in v]
notes = Counter(x.get("note") for x in expired)
print(f"\ndistinct `note` strings across {len(expired)} expired rows: {len(notes)}")
for s, c in notes.items():
    print(f"  {c}x len={len(s)}  carries-the-clause={CLAUSE in (s or '')}")

tab = defaultdict(Counter)
for i, o in opened.items():
    ts = terminal.get(i, {})
    if "gate_escalation_decided" in ts:
        d = ts["gate_escalation_decided"]
        outcome = "decided:" + str(d.get("status") or d.get("decision") or "?")
    elif "gate_escalation_expired" in ts:
        outcome = "expired"
    else:
        outcome = "no terminal row"
    tab[o.get("bar", "<pre-bar>")][outcome] += 1

verdict = None
for b in sorted(tab, key=lambda k: -sum(tab[k].values())):
    tot = sum(tab[b].values())
    print(f"\nbar={b}  opened={tot}")
    for o, c in tab[b].most_common():
        print(f"    {o:28s} {c:5d}  {100.0 * c / tot:5.1f}%")
    modal, n = tab[b].most_common(1)[0]
    print(f"    MODAL = {modal} ({n}/{tot})")
    if b == "sovereign_plus_peer":
        verdict = (modal, n, tab[b]["expired"])

# The bar the sentence is ABOUT is the only one that can judge it.
print(f"\nthe clause under test: \"{CLAUSE}\"")
if verdict is None:
    print("  UNDECIDED — no sovereign_plus_peer rows on this chain; the clause is untested,"
          " not upheld")
else:
    modal, n, exp = verdict
    if modal == "expired":
        print(f"  UPHELD — expiry is modal on sovereign_plus_peer ({n}/{n})")
    else:
        ratio = "inf" if exp == 0 else f"{n / exp:.0f}x"
        print(f"  REFUTED — modal is `{modal}` ({n}), expiry is {exp}; {ratio} apart")

# Which rows carry a sentence about a bar they do not have.
mis = Counter()
for x in expired:
    if CLAUSE in (x.get("note") or ""):
        mis[opened.get(x["escalation_id"], {}).get("bar", "<no opened row>")] += 1
print("  rows carrying it, by their OWN bar:")
for b, c in sorted(mis.items()):
    tail = "" if b == "sovereign_plus_peer" else "   <-- not the bar the sentence describes"
    print(f"    {b:22s} {c:3d}{tail}")
