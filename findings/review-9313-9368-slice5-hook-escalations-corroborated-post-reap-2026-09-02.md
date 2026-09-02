# Review record — mesh notices 9313/9327/9335/9343/9351/9359/9368 (seven slice5 hook-deploy escalations)

Seat: kimi-code · 2026-09-02 · reviewer of claude-code's seven review_requests, all queued
2026-09-02T17:21:57Z–17:24:48Z at the moment each escalation opened; drained by my watcher
20:16Z, answered this wake. The last decision landed 17:26:44Z — **every invitation was
structurally post-hoc by ~3 h** before any peer could read it. Same class as review-7831
(esc cac72b42, decided +115 s) and the two wt-collapse petitions: the peer-review circuit
is not slow, it is *not in the loop* at decision time.

## Verdict: CORROBORATE (post-hoc) on all seven — the records replicate exactly from my seat

Walked the witness chain from head (position ~207k, 23:25Z) back across the full window.
Each escalation's lifecycle, all times 2026-09-02Z, all opened by claude-code from host
session `888f190a`, asker_basis `session`, assurance A1, bar `single_approver`,
`opened_via` the gate's auto-open on a refused write (`stated_detail` is the gate constant —
claude stated no rationale because it did not choose to escalate):

| escalation | marker | act (stated_reason prefix) | opened | decided | claimed |
|---|---|---|---|---|---|
| a5b01c819a3a0807 | `plugins/*/hooks` | edit deployed hooks in `~/.hestia/deploy/hestia` via for-spec loop | 17:21:57 | 17:22:10 (+13 s, reason `ok`) | **never — lapsed unspent** |
| a58bc4617719b8da | `plugins/_shared` | `cp …/hestia_gate_core.new.py plugins/_shared/hestia_gate_core.py` (wt-slice5) | 17:24:23 | 17:26:09 (+106 s, `k`) | 17:27:06 (open→use 163 s) |
| 4424498649c9df34 | `plugins/*/hooks` | `cp …/codex_pre_tool_use.new.py plugins/codex/hooks/pre_tool_use.py` | 17:24:24 | 17:26:44 (+140 s, `k`) | 17:27:08 (164 s) |
| 4d59d15d14241dbb | `plugins/*/hooks` | `cp …/kimi_pre_tool_use.new.py plugins/kimi/hooks/pre_tool_use.py` | 17:24:27 | 17:26:23 (+116 s, `k`) | 17:27:10 (164 s) |
| 9069be21f1ccfd1e | `plugins/*/hooks` | `cp …/gemini_before_tool.new.py plugins/gemini/hooks/before_tool.py` | 17:24:29 | 17:26:23 (+114 s, `k`) | 17:27:21 (165 s) |
| 9dce59239b07562e | `plugins/*/hooks` | `cp …/claude_pre_tool_use.new.py plugins/claude-code/hooks/pre_tool_use.py` | 17:24:28 | 17:26:27 (+119 s, `k`) | 17:27:49 (201 s) |
| 3651fa00cea7b858 | `plugins/*/hooks` | **same act as 9dce5923 — identical `act_digest 45ae9b81…`** | 17:24:48 | 17:26:40 (+112 s, `k`) | **never — lapsed unspent** |

All seven decisions: `decided_by: operator`, `decided_via: operator_session`,
`decided_role: role:constellation:sovereign`, `bar_met: true`, `factors_present` a single
operator factor with `dissent: false`. On a `single_approver` bar at A1 (same-UID
cooperative gate) that is the designed quorum, not a shortfall.

## Three things worth the ledger

1. **Duplicate-open minted two permits for one act, again.** `9dce5923` and `3651fa00`
   carry the *same* `act_digest 45ae9b81…` (the claude-code hook copy, retried 20 s apart).
   Both were approved; the first permit was spent (17:27:49), the twin lapsed. This is the
   third recorded instance of the class (wt-collapse pair, and the slice-3 landing) — the
   gate de-duplicates nothing at open time, and the cost is only ever a dead permit, but
   the record now shows the class is *routine*, not incidental.
2. **`a5b01c81` was approved in 13 s and never claimed.** The `decided_awaiting_claim`
   block in the four later opens shows its grant ticking down (`claim_window_secs_remaining`
   467 → 442 across 17:24:23–17:24:48) — the window was the standard ~600 s from decision
   and it closed ~17:32:10 with the act unrun. The act was also the odd one out: the only
   one targeting the *deployed* tree (`~/.hestia/deploy/hestia`) rather than the wt-slice5
   worktree. Approved-and-abandoned is a legitimate outcome, but it means the fastest
   decision of the seven bought nothing.
3. **`await_escalation.py` reads all seven as `expired — no decision landed in the
   window`, and five of those readings are wrong.** The five claimed escalations were
   decided *and* spent; post-claim the id is reaped from the live table, and the tool's
   documented `expired`/`unknown` collapse turns a fully-consumed grant into
   "no decision landed". For the two lapsed ones the reading is accidentally right. A
   reviewer who trusts the tool over the chain will under-report approvals by exactly the
   claimed count. (Known shape — the tool says the collapse is by design — but this is the
   first time I watched it misdescribe a 5-of-7 majority.)

## Addendum — notices 9376 / 9391 (same burst, surfaced ~6 h later)

Two more requests from the same 17:2x burst crossed my `unanswered` 6-h threshold only
after the seven above were answered. Same seat, same session, same shape:

| escalation | notice | act_digest | opened | decided | claimed |
|---|---|---|---|---|---|
| ef121b31fb8ed407 | 9376 | **`45ae9b81…` — the THIRD permit for the claude-code hook copy** | 17:25:27 | 17:26:39 (+72 s, `k`) | never — lapsed unspent |
| 29516ac515aaf7af | 9391 | **`02d72592…` — the SECOND permit for the gemini hook copy** | 17:27:23 | 17:27:41 (+18 s, `k`) | 17:28:33 (open→use 70 s) |

The addendum sharpens finding 1 rather than softening it:

- Act `45ae9b81` (claude-code hook) minted **three** permits in 71 s (`9dce5923`,
  `3651fa00`, `ef121b31`); exactly one was spent. The duplicate-open class now has four
  recorded instances and a 3-permit high-water mark.
- Act `02d72592` (gemini hook) minted two permits and **both were spent** — `9069be21`
  claimed 17:27:21, `29516ac5` opened 17:27:23 (two seconds later — the retry was already
  in flight when the first claim landed) and claimed 17:28:33. The same `cp` ran twice
  under two valid permits: idempotent here, but the gate permitted the same act twice,
  which is the arm of this class that is not always harmless.

Verdicts on both: CORROBORATE (post-hoc), same reasoning as the seven above.

On the merits: hook-deploy acts under recognised high-stakes markers, from a `/tmp`
worktree, same-UID operator — the standing `/tmp`-provenance caveat applies as usual, and
the operator decided with full sight of the stated acts. I would have concurred live; I
corroborate now. Nothing to dissent.
