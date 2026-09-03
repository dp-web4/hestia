# "Decided = corroborable forever" has a bound — but it is NOT the restart (see correction)

> **CORRECTED 2026-09-03 by `findings/wake-0903-reap-not-restart-evicts-the-decided-row.md`
> (PR #867). The title of this file is wrong and the filename preserves the error.**
>
> The eviction door is `reap`, called unconditionally by `EscalationStore::open()`
> (`gate_escalation.rs:1430`), not `rehydrate()` at a restart. Every one of the eleven rows
> below had already been swept by an unrelated open **13.9–22.8 hours before** the
> 09-02T04:21:49Z restart this document blames. The restart path is real but was never
> reached here.
>
> What survives: the observation (eleven verified factors could not be filed), the
> `rehydrate()` reading, the act table, and the #797 refinement. What does not: the causal
> attribution and the headline rule. The corrected rule is
> `min(first open after expires_at+3600, first restart after expires_at)`, and because reap
> runs only inside `open()`, the answerable window is a function of unrelated fleet traffic —
> median 3.2h past the ruling against a 2.0h nominal, max 30.7h.
>
> Prompted by codex's correction on `findings/review-7597.md`. I reasoned from the poll's
> `note` for an unknown id, which says *"a restart drops the store"*; that sentence names the
> rare door and is why two seats independently reached the same wrong mechanism.


Wake 2026-09-02 ~04:15Z (claude-code, CBP). Eleven review_requests from codex
(notices 7902–8029, queued 2026-09-01 00:17–05:42Z), each a
`hestia://escalation/<id>#corroborate-or-dissent` pointer. All eleven acts were
verified (below) and eleven concur factors were written. **Zero could be filed.**

## The refusal, and the mechanism

Every `hestia_gate_escalation_corroborate` call answered:

    no such escalation — unknown ids are denies, not retries

The rows exist — all eleven were recovered from the witness chain (opened,
decided, and for six of them claimed). The refusing guard is not the corroborate
door's own timing rule; it is what the door can *see*:

1. `resources/read` on `hestia://escalation/<id>` searches **1000 entries** back
   (`searched:1000, complete:false` at chain length 210,921). The chain grew past
   these rows within hours.
2. The live store is rebuilt at startup by `rehydrate()`
   (`core/src/server/gate_escalation.rs`, `gate_escalation_opened` arm), which
   **skips any open whose `expires_at <= now`** — "terminal-by-time entries are
   not worth restoring: they cannot be ruled." The `gate_escalation_decided`
   replay arm only mutates rows already restored by the opened arm, so a decided
   row past expiry is not restored *decided* — it is not restored at all.
3. The daemon on this box restarted 2026-09-02 04:21:49Z. All eleven rows expired
   ~09-01 06:00Z at the latest. After the restart, `by_id` has no entry, and the
   corroborate door answers `DecideError::Unknown`.

## Why this bounds a pinned theorem instead of contradicting it

`fb_peer_cannot_is_a_belief_until_the_door_is_called` (#736) proved that on a
**running** store, `status_at` reaches `Expired` from `Pending` alone, so the
expiry guard is unreachable on a decided row — decided rows take factors
indefinitely, and the tool description now says so at the door. That theorem is
true of the store it was proved on. `rehydrate()` is a second door the theorem
never called: it evicts by `expires_at` alone, decided or not. So the honest
statement is:

> A decided escalation is corroborable until the first daemon **restart** after
> its `expires_at`. After that the door denies with `Unknown` — a third refusal
> class, distinct from `Expired` and `AlreadyDecided`, and the one class the
> "file it anyway, the ruling is not the deadline" guidance cannot survive.

Consequences worth measuring:

- Peer review latency runs 736s median past the ruling, and post-terminal filing
  is the norm (130 of 196 factors). Every one of those beat expiry+restart by
  luck of uptime. An invitation's answerable-window is a function of **daemon
  uptime**, a variable unrelated to either party's conduct.
- The `rehydrate` comment's rationale ("they cannot be ruled") is true for
  pending rows and false as a totality: a decided row past expiry can still take
  a *factor* — the corroborate door's own contract says approved/denied rows
  accept evidence indefinitely. The skip forecloses that contract silently.
- A watcher-restart also re-fires retained primers, so the same restart that
  evicted the rows is what delivered the stale wake asking about them.

Remedy direction (not implemented here): the `_opened` replay arm could restore
terminal-by-time rows in a decided-only capacity (never enter the pending queue,
never claimable), or the corroborate door could fall through to a bounded chain
lookup on `Unknown`. Either keeps the invitation answerable without re-arming
anything.

## The eleven acts, verified against landed artifacts

Read as full chain rows via `chain_walk` (the wrapped walker; 4,080 hops).
8 of 11 `stated_reason`s are capped at 412 chars ending `…[truncated]` (codex's
400 cap); their content was recovered from the target worktrees' commits.
All eleven were operator-approved (`k`). All eleven concur — the table below is
the substance of the withheld factors (the probe scripts are seat-local under
`tools/claude_wake_0902e_*.py`, gitignored per #493).

| escalation | act (recovered) | claimed? | landed as |
|---|---|---|---|
| 8aa509e633f331ef | claude hook cutover edit, iteration 1 of 3 | no | superseded by 9001eba5/e8258534; final in `505b300` (00:52:30Z) |
| 9001eba5f0615278 | same series, iteration 2 | yes | `505b300` |
| e8258534bb8bc8d8 | same series, iteration 3 | yes | `505b300`, 3 min after grant |
| 94134d2993ac8aca | ci_discovery bare battery (FULL act, 351ch) | no | read-only; marker-in-compound FP class |
| ca7d50b5062e81b9 | ci_discovery hooks battery (FULL, 392ch) | no | same class |
| 8ce65aa40f5d8d30 | ci battery (FULL, 348ch) | yes | ran |
| d58d1e33adf97f88 | installer: drop DRY_RUN preview loop | no | reworked into `39a3fb9` (~9h later) |
| 160e09ff4bad281c | codex hook ENGINE AUTHORITY block | yes | `2bb2c82` (05:43Z) |
| 02719168736a54a1 | decision_sabotage_test env edit | yes | `2bb2c82` |
| 20e5084449b3c719 | second sabotage-test hunk | yes | `2bb2c82`, 2 min after grant |
| b6d7c2266bba8b11 | installer ORDER comment edit | no | recast as blocker test `831d760` + comments in `39a3fb9` |

## Refinement of the PR #797 discriminator

PR #797 (09-02) proposed act CLASS as a chain-visible discriminator for
unclaimed grants: 2/2 unclaimed were marker-FP read loops, 5/5 writes were
consumed. This batch splits differently: **5 unclaimed = 2 reads + 3 writes**,
and each unclaimed write is a *supersession* — the same edit re-issued and
claimed under a later petition (8aa509e6), or the same concern landed reworked
in a later commit (d58d1e33, b6d7c226). So act class predicts less than the
mechanism behind it: writes go unclaimed too, whenever iteration outruns the
claim. The chain sees the supersession only as sibling petitions; the commit
graph is what closes the loop. "Writes are consumed" was a property of that
sample, not of the class.

## Also measured this wake

- Open petitions: `{"asked": true, "mine": []}` — a measured zero (the primer
  carried no `open_petitions` key; its producer predates the fold).
- `peek`: mailbox empty; the primer (notices dated 08-26) was a retained-primer
  re-fire at the 04:21Z watcher restart. The real work list came from
  `unanswered 0`: 240 rows, 186 bounces (77.5%), 54 genuine, of which the live
  items were codex's 11 corroborate invitations + review_request 8576 (PR #796,
  reviewed: https://github.com/dp-web4/hestia/pull/796#issuecomment-5504444429).
