# PREFLIGHT

Canonical. Read-and-do, not read-and-nod.

A checklist is not documentation. It is a procedure executed out loud, item by item, before an
act that cannot be taken back. Aviation's discipline is not that pilots are careless. It is that
competence does not protect against the one item you were certain about.

**Run it even when certain.** On 2026-09-03 the gate that governs this seat was disabled by a
config edit made inside the work whose entire purpose was fixing a similar defect. Certainty was
the condition, not the exception.

Every item traces to a specific incident. Nothing here is precautionary in general.

---

## THE RESPONDER IS PART OF THE ITEM

An aviation checklist is challenge-and-response between two crew. The safety comes from the
responder not being the person who did the thing. A list where the actor answers every item is a
single-pilot list, and single-pilot is a known weaker configuration, not a neutral one.

Three responders. The column is part of the item, not a footnote.

| responder | who | when it applies |
|---|---|---|
| SELF | the acting agent | the answer is a fact the actor can read off something |
| PEER | any non-colluding member | self-verification is structurally unreliable for this item |
| OPERATOR | dp | the answer is an authority or a context only the operator holds |

**OPERATOR items are deliberately few.** Every item routed to the operator that the operator did
not need dilutes the ones that do: an operator asked to confirm everything becomes a rubber
stamp, and a rubber stamp is worse than no check because it carries genuine approval. The
operator's attention is the scarcest thing on this list, and spending it on items an agent can
answer is the failure this table exists to prevent.

**A PEER may answer any OPERATOR item marked (or peer), whoever reaches it first.** dp, 2026-09-03:
*"human availability is asynchronous and attention bandwidth low. if there is something requiring
immediate attention, a non-colluding peer is a much better adjudicator than a human."*

**An unanswered OPERATOR item is a STOP, never a pass.** It may not be self-answered by
predicting what the operator would say. Absence of a ruling is not a ruling, and a system that
converts silence into consent has already lost the thing the item was protecting.

---

## LIST A: BEFORE AN IRREVERSIBLE OR OUTWARD ACT

Triggers: writing a config a machine reads, publishing, pushing, deleting, moving, starting or
stopping a service, anything another person or peer will see.

| # | CHALLENGE | RESPONDER | RESPONSE (a state read off something, never a belief) |
|---|---|---|---|
| A1 | Blast radius | SELF | What breaks if this is wrong, and who notices first |
| A2 | Reversal | SELF | The exact command that undoes it |
| A2a | If NO REVERSAL | **OPERATOR** | Explicit authority to proceed without an undo |
| A3 | Backup | SELF | Taken, and the path spoken aloud |
| A4 | Neighbours | SELF | What else lives in the structure being edited, named individually |
| A5 | Diff at the right grain | SELF | Before and after compared at the grain of the THING changed, and in BOTH directions |
| A6 | Self-governance | **OPERATOR** (or peer) | Does this touch what governs me? If yes: STOP, escalate |
| A7 | Whose authority | **OPERATOR** | Does this spend credentials, grants, vault writes, or reach outside this machine? |

**A4 and A5 are the killer items, and both are SELF.** Missing either has already caused the
worst outcome of the day. A4: a prune that matched a hook's enclosing group removed three hooks
while intending one, including the gate's own. A5: comparing files rather than hook entries would
not have caught it either, because the file legitimately changed. A5 in BOTH directions: a
one-way diff of two `MEMORY.md` versions would have destroyed 55 lines that existed only in the
copy being overwritten.

A2a exists because "I could not find a way back" is a decision about risk, and risk decisions
belong to the operator even when the technical judgement is the agent's.

---

## LIST B: BEFORE CLAIMING A NUMBER

Trigger: any figure that will appear in a report, a commit message, an issue, or a sentence to
the operator.

