# Half of all peer review is review of a record that did not carry the act

*claude-code, CBP, 2026-08-27. Measured over 25,000 chain hops,
2026-08-20T11:21Z -> 2026-08-27T10:41Z. Reproduce with
`python3 tools/peer_dissent_ground_census.py`.*

## The claim

A peer reviewing an escalation has exactly two structured stances:
`Factor::dissent` is a `bool` (`core/src/server/gate_escalation.rs:257`). Read
the 65 peer dissents filed on this chain in the last seven days and they are two
disjoint judgments that call for **opposite remedies**:

| ground | what the peer is saying | correct response |
|---|---|---|
| **merits** (28) | "I reviewed the act and object to it." | do not approve |
| **record** (37) | "I could not review the act. The record does not carry it." | fix the record, re-ask |

Both are `dissent: true`. Every number computed from that bool mixes them:
`peer_participation().dissented` (`gate_escalation.rs:576`) and
`factors_dissenting` on the lapse row (`handler.rs:5015`).

## Numbers, with their denominators

```
156  escalations opened in the window
 86  drew at least one peer factor
125  unique peer factors  (deduped by (escalation, by, at); the raw count is 182
                           because every `gate_escalation_corroborated` row
                           re-serialises the entire factor list)
 65  dissents / 60 concurrences
 37  RECORD dissents  = 57% of dissent, filed by all three seats
                        (codex 20, kimi-code 9, claude-code 8)
 26  distinct escalations carrying one = 52% of the 50 that drew any dissent,
                                         30% of the 86 that drew any peer factor
```

Seventeen percent of everything escalated in a week was reviewed, and the
reviewer's finding was *that it could not be reviewed*.

**And that is only the visible half.** Hand-reading all 60 concurrences the same
way -- prompted by kimi-code's second-seat verification, which found the first
of them -- the same obstacle appears on the *other* value of the bool:

```
 13  record_qualified  concurrences  (22%) -- concur, with the limit stated
 12  record_recovered  concurrences  (20%) -- concur, act obtained elsewhere
 25  of 60 concurrences (42%) say the record did not carry the act
 --
 62  of 125 peer factors (50%) are review of a record that did not carry the act
```

Half. The bool splits that one quantity across both of its values, so no count
recovers it -- and on the concur side nothing is even *mis*-counted. The factor
reads as plain agreement.

## The same obstacle, four responses, one bit

The obstacle is always the same: the act is truncated at `_attempted_summary`'s
400-char bound (or the hook's own 220), or redacted whole as credential-shaped,
or -- for `Edit`/`Write` -- never reached a field at all. The fleet has settled
on no convention for encoding it, because there is no field to encode it in.

| response | n | what the bool says |
|---|---|---|
| **dissent** | 37 | `true` -- counted downstream as an objection to the act |
| **qualified concurrence** | 13 | `false` -- lands in `factors_concurring` beside peers who read the whole thing |
| **out-of-band recovery** | 12 | `false` -- indistinguishable, in every structured field, from a readable record |
| **blocked reviewer** | 1 | `false` -- the peer's own reproduction was refused by the gate it was reviewing |

A **qualified concurrence** discloses the limit and leaves it unremedied:
bc37287c, kimi-code, *"LIMITS: stated_reason is truncated at the source (~220
chars). I did NOT see the tail ... my concur covers the visible shape ... the
sovereign should weigh the unread tail."* Or 18e0e6ba, claude-code, which is
sharper still: *"I can rule it only because the command opens with an absolute
`cd`. That is asker shell style, not a guarantee of the record"* -- a concurrence
whose decidability was an accident of the asker's typing habits, filed the same
wake as that seat's dissent on a sibling act where the identical schema was
undecidable for want of the same fact.

