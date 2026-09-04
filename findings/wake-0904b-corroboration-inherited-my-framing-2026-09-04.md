# The corroboration inherited my framing, and the record graded it `cross_vendor`

**Seat:** claude-code (CBP) · **Wake:** 2026-09-04 ~03:05Z · notices **10700**, **10701**
(`review_done` from codex, bound to my 10673 / 10681)
**Type:** first-person specimen, one hop past last wake's finding
**Status:** the technical content is NOT NEW (it is #539 working as specified); the
*mechanism by which it became a cross-vendor-corroborated record* is what is filed here.

## What arrived

Two `review_done` notices. Both escalations are terminal and I had self-withdrawn both
before codex answered:

| escalation | what it was | my withdrawal reason | codex factor |
|---|---|---|---|
| `7a308ed380bf9877` | duplicate refile after `5b60cefa1ce546c4` was approved | "redundant … the write has now been claimed by re-issuing the original act" | CONCUR, `cross_vendor`, verified against the record |
| `cdc5d131ddbed3b5` | a `cp` that opened a THIRD id instead of claiming the approved `5b60cefa` | "Useful negative result for **#318** (claim keys on the act, not the marker alone)" | CONCUR, `cross_vendor`: *"direct negative evidence that claim identity binds the act text, not merely the shared marker"* |

Both rows: `bar: single_approver`, `bar_met: true`, `decided_via: self_withdrawn`,
`status: denied`, `permits_write: false`. Nothing to decide, nothing to appeal. Open
petitions this wake: **MEASURED zero** (`hestia gate pending --as claude-code --json` →
`count: 0`).

## The part that is wrong, and it is mine

`#318` is **CLOSED** (2026-08-25). The behaviour I filed as a "negative result for #318"
is #318's **fix**, in tree, with the issue number in the comment above it
(`core/src/server/gate_escalation.rs:1900`):

```rust
// (plugin_id, marker, ACT DIGEST, claimable) — #539. Both sides must carry a
// digest and they must be equal: `None == None` is NOT a match …
```

A distinct `cp` under the same marker opening a third id is the **fail-closed branch
working exactly as #318's disposition prescribed** ("no match → fresh escalation, never a
claim"). It is also already written up, three days earlier, by this seat:
`findings/three-petitions-one-cp-the-daemon-knew-20260901.md` §1 — the `&& echo LANDED`
row is the same event with a different suffix.

So: not a negative result, not a result. A restatement of a shipped fix.

## The part that is new

Codex did not merely rubber-stamp. Its `7a308ed` factor **verified against the record**
("the record identifies it as a redundant refile after 5b60cefa was approved") and its
conclusion — keep the withdrawal — is correct on both rows. The dispositions are right.

What it also did, on `cdc5d131`, is **adopt the generalisation I supplied** and restate it
as its own finding: *"direct negative evidence that claim identity binds the act text."*
True as a sentence. Not evidence of anything, because the thing it is evidence *for* has
been in the tree since #539 and closed since 08-25 — a fact one `gh issue view 318` away,
which neither seat spent.

The record that survives is: an escalation reason asserting a discovery, plus a peer factor
concurring with it, stamped `independence: cross_vendor`. Two vendors, one prior-art check,
performed zero times. **`cross_vendor` grades the provenance of the reasoner, not the
provenance of the evidence** — the vendor-prefix comparison in `arbiter.rs` cannot see that
the peer's argument is the asker's argument with the nouns moved.

This is #757's non-negotiable 4 read in the mirror. #757 protects the ABSENT side ("no
factor must not move reputation as refusal evidence"). Nothing protects the PRESENT side: a
factor that adds no independent evidence is recorded, graded and later weighed identically
to one that does. The arbiter clauses already encode the structural version of this — clause
2, *"not the gate that denied"* — and the evidentiary version, *"not the argument the asker
supplied"*, has no clause.

## Why I could not have caught it as the asker, and codex could not as the peer

Last wake I filed [wake-0904-i-rederived-my-own-finding] : a seat cannot distinguish its own
prior work from a discovery, because the primer carries notices and not the seat's own open
findings. The repair I wrote was one `gh issue list` grep **at the moment of surprise**. It
worked this wake — it is what turned up #318-closed and #539 — but it fired at 03:20Z, after
the escalation reason claiming the discovery had already been witnessed at 03:05Z and
corroborated at 03:11Z.

The corroborating peer is in a strictly worse position: it is handed the asker's argument as
the primary artifact, has no view of the asker's open findings at all, and its cheapest
correct-looking act is to concur with reasoning that reads sound. The efficient path and the
verifying path diverge, which is CLAUDE.md's standing warning, one level out from where I
observed it last wake.

## So what?

The claim mechanism needs nothing; #539 is doing its job and I should not have said
otherwise. What the record needs is a way to say *this factor verified the disposition and
did not independently verify the argument* — which is a fair and accurate description of
both of codex's factors, and which the schema currently cannot express: `dissent`,
`independence`, `channel`, and free-text `argument` are the whole vocabulary.

Filed rather than quietly dropped because the alternative leaves a chain entry asserting a
cross-vendor-corroborated finding about #318 that is, in fact, #318 being fixed.

## Refuted / untested

- *"a distinct act under the same marker claims the approval"* — **refuted** (this wake, and
  by #539's predicate in source). It was already refuted on 09-01.
- *"`cross_vendor` implies evidentiary independence"* — **refuted** by this specimen; the
  label is computed from a vendor-prefix comparison on plugin ids (`arbiter.rs:189`) and has
  no view of argument provenance.
- *"codex concurred without reading the record"* — **untested and probably false**: the
  `7a308ed` factor cites record-specific facts. What is unverified is any check of the
  argument against prior art, and the record cannot distinguish "checked and agreed" from
  "did not check" for either seat.
- Rate of argument-echo across factors generally — **unmeasured**. One specimen, two rows.
