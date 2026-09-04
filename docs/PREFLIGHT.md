# PREFLIGHT

Canonical. Read-and-do, not read-and-nod.

A checklist is not documentation. It is a procedure executed out loud, item by item, before an
act that cannot be taken back. Aviation's discipline is not that pilots are careless. It is that
competence does not protect against the one item you were certain about.

**Run it even when certain.** On 2026-09-03 the gate that governs this seat was disabled by a
config edit made inside the work whose entire purpose was fixing a similar defect. Certainty was
the condition, not the exception.

Every item below traces to a specific incident. Nothing here is precautionary in general.

---

## LIST A: BEFORE AN IRREVERSIBLE OR OUTWARD ACT

Triggers: writing a config a machine reads, publishing, pushing, deleting, moving, starting or
stopping a service, anything another person or peer will see.

| # | CHALLENGE | RESPONSE (a state read off something, never a belief) |
|---|---|---|
| A1 | Blast radius | Name what breaks if this is wrong, and who notices first |
| A2 | Reversal | The exact command that undoes it, or the words NO REVERSAL |
| A3 | Backup | Taken, and the path spoken aloud |
| A4 | Neighbours | What else lives in the structure being edited, named individually |
| A5 | Diff at the right grain | Before and after compared at the grain of the THING changed, not the file |
| A6 | Self-governance | Does this touch what governs me? If yes: STOP, escalate |

**A4 and A5 are the killer items.** Missing either has already caused the worst outcome of the
day. A4: a prune that matched a hook's enclosing group removed three hooks while intending one,
including the gate's own. A5: comparing files rather than hook entries would not have caught it
either, because the file legitimately changed.

---

## LIST B: BEFORE CLAIMING A NUMBER

Trigger: any figure that will appear in a report, a commit message, an issue, or a sentence to
the operator.

| # | CHALLENGE | RESPONSE |
|---|---|---|
| B1 | Denominator | The population named. Could a row be in this set ONLY because of the outcome being measured? |
| B2 | Producer | Who writes this row, and at what moment |
| B3 | Blind instrument | Would this number look the same if the thing it measures were absent? |
| B4 | Layer | If two producers write the same shape, which one am I counting? |

B1: a 100% delivery-failure rate was read off a spool that only receives rows when delivery
fails. The real rate was 57%. B3: a readiness column read 0/0 and graded PASS. B4: one seat was
the chain's largest deny contributor and had zero denials from the layer being asked about.

---

## LIST C: BEFORE CLAIMING DONE

Trigger: saying finished, fixed, verified, working, or complete.

| # | CHALLENGE | RESPONSE |
|---|---|---|
| C1 | Named consumer | Who reads what I produced. Named, not assumed |
| C2 | Content over existence | Opened it and checked what is inside, not that something is there |
| C3 | Guard fired | Every new check watched FAILING on the unfixed case |
| C4 | Name matches body | Each test's name states what it actually asserts |
| C5 | Prose matches code | Every property claimed in a comment or message holds on the code path |
| C6 | Script honesty | The script reports failure when its step fails |

C1: a producer with no consumer read as a finished mechanism. C2: 44 repos were present and 4
held different content, because a clone takes the default branch. C3 and C4: a test named
`produces_no_finding` asserted that a finding was written, and was green either way. C5: a
comment said losing state "re-opens the finding, which is the safe direction" while the code did
the opposite. C6: a script printed CLONED after the clone failed, and a quiesce printed success
while the count stayed at ten.

---

## HOW TO RUN IT

Speak the item, then the state. `A3 backup: taken, ~/.claude/settings.json.pre-cutover-...`.
A response that is an intention rather than an observation ("will back up", "should be fine") is
a failed item, not a passed one.

If an item cannot be answered, that is the finding. Stop and say so.

## WHAT THIS DOES NOT COVER

Judgement. A checklist catches the item you skipped, not the plan that was wrong. Question the
frame separately, before the list, not inside it.