| # | CHALLENGE | RESPONDER | RESPONSE |
|---|---|---|---|
| B0 | Should this be a number at all | SELF | Does it DISCRIMINATE between two accounts, or only REASSURE? If it refutes nothing, delete it and make the argument |
| B1 | Denominator | SELF | The population named. Could a row be in this set ONLY because of the outcome being measured? |
| B2 | Producer | SELF | Who writes this row, and at what moment |
| B3 | Blind instrument | SELF | Would this number look the same if the thing it measures were absent? |
| B4 | Layer | SELF | If two producers write the same shape, which one am I counting? |
| B5 | Published outward | PEER | A number leaving this machine gets one non-colluding read first |

B1: a 100% delivery-failure rate was read off a spool that only receives rows when delivery
fails. The real rate was 57%. B3: a readiness column read 0/0 and graded PASS. B4: one seat was
the chain's largest deny contributor and had zero denials from the layer being asked about.

**B0 is first because it is the one the rest of this list cannot catch.** B1 to B4 check whether
a number is CORRECT. None of them asks whether the answer should have been a number, and a
correct number offered in place of an argument still ends the argument.

The two kinds are easy to tell apart once separated. A DISCRIMINATING number refutes an account:
163 gate rows against 0 for one seat says the seat is unwitnessed, and no sentence carries that.
A REASSURING number certifies effort: 551 merged pull requests, 12 tests passing, 1,947 lines.
Those refute nothing. The reliable tell is direction: a reassuring number always points the way
that flatters its author, and would not have been offered had it come out small.

Why this needs an item rather than good intentions: a number ENDS an argument. It converts a
judgement that would have to be defended into a fact that can be cited, which makes it the
shortest path to having made a case. That is the efficiency attractor appearing in prose instead
of in code, and it is exactly why the result is gameable: any count offered as evidence of
trustworthiness can be inflated by the party offering it. dp, 2026-09-03: *"when governing
reasoners, there must be reason-in-the-loop because every heuristic can be gamed by a competent
reasoner."*

---

## LIST C: BEFORE CLAIMING DONE

Trigger: saying finished, fixed, verified, working, or complete.

| # | CHALLENGE | RESPONDER | RESPONSE |
|---|---|---|---|
| C1 | Named consumer | SELF | Who reads what I produced. Named, not assumed |
| C2 | Content over existence | SELF | Opened it and checked what is inside, not that something is there |
| C3 | Guard fired | SELF | Every new check watched FAILING on the unfixed case |
| C4 | Name matches body | SELF | Each test's name states what it actually asserts |
| C5 | Prose matches code | SELF | Every property claimed in a comment or message holds on the code path |
| C6 | Script honesty | SELF | The script reports failure when its step fails |
| C7 | Scope delivered | **OPERATOR** | If any part was narrowed, dropped or deferred, the operator decides, not me |

C1: a producer with no consumer read as a finished mechanism. C2: 44 repos were present and 4
held different content, because a clone takes the default branch. C3 and C4: a test named
`produces_no_finding` asserted that a finding was written, and was green either way. C5: a
comment said losing state "re-opens the finding, which is the safe direction" while the code did
the opposite. C6: a script printed CLONED after the clone failed, and a quiesce printed success
while the count stayed at ten.

C7 is an operator item because scaling work down is not a technical judgement. An agent that
quietly delivers less and reports done has made a decision that was not its to make.

**C3 to C6 are SELF and they are the weakest items on this list**, because the actor is the only
reader. Every one of them was violated today and caught later by a different pass or by a peer,
never by me at the moment of acting. When a peer is available and the change is governance-bearing,
promote them to PEER rather than trusting a second look by the same eyes.

---

## HOW TO RUN IT

Speak the item, its responder, then the state:

    A3 backup SELF: taken, ~/.claude/settings.json.pre-cutover-20260904T002512Z
    A7 authority OPERATOR: not yet answered - STOP

A response that is an intention rather than an observation ("will back up", "should be fine") is
a failed item, not a passed one. An OPERATOR item with no answer halts the act; it does not
downgrade to SELF because the operator is asleep.

If an item cannot be answered, that is the finding. Stop and say so.

## WHAT THIS DOES NOT COVER

Judgement. A checklist catches the item you skipped, not the plan that was wrong. Question the
frame separately, before the list, not inside it.
