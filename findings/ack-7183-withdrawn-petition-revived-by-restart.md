# Wake record: notice 7183 — a withdrawn petition came back to life, and the operator approved it (claude-code, 2026-08-28 ~07:30Z)

One terminal notice: daemon `disposition`, pointer `hestia://escalation/b8228e5250e87356#decided`,
queued 07:19:54Z. Same escalation as notice **7177** (`#withdrawn`, 07:10:07Z) from the previous
wake. One petition, two dispositions, nine minutes apart — and the second one is an operator
**approval** of an ask I had already refused in writing.

## What the chain says (positions from `hestia_query_history`, tail 500)

| pos | UTC | event | what |
|---|---|---|---|
| 197091 | 07:07:34 | `gate_escalation_opened` | `b8228e5`, `for … done` around a `grep`/`gh issue list` — read-only, out-of-grammar → WRITE. No `opened_at` key on the row. |
| 197117 | 07:10:07 | `gate_escalation_withdrawn` | `status: denied`, `decided_via: self_withdrawn`, `bar_met: false`, one factor (`self_withdrawn`, by `claude-code`), reason "self-withdraw: … nothing to claim". |
| 197210 | 07:18:38 | `member_notice` | my bound ack of 7177 (`#withdrawn-received-claude-code`). |
| — | **07:18:14** | *(no chain row)* | **daemon restarted**: `/proc/334658` ctime 00:18:14.696 PDT; `~/.local/bin/hestia` mtime 00:18:14.557 (build-then-restart, 0.14 s apart); running `v0.0.4-485-gc7ec7bd` = `origin/main`. |
| 197224 | 07:19:37 | `operator_session_opened` | dp opened the operator surface 83 s after the restart. |
| 197225 | 07:19:54 | `operator_gate` | `POST /api/operator/gate-escalation`. |
| 197226 | 07:19:54 | `gate_escalation_decided` | **`status: approved`**, `decided_by: operator`, reason `,k`, `bar_met: true`, **`factors_present` = the operator factor ONLY** — the withdrawal factor is gone. **`secs_into_window: 99`.** |

Live poll at 07:22:37Z as `hestia-cli`: `status: approved`, `granted: true`, `permits_write: true`,
`consumed_at: null`, `claim_window_secs_remaining: 437`, `observation_started_claim_window: false`.
A single-use governance grant, live, for an act its asker had abandoned 12 minutes earlier.

`secs_into_window: 99` is the tell. The ask was opened 07:07:34 and ruled 07:19:54 — 740 s — but
the daemon believes 99 s, because the restored row's `opened_at` is the restart time
(07:18:14 + 99 s = 07:19:53). That is #700 exactly (`opened_at: u(d, "opened_at").unwrap_or(now)`;
the writer never emits the key; the fix `830cb2e` is on `claude/opened-at-survives-replay`, not
on `main`).

## Mechanism (source-read, `core/src/server/gate_escalation.rs` at `c7ec7bd`)

`EscalationStore::rehydrate` matches `gate_escalation_opened`, `gate_escalation_decided`,
`gate_escalation_corroborated`, `gate_escalation_claimed`, and `_ => {}`.
**`gate_escalation_withdrawn` is the `_` arm.** So on restart:

1. the `opened` row restores as `Status::Pending` with `opened_at = now` (restart time);
2. the `withdrawn` row is skipped — status stays Pending, `factors` stays empty, `decided_via`
   stays `None`;
3. `pending(now)` lists it, so the operator surface shows a live petition;
4. `decide()` checks `status_at(now)` — Pending — and accepts the approval; the withdrawal factor
   is not there to be overwritten, it was never restored.

`gate_escalation_expired` is also unhandled, but that state is recomputed from `expires_at`
(the open arm skips rows with `expires_at <= now`), so lapse survives replay by the clock.
**Withdrawal is the only terminal state that replay resurrects.** It is also the only one the
member reaches by its own conduct — the withdrawal was the wanted behaviour, and it was the one
the restart un-did.

No test covers it: `replay_restores_rulings_without_re_arming_spent_ones` builds only
`_decided` entries. `git grep gate_escalation_withdrawn -- core/src/server/gate_escalation.rs`
is empty on every remote branch.

## What this cost

- One operator ruling (`,k`) spent on a petition with no asker behind it. The loop-closes-through-
  a-human finding, inverted: here the human closed a loop that had already been closed, because
  the record shown to them had forgotten.
- The chain now reads `opened → withdrawn → approved` and the live store reads `opened → approved`.
  Two records that disagree about whether the asker ever spoke — exactly the shape the replay
  design comment says "this subsystem must never have".
- Any approved-count that folds `b8228e5` reads one approval of a real ask. It is an approval of a
  ghost. Any `bar_met:true` count includes it. Any withdrawal count from the LIVE store (not the
  chain) is short by one, permanently, until the next restart re-derives it — from the chain,
  where the withdrawal still is.
- The grant was live for a claim window (`permits_write: true`) with nobody intending to claim
  it. I did not re-issue the act: it was a read, the marker was a grep operand, and spending a
  grant on it would make the record read "compliant" about an act nobody needed governed.

## Two more rows from this wake

- **The ghost grant lapsed unclaimed.** Poll at 07:30:40Z: `claim_window_secs_remaining: 0`,
  `permits_write: false`, `consumed_at: null`, `status: approved`. Approved-then-unclaimed is the
  modal end and emits no event, so the chain's last word on `b8228e5` is the operator's approval
  of a withdrawn ask. Nothing on any surface will ever say the grant was for nobody.
- **A second withdrawal, live and at risk.** Getting a test build meant applying my worktree diff
  onto the shared main tree; the gate refused `git apply` as an opaque writer and opened
  `6c2034f7df1bc7a5` in my name. The test runs in the worktree, so I self-withdrew it
  (`status: denied`, `decided_via: self_withdrawn`, witness `0485ce21…`). Until this PR is
  deployed, that row is exactly the state this record is about: if the daemon restarts before
  its `expires_at`, `6c2034f7` comes back pending, dated at the restart, and an operator can
  approve a `git apply` nobody will run. A second natural instance, if anyone wants to watch it.

## Fix (this PR; issue #709)

`rehydrate`: `"gate_escalation_decided" | "gate_escalation_withdrawn" =>` — the payloads share a
shape (`status`, `decided_by`, `decided_role`, `decided_via`, `reason`, `factors_present`), so the
existing arm restores both; `decided_via` is now restored from the row too (it was not restored
for decided rows either, so a restarted daemon could not tell `self_withdrawn` from a peer deny).
Test `replay_restores_a_withdrawal_as_terminal_not_pending` pins it from the real payload shape:
after replay the row is `Denied`, absent from `pending()`, carries the withdrawer's factor, and
`decide(approve)` returns `AlreadyDecided(Denied)`.

Not fixed here: `opened_at` (#700, its own PR); and the chain row for the ghost approval stays —
it is a true record of what the operator did, on a surface that lied to them.

## Disposition of 7183

Acked, bound to 7183. The daemon reads no mailbox, so the ack is dead mail on delivery
(precedent 2026-08-27); the binding is what clears the row. Heads-up sent to codex (whose
`review-7169` correctly recorded the withdrawal as the end of this petition — it was, until the
restart) and to kimi-code (who read `b8228e5`'s `stated_reason` at 07:17Z).

## Open petitions

`hestia gate pending --json` (as `hestia-cli`): `count: 0, pending: 0`. The primer carried no
`open_petitions` key; this is the measured zero.
