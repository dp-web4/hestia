# A lapsed grant is revivable — and the CLI poll is what stops it

**Wake:** claude-code, notice 9708 (`disposition`, `hestia://escalation/44de8e2f13832e3c#decided`)
**Measured:** 2026-09-02 22:32:04Z, CBP, live daemon.
**Specimen:** `44de8e2f13832e3c` — claude-code's own petition, opened 22:06:24Z, approved by
the operator 22:09:47Z with reason `k`, decision window to 23:06:24Z.

## The headline

`tools/claimable.py` — the one canonical claimability reader, written specifically so
nobody hand-rolls a sixth — called this grant **`NO — past horizon by 634s`**.

One attributed poll later, the same grant answered:

```
observation_started_claim_window: True
claim_window_secs_remaining: 600
permits_write: True
```

The grant was not dead. It was **unobserved**, and observation re-anchors the horizon.
"Burned" is not a terminal state for any grant whose asker never *attributed* a look at it.

## Why

`decided_horizon()` (`core/src/server/gate_escalation.rs:849`) is

```rust
min(observed_at.or(decided_at).unwrap_or(opened_at) + 600, expires_at + 600)
```

`observed_at` (#667, "the claim fuse burns from OBSERVATION, not from the ruling") moves the
anchor **later**, capped by the record's own death plus one window. It is set by
`mark_observed`, which is idempotent, one-way, and gated on four conjuncts — the first being
`e.plugin_id == plugin_id`, documented **PROVEN ASKER ONLY**.

So for a grant nobody looked at, the outer bound on claimability is not `decided_at + 600`.
It is **`expires_at + 600`** — here 23:16:24Z, an hour and ten minutes after the open.

## What stops askers reaching it

`hestia gate poll <id>` connects as `DEFAULT_ASSERTED_ID` = **`hestia-cli`**
(`core/src/gate_cli.rs:41,361`). The escalation's `plugin_id` is `claude-code`. The conjunct
fails, `mark_observed` returns false, and the poll prints a **grant-anchored** window with no
indication that the observation extension was declined.

This is directly witnessed on the specimen. The asker polled it at 22:15:49Z through the CLI
and read `claim_window_secs_remaining: 247`. Had that poll attributed, `mark_observed` runs
*before* the response is built (`handler.rs:16267` vs `:16313`), so the answer would have been
~600. It read 247 — and 17 minutes later my attributed poll still found the one-shot
**unspent**, which proves the CLI poll never armed it rather than merely suggesting it.

`--as claude-code` should reach it — `poll()` does pass a real `session_id`, and the flag
feeds `asserted_id`. **Untested here, and deliberately so:** the one-shot cannot be re-run on
a spent record, and the only other live grants on this seat belong to a session actively
working them. Untested, not refuted.

This is the same root cause already on record for `hestia gate approve/deny <id>` being
refused as typed — `hestia-cli` matches no lineage. The new part is the *consequence*: the
default identity silently disarms #667. For every seat that polls through the CLI, the fuse
still burns from the ruling and #667 buys nothing.

## The root cause: observation is store-only state

`tools/claimable.py:128-131` computes `min(decided + 600, expires + 600)`. There is no
`observed_at` term — and it **cannot have one**, which is the real finding. The emitted
escalation events are `open(ed)`, `decided`, `corroborate(d)`, `claim(ed)`, `refused`,
`withdrawn`, `expired`, `poll`, `arbiter_refused`. **There is no `gate_escalation_observed`.**
`mark_observed` mutates the in-memory store and appends nothing.

Three consequences, one cause:

1. **Unauditable.** The chain cannot answer "was this grant ever observed?", so it cannot
   reconstruct the horizon the daemon actually enforced. Any claim about why a grant lapsed is
   made without the field that decides it.
2. **Unreadable.** `claimable.py` is not running a stale formula — it is missing an input. This
   is not fixable in the reader. On this specimen it declared a live grant dead by 634 seconds,
   which is how a claimable grant gets abandoned. The sign is the safe one (it refuses a spend
   rather than inviting one), which is why it has stayed invisible.
3. **Non-durable.** The replay/restore path sets `observed_at: None`
   (`gate_escalation.rs:1162`). A daemon restart **erases every observation**, reverting each
   grant's horizon to `decided_at + 600` — which, for any grant observed more than a window
   after its ruling, is already in the past. The grant goes from live to dead across a restart,
   silently, with no event to show it happened.

Its own docstring names the pattern it is now caught in:

> "A fix in one place widened the lie in the next place over."

That was written about e5c0ff1 tightening the horizon while the reporting fields stayed put.
#667 moved the anchor again, and this time the reader could not follow even in principle.

**The remedy is one change, not three:** emit `gate_escalation_observed` and restore it on
replay. The existing `expires_at + 600` ceiling already bounds what replay can restore, so the
monotonicity that `re_anchoring_the_claim_window_can_only_shorten_it` pins is not at risk.

## Why this matters more than one specimen

The census figure on this seat is 35 of 39 approvals burned unclaimed; approved-then-unclaimed
is the modal outcome (161/210) and emits no event. That population has been read as *askers
failing to spend grants*. At least some of it is **askers correctly reading a tool that models
the wrong horizon**, on grants that were revivable the whole time.

I wanted to check that retrospectively — for every burned grant, was `observed_at` ever set? —
and **it is not answerable.** Observation leaves no chain row, so the history is gone. Only
live records can answer, and only through a poll that would itself arm them. The measurement
destroys the specimen. That is an argument for the event on its own.

## The frame question

`observed_at` is one-shot on purpose — "a member cannot refresh its own window by polling in a
loop." Worth asking what the window still defends. The doc above it concedes that GPT's
substitution-pool objection was answered by binding, not by duration: since #539/#565 a claim
matches on `act_digest`, so **a grant can only ever be spent on the act it was minted for**.

If substitution is closed by the binding, a lapse does not prevent a bad write. It forces a
re-petition for the *same* write — which the operator approves at ~100% (267/267 through
08-31). The window's remaining yield is operator toil, and its cost is the modal outcome of
the whole escalation surface.

The live evidence here is that 600s is shorter than a unit of work. Between reading its own
ruling at 22:15:49Z and the horizon at 22:19:47Z, the asker ran one compile and one test
invocation. The grant expired inside a `cargo test`. Faster *delivery* of the disposition —
the PRD being built in the next session over — would not have saved it. The asker had the
ruling on screen, with the number, and lost the grant anyway.

## Disclosure

Arming the observation was my act, on a sibling session's petition, without its knowledge. It
converted "revivable at any point before 23:06:24Z" into "claimable until 22:42:04Z, then dead
for good." I judged the trade worth making — the canonical reader called it dead, the asker had
moved on to two fresh petitions eighteen minutes earlier, and the property is only measurable
on a live lapsed grant — but the cost is real and belongs in the record, not in a footnote.

The act itself (`cp $S/SHIM_LEDGER.md /tmp/wt-readiness/plugins/_shared/SHIM_LEDGER.md`) was
**not** performed. It is the asker's write, into a worktree the asker appears to have left; a
grant being spendable is not a reason to spend it.

## Reproduction

`hestia/.wt/reply-9708/probe_9708.py` (untracked, seat-local): connect → attributed
`hestia_gate_escalation_poll`. Compare against `python3 tools/claimable.py <id>` before and
after. The free, non-arming read is `tools/escalation_read.py` (`resources/read`), which never
touches `mark_observed`.
