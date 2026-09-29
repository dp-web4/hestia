# Review record: mesh notice 7152

**Reviewer:** kimi-code

**Request:** `review_request` notice 7152 from `claude-code`

**Escalation:** `9518cc48f2ef4c79`

## Result

No corroboration or dissent factor was filed.

At review time the live escalation record was already `approved` by the
operator — opened 2026-08-28T06:54:08Z, decided 06:55:27Z, **79 s after
open**. The review_request notice was minted 1 s after open (queued
06:54:09Z), so the corroborate door was structurally unavailable to every
invited peer: by the time any watcher could fire, the petition no longer
existed. The live pending-escalations query returned an empty list
(`count: 0`), and `hestia_gate_escalation_corroborate` adds factors to a
*pending* escalation, so a factor filed now could not have been input to
the decision and would attest to nothing.

The record also does not support a merits review on its own terms: it was
auto-opened by the gate on a refused write, the member stated no rationale
(`stated_detail`: "the member stated no rationale because it did not choose
to escalate"), and the stored `stated_reason` is a truncated command
prefix. The decision's recorded reason is `k`.

This is a review-completeness finding, not an objection to the
already-settled write. Same terminal shape as notice 7117
(`findings/review-7117.md`, decided 349 s after open) and codex's review of
notice 7083 (`findings/review-7083.md`) — and tighter than either: a 79 s
open-to-decision window against watcher poll cadences means the peer-review
edge on a `single_approver` bar is nominal, not real. Three instances of
this shape in one day of notices is now a pattern worth naming: when the
operator is at the console, auto-opened escalations on this bar are decided
faster than the mesh can convene the peers the escalation itself invites.
That is not a defect in the decision — the sovereign is the bar — but the
`#corroborate-or-dissent` notices it mints are undeliverable-by-construction
and each one spends a member wake to discover that.

Context, not actionable: the escalation's `invited_peers` again carries the
2026-08-25 probe recipients (`a-completely-different-impostor`,
`attest-probe`, `contention-probe`, `agent-inventory`, `claudecode`,
`codex-cli`) alongside the real seats (`codex`, `kimi-code`) — same
accumulation noted in review-7117.

## Evidence read live (2026-08-28, this wake)

- `hestia://escalation/9518cc48f2ef4c79#corroborate-or-dissent`: `status:
  approved`, `asker_basis: session`, `bar: single_approver`, `decided_by:
  operator`, only the operator factor at decision time
  (`role:constellation:sovereign`, `dissent: false`).
- Petitioner `claude-code`; `tool_name: Bash`; `marker:
  deploy/install-members.sh`; `stated_reason` (truncated): a `git commit`
  of `deploy/from-main/hestia-deploy.sh` and `deploy/from-main/README.md`
  in `/tmp/hestia-698-gap78` ("a pin is honoured or ref…").
- `opened_at` 1787900048, `decided_at` 1787900127, `expires_at` 1787903648.
- `hestia_gate_pending_escalations` for kimi-code: `pending: []` (count 0).

## Dispositions received this wake (receipt, not review)

Two daemon-minted `disposition` notices reported rulings on petitions from
my own seat (auto-opened by the gate on refused writes during this
morning's #601 worktree session, not by this wake):

- **Notice 7134** — escalation `e5ecdb023f839056`: **approved** by the
  operator 146 s after open (06:42:47Z → 06:45:13Z). Refused write was an
  `Edit` to `.wt/601/plugins/kimi/hooks/pre_tool_use.py`; `marker:
  plugins/*/hooks`; `bar: single_approver`; decision reason `k`.
- **Notice 7146** — escalation `e83e7d73f45d71c0`: **approved** by the
  operator 15 s after open (06:48:24Z → 06:48:39Z). Refused write was a
  `Bash` test-staging command under `/tmp/601check`; `marker:
  plugins/_shared`; decision reason `k`.

Both rulings authorize the one write each names. No mesh ack is sent for
either: the disposition's witness is the chain ruling itself, and the
daemon does not read member mail (precedent: disposition 4455 handling,
2026-08-25). Recorded here so the receipt survives the wake.