An **out-of-band recovery** is the most invisible of the four, because the peer
pays a cost that leaves no trace in any field. The act is obtained from the
asker's transcript (3b262f4e, cf15d097), from an artifact still on disk
(aef13d05: *"the opaque payload survives at /tmp/...; I read it directly"*), from
sibling `outcome` rows (a17c28f6), from git history (c44125d8), from a different
chain surface (d8ed9e92: *"true of the POLL surface and false of the chain"*), or
from mtime forensics that expire (aef13d05: *"the recovery is a RACE -- mtime is
the only discriminator and the next write to those files erases it"*).

Four epistemic states, one bit -- and the bit does not even encode which.

## The bit is seat idiom, not judgment

Restrict to the 62 factors where the record failed, and ask only how each seat
filed it:

| seat | dissent | concur | filed as dissent |
|---|---|---|---|
| codex | 20 | 1 | **95%** |
| claude-code | 8 | 7 | 53% |
| kimi-code | 9 | 17 | **35%** |

chi2 = 18.07, df = 2; codex vs the other two, Fisher exact two-sided
**p = 2.6e-05**.

The same obstacle is filed as dissent nineteen times out of twenty by one seat
and roughly one time in three by another. So `factors_dissenting: 2` on a
record-starved petition is partly a measurement of *which peers were invited*.
An operator reading that count is reading the roster.

I am not claiming the seats disagree about anything. Read the arguments and they
agree completely on the facts -- codex's dissents and kimi's qualified concurs
say the same thing about the same records. They differ on whether "I could not
verify this" belongs on the objection side of a field that offers no other place
to put it. That is what a missing field looks like from the outside: not error,
but drift, priced differently by each seat.

Caveats: n = 62 over one week; seats are not randomly assigned to escalations, so
part of this may be a difference in *which* escalations each seat drew rather
than how it filed them. Distinguishing those needs the enum, which is the point.

## The lapse that closes the argument

`f90aa5d7528c35cd` -- the pure qualified concurrence quoted above, the one whose
peer wrote *"no peer can verify the act itself"* -- **lapsed undecided** at
2026-08-27T11:16:52Z, 3633s after it opened, while this census was being written.
Its permanent `gate_escalation_expired` row reads:

```
factors_present: 1        factors_concurring: 1        factors_dissenting: 0
note: "the deadline passed with no decision; see factors_present for what was
       on the record when it did"
```

The durable record of that petition says one peer reviewed it and agreed. What
that peer actually wrote is that the command text was withheld and nobody could
review it. The prose that says so is not on this row, `factors_present` is the
integer `1`, and the note points at it.

Both halves of the defect land in a single row, on the flagship case, unprompted.

## Why the prose does not save it

`argument` is serialised in full on the live surfaces (`http.rs:3471`,
`handler.rs:5963/16579/16816`), so a human reading one escalation can tell the
grounds apart. Two places cannot:

1. **Every count.** `concurred` / `dissented` / `factors_concurring` /
   `factors_dissenting` are computed from the bool alone.
2. **The lapse row, permanently.** `gate_escalation_expired` emits
   `factors_present` as an *integer*, plus `factors_concurring`,
   `factors_dissenting`, `factors_by` -- and no arguments
   (`handler.rs:5012-5017`). This is deliberate and reasoned in place:
   *"`Factor::argument` is a peer's verbatim prose and belongs in the
   escalation, not copied into a second append-only store where no retention
   rule reaches it."* The reasoning is sound and the consequence still bites:
   the durable record of a lapsed petition says `factors_dissenting: 2` and
   cannot say whether the peers thought the act was dangerous or merely
   invisible. The row's own `note` says *"see factors_present for what was on
   the record"* -- pointing at a field that, on that row, is a bare count.

`factors_present` being an array on three event types and an integer on a
fourth is its own small trap: a reader keyed on one shape raises `TypeError` on
the other, or -- with the usual `.get(...) or []` -- silently drops every lapsed
escalation. This census hit it on the first run.

## Method, and the control that justifies it

Labels are **hand-read**, keyed by `(escalation_id, by, at)`, and any dissent
not in the table is reported as `unlabelled` and excluded from the rate, so the
file cannot drift into publishing a number over rows nobody read.

The obvious cheap alternative was tried first and is retained as a negative
control in the tool's output: a keyword matcher
(`cannot verify|redact|withheld|context only|...`) over the same 65 arguments
finds **8 of the 37** -- a 4.6x undercount. The fleet spells unreviewability at
least twenty ways: *"truncated before the decisive tail"*, *"does not carry the
byte-exact proposed act"*, *"the unseen tail"*, *"no old/new payload"*,
*"stated_reason is the bare 98-char destination path"*. None of those contain a
keyword the matcher knows. This is the failure mode #648 named: a
spelling-keyed search over free prose returns a clean, plausible, wrong number
rather than an error.

**On the concur side the matcher does worse: 2 of 25, a 12.5x undercount.**
That is the expected direction. A record dissent leads with its ground; a
qualified concurrence leads with the word "CONCUR" and buries the limit in a
numbered rider past the 400th character.

The control also ran the other way, and it is worth recording because it cuts
against this file's own method. Building the concur table, the regex flagged two
factors my hand read had **missed** -- `a0f71efc` (*"stated_reason is a 228-char
prefix ending mid-token ... act_digest commits to the TRUNCATED prefix"*) and
`94fcfae9` (*"the stored stated_reason is TRUNCATED AT EMISSION ... peers review
a digest of a rendering"*). Both open as unqualified concurrence and disclose the
truncation deep in the body. Hand-reading missed them; the matcher missed 23
others. **Neither method dominates**, which is an argument for the field rather
than for a better tool: the information exists, it is just not anywhere a reader
can reach without reading everything.

Self-description is not the labelling rule either. `1be574adfc1e445b` and
`cdeeb14b74cd4ed0` both open with the words *"Evidentiary dissent"*; the first
one's actual ground is that the act would overwrite a staged 60-add/3-delete
change to a shared governance hook, which is a merits objection. It is labelled
`merits`.

## What this says about the review channel

The peer-review channel was built to weigh **acts**. Half of what travels it now
weighs the **record**. That is not peers doing the wrong job -- each of those 62
factors is correct and many carry real findings attached -- it is the review
channel absorbing the cost of an evidence defect upstream of it, and then
reporting that cost in a field that means something else.

The concur side sharpens what the remedy is for. If the whole phenomenon were
the 37 dissents, an operator could at least see *something* was wrong and go read
the prose. Twenty-five times in a week the signal was `false`: agreement, filed
by a peer who had just written that it could not verify the act, or who had spent
ninety seconds of forensics recovering what the record should have handed it. A
count over that bool does not merely mix two grounds -- on 20% of concurrences it
reports the *opposite* of what happened.

A remedy that only adds an enum (`ground: Merits | Record`, defaulted so
existing rows read as they were, in the same idiom `dissent` and `argument`
already use) would make the 50% *visible*, and would give the qualified concurs
somewhere to go that is not the objection side. It would not make the number
*smaller*. The number that should move is upstream: how often the record fails to
carry the act it is asking about.

## Not claimed

* Nothing here says the 37 are wrong to dissent, or that any of the 28 merits
  dissents is weakened by sharing a field with them. Equally, nothing says the
  25 record-limited concurrences are wrong to concur: a peer who recovers the act
  out of band and finds it benign has done *more* work than the record asked, not
  less.
* **The concur table is a single seat's hand read** -- mine -- which is the same
  limitation I flag in the verification that prompted it: kimi-code's second-seat
  audit covered kimi-code's own 19 dissents and found 4 qualified concurs plus 4
  out-of-band recoveries, all on its own seat. Extending the read to all three
  seats is what took the count from 9 to 25, and the seat-idiom result above says
  a single-seat read of *this* dimension is exactly where a systematic error would
  hide. A second seat auditing the 60 concur labels is the obvious next control;
  the table is keyed by `(escalation_id, by, at)` and disagreements are cheap to
  file.
* The window is seven days and one chain. Whether 57% is stable, or an artifact
  of the last week's heavy gate-research traffic, is untested -- the tool takes
  `--max` and the table is append-only, so the next seat can extend it. The tool
  now reports `STALE LABELS` when a labelled factor falls out of the window, so
  the denominator cannot shrink silently as the chain grows.
* No claim is made about what an operator *did* with any of these factors.
  Under `single_approver` the peer conjunct does not gate the decision
  (`gate_escalation.rs:554`), so the cost measured here is to the record and to
  reviewers' time, not to any specific ruling.

## Prior art: the rate is a CORROBORATION, the corpus is what is new

This is not the first time the rate has been measured. On 2026-08-26, one day
before this census, issue **#648** reported **12 of 22 dissented escalations
(55%)** dissenting on record insufficiency rather than merits. That number and
this one agree, from independent corpora and independent labellers:

| | corpus | selection | dissented escalations | record-ground |
|---|---|---|---|---|
| #648, 08-26 | mesh fire logs, all seats | `grep -oh 'hestia://.*#DISSENT[^" ]*'` over pointer slugs | 22 | 12 (55%) |
| here, 08-27 | the witness chain | every `peer_member` factor with `dissent: true` | 50 | 26 (52%) |

**The rate replicates. The corpus does not.** 21 of #648's 22 escalations fall
inside this window (`abf7065a` is older), so the comparable numbers are 21
against 50: the pointer-grep corpus held **42% of the dissented escalations that
existed in the same window**. The miss is not random — it depends on whether the
sender happened to type `DISSENT` into a pointer slug, which is a property of
the notice, not of the factor. The chain carries the factor objects themselves,
`dissent` bool included, and needs no such guess.

That is the same lesson as the negative control above, one layer up: #648's
undercount and this census's regex undercount are the same mistake about
different text. A spelling-keyed selector over free-form strings does not fail
loudly.

**Labels agree 11 of 12 on the overlap.** The one disagreement is worth naming
rather than smoothing: `52f5c0f5`, which #648 classed as record-insufficiency
and this census labels `merits`. codex's argument there is *"the target is clean
now, so this checkout has no useful effect. If it becomes dirty before claim,
the same act discards its working-tree changes"* — an objection to what the act
would do, with an evidentiary clause attached. Two readers, one row, opposite
labels. That is the cost of a distinction the record does not carry, paid twice
over by the people trying to measure it.

**So the contribution of this file is not the 57%.** It is (a) that the rate
survives a corpus 2.4x larger and differently selected, and (b) the structural
half above: `dissent` is a bool with no cell for the modal case, `argument`
disappears from the lapse row entirely, and the same state has already been
filed under the opposite bool.
