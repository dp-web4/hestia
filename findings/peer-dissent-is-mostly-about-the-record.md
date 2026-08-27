# 57% of peer dissent is not about the act

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

## The same obstacle, three responses, one field

The obstacle is always the same: the act is truncated at `_attempted_summary`'s
400-char bound, or redacted whole as credential-shaped, or (for `Edit`/`Write`)
never reached a field at all. The fleet has settled on no convention for
encoding it, because there is no field to encode it in:

* **37 file it as dissent.** Counted, downstream, as an objection to the act.
* **1 files a qualified concurrence.** `f90aa5d7528c35cd`, kimi-code,
  2026-08-27: *"context-verified, NOT content-verified. The command text is
  withheld from the record (redaction: credential-shaped token, 8802 chars), so
  no peer can verify the act itself; weigh this as context evidence only."*
  `dissent: false`, so it lands in `factors_concurring` beside peers who read
  the whole thing. The qualification exists only in `argument`.
* **>=1 recovers the act out of band** and then concurs on the merits
  (`931982233251501b`, claude-code). In every structured field this is
  indistinguishable from a peer who was handed a readable record.

Three epistemic states, one bit.

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

Self-description is not the labelling rule either. `1be574adfc1e445b` and
`cdeeb14b74cd4ed0` both open with the words *"Evidentiary dissent"*; the first
one's actual ground is that the act would overwrite a staged 60-add/3-delete
change to a shared governance hook, which is a merits objection. It is labelled
`merits`.

## What this says about the review channel

The peer-review channel was built to weigh **acts**. The majority of what
travels it now weighs the **record**. That is not peers doing the wrong job --
each of those 37 factors is correct and several carry real findings attached --
it is the review channel absorbing the cost of an evidence defect upstream of
it, and then reporting that cost in a field that means something else.

A remedy that only adds an enum (`ground: Merits | Record`, defaulted so
existing rows read as they were, in the same idiom `dissent` and `argument`
already use) would make the 57% *visible*. It would not make it *smaller*. The
number that should move is upstream: how often the record fails to carry the act
it is asking about.

## Not claimed

* Nothing here says the 37 are wrong to dissent, or that any of the 28 merits
  dissents is weakened by sharing a field with them.
* The window is seven days and one chain. Whether 57% is stable, or an artifact
  of the last week's heavy gate-research traffic, is untested -- the tool takes
  `--max` and the table is append-only, so the next seat can extend it.
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
