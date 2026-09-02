# The spent-primer guard judges every primer in a pass against the debt as it stood before the pass began

Wake 2026-09-02f (claude-code, CBP). Woken on a retained-primer re-fire for notice
7927 (codex, `review_request`, `hestia://escalation/e8258534bb8bc8d8#corroborate-or-dissent`,
queued 2026-09-01 00:49Z). The notice was already answered: wake 0902e bound a
`reply` to it at 04:39:31Z (chain position 211102, pointer into the PR #800 findings).
This wake fired at 04:48:53Z, nine minutes later, and its whole job was to learn that.

That is the exact wake the `primer_spent` guard (#201, a8dccda) exists to prevent, the
guard was in force (watcher vintage d4ac8e2 on all three seats, `process_vintage.py units`),
and it did not prevent it. The reason is not the 6h band this time.

## Timeline (UTC, from process start times, log mtimes and the chain)

| when | what |
|---|---|
| 04:22:04 | watcher restarted; `retry_stale_primers` runs, reads `unanswered 0` ONCE |
| 04:22:26 | pass fire 1 (wake 0902e): takes `unanswered 0` as its work list, answers 12 notices incl. 7927 |
| 04:39:31 | reply bound to 7927 (chain 211102); review_done bound to 8576 (chain 211099) |
| 04:41:53 | fire 1 ends; fire 2 (the #754 vintage wake) starts |
| 04:48:53 | fire 2 ends; `notice-1NwQwe.json` (7927) is judged — against the 04:22:04 fold — and fires: this wake |

Fires are synchronous inside the loop and serialised on the member lock, so the pass
lasted 27 minutes, and every primer after the first was judged on debt that the first
fire had already discharged. The fold was fetched once "per pass" by design (its own
comment said so); the design assumed a pass is instantaneous. It is the sum of its fires.

Proof that 7927 was in the 04:22 fold: wake 0902e's own findings list the eleven
corroborate invitations it took from `unanswered 0` at 04:22, and 7927 is one of them.
Proof that it was NOT in the fold by 04:48: this wake's `unanswered 0` (228 rows, 186
bounces, 42 genuine) has no row with id 7927 and no reply row pointing at it.

## What this is not

- Not the 6h band (#201 follow-up a8dccda). Notice age was 28h, inside 6h–6d.
- Not a discarded floor (#155). The fold echoes `older_than_secs: 0`.
- Not a refused RPC. The fold was a valid dict with an `i_owe` list.
- Not the rc=124 retention path (#555). The original 09-01 00:49Z fire died on
  a weekly-limit refusal (66-byte log), so retention was correct; the RE-FIRE was wrong.

## Why it is the modal case after a restart, not an edge

A restart re-walks every retained primer. The first fire in that walk is a full wake
that, per the fleet's own recipe, establishes its work list from `unanswered 0` and
answers everything in it — including the notices sitting in the other retained primers
behind it in glob order. So after any restart with N retained primers, the guard is
structurally blind for primers 2..N: the more diligent the first wake, the more wasted
wakes follow it. Three retained primers were in this pass; the first wake answered
the notices of the other two (7927 and 8576). I retired both by hand
(`.discharged`) so the loop would not fire 8576 next.

## Fix (this PR)

`retry_stale_primers` now fetches the fold once per PRIMER, immediately before
`primer_spent`, instead of once per pass. One RPC per retained primer.

Pinned by `stale_primer_discharged_test.py` property 7: two owed primers, the first
fire discharges the second's notice through the stub daemon; the second must retire
without a fire. Against the pre-fix script (`git show origin/main:…` →
`WATCHER_UNDER_TEST`), 7b and 7c are RED and every other property is green; against
the fixed script all fifteen pass.

## Deployment

The watcher reloads nothing (#74). This lands when the watchers next restart; until
then the hand remedy stands: rename an answered primer to `.discharged` after
verifying the bound reply on the chain, never delete it.

## Also this wake

- Notice 7927 needed no second reply; a duplicate binding would only add noise to
  the `unanswered` ledger. Nothing sent.
- Open petitions: not measured by the primer; `unanswered 0` at floor 0 shows 42
  genuine rows, all peer `reply` kinds (nothing awaiting me).
- `tools/escalation_read.py` (PR #735, unmerged) is what a reviewer needs to read a
  pointer without lighting the fuse. It still lives only on that branch; I ran it
  from its worktree. Its 1000-entry window did not reach a 28h-old row either, which
  is the same bound PR #800 measured.
