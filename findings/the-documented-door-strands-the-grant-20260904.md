# Using the escalation door correctly is what makes your grant unspendable

**2026-09-04, claude-code on CBP.** Measured over 40,000 chain hops
(2026-08-27T10:31Z .. 2026-09-04T05:13Z), 207 `gate_escalation_opened` rows.
Reader: `tools/stranded_grant_recover.py`.

## The result is a dichotomy, not a rate

| `opened_via` | act recoverable from the chain | n |
|---|---|---|
| `claim` — the gate hook's door | **recoverable** | 201 / 201 |
| `open` — `hestia_gate_escalation_open`, the DOCUMENTED door | **LOST** | 6 / 6 |

No exceptions either way, in eight days.

An approval is bound to an act digest (#539) and `claim()` requires re-issuing the *same*
string. `act_digest` is `sha256(attempted_act.trim())`, and `attempted_act =
act.or(stated_reason)` (handler.rs, `tool_gate_escalation_claim`). The chain's
`gate_escalation_opened` row persists `stated_reason`. **It does not persist `act`. There
is no `act` field on the row at all.**

So:

- The gate hook never sends `act`. Its digest is over the truncated preview it sent as
  `reason` — which IS on the chain. Recoverable.
- `hestia_gate_escalation_open` **requires** `act`, and says why: *"`reason` is your
  rationale and is NOT the act — an approval bound to a rationale can never be claimed, so
  an open without `act` is refused rather than granted-and-unspendable."* Its digest is
  over a string that is written nowhere durable. Unrecoverable.

The door that refuses you *in order to* prevent "granted-and-unspendable" is the door that
produces it, one wake later, for every caller that obeys it.

## Why "one wake later" is the normal case, not an edge

Approved escalations in the window: **147. Median decision latency 72s** (min 8s, max
2338s); 12 were decided more than 600s after the open. A decision arrives at the asker as a
`disposition` notice, and a member drains its mailbox once at the top of a wake. So the
routine path is: open → wake ends → operator approves → *next* wake is told it holds a
grant. By then the asker's context, which is the only place `act` ever existed, is gone.

**77 of the 147 approved grants (52%) were never claimed.**

#667 (merged 2026-09-01) fixed the *clock* for exactly this member — the claim fuse now
burns from observation, so a later wake still gets its full 600s. It did not fix the *act*.
A grant whose clock was rescued and whose act was not is still dead, and it dies looking
like it should have worked.

The cost is already in the record. `7079b9f6d4732751`'s own stated reason reads: *"dp ruled
and already approved this once (`f4a8ea0dd68ec543`, granted by operator, reason 'k'); that
grant expire…"*. Both of those are `opened_via: open`. Both are in the LOST column. The
operator was asked to rule twice on one act because the first grant could not be re-issued.

## The coupling with #627, which is the part that matters

#627 (CLOSED COMPLETED, 2026-08-27) established that `act_digest` binds a **truncated
preview** — 80 of the 207 rows here (38%) still carry a `stated_reason` ending in U+2026,
eight days after that close, so the behaviour is live. #627 reads that as over-breadth:
prefix-colliding commands share a grant.

It is over-breadth. It is also **the only reason any grant on this chain survives its wake.**
Recoverability is 100% precisely where the binding is weak and 0% precisely where it is
strong.

So the obvious remedy for #627 — bind the digest to the real act instead of the preview —
would take cross-wake recoverability from 97% to **zero**, and re-open #667's wound through
a door nobody is watching. Fixing #627 without persisting `act` is a regression for the
asynchronous member both changes exist to protect.

**Remedy, and it is small:** write `act` onto the `gate_escalation_opened` payload beside
`act_digest`. It costs one field. It is a prerequisite for #627, not an alternative to it —
and on its own it makes the documented door usable, which today it is not.

## Demonstrated live, not only counted

`309aebc989e69acb`: opened 04:53:16Z by a wake that ended ~05:02Z, approved by the operator
04:53:28Z (12 seconds), delivered to me as a `disposition` notice on the *next* wake with the
act string gone. I recovered the act from the chain's `stated_reason`, verified
`sha256 == act_digest`, and spent it at **05:11Z — 18 minutes after the asking wake died**
(`claimed: true`, `permits_write: true`, witness `b477e2cf6a6ff2b9`). Then performed the act.

That worked only because it came through the `claim` door. Had I used the documented one, the
same grant would have been unspendable.

## A second, smaller thing found on the way

At 04:56:11Z the daemon told me, via `decided_awaiting_claim` on another open, that
`309aebc989e69acb` had `claim_window_secs_remaining: 437` — a deadline of 05:03:28Z
(`decided_at + 600`). That deadline did not bind. The grant was unobserved, so under #667 its
fuse had not started; my first poll at 05:04:55Z — 87 seconds *past* the advertised expiry —
returned `observation_started_claim_window: true` and a fresh 600s, and the claim succeeded
at 05:11Z.

`decided_awaiting_claim` is the one surface that exists to tell an asker "you hold a grant."
The countdown it prints is neither the decision fuse (which does not bind) nor the observation
fuse (which has not started). An asker reading 437s at 04:56 with a wake ending at 05:02 would
correctly conclude the grant was out of reach, and would be wrong. This is #651's shape — two
distinct facts sharing one integer — one state later, on a surface #651's fix did not touch.
The honest answer for a decided-but-unobserved grant is not a number of seconds to claim in;
it is "look, and then you get 600s."

## What I checked before filing

#539 (open, act binding), #627 (closed, digest binds the preview), #651 (closed,
`claim_window_secs_remaining` lying while pending), #667 (merged, fuse burns from observation),
`tools/act_digest_population.py`, `tools/act_digest_binds_path_not_content.py`,
`tools/escalation_detail_is_a_constant.py`. The identity `act_digest ==
sha256(stated_reason)` is #627's, and I am not re-filing it. What none of them say is that
the identity is load-bearing for recovery, that it holds on exactly one of the two doors, or
that the other door is 0-for-6.
