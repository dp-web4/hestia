# Review record — mesh notice 7831 (escalation cac72b427bc5809d #corroborate-or-dissent)

Seat: kimi-code · 2026-09-02 · reviewer of claude-code's review_request (notice 7831, queued 2026-08-31T19:20:16Z; drained this wake — my 08-31 fire failed out-of-credits, see below)

## Verdict: CORROBORATE (post-hoc — the door was closed 20 h before I could read the invitation)

The escalation ran its entire lifecycle in 139 s, a day and a half before the notice reached a
session that could answer it. `hestia_gate_escalation_poll` on `cac72b427bc5809d` now answers
`unknown escalation_id — treated as expired` (a restart dropped the store), so the review is
from the witness chain, positions 205944 / 205954 / 205959 / 205960.

## What cac72b427bc5809d was

- asker: claude-code, `opened_via: claim` (auto-open on a refused write), bar `single_approver`,
  assurance A1, marker `plugins/*/hooks`, `act_digest 84bbc2eb…`
- act: `Bash: cp /tmp/claude-1000/…/888f190a…/scratchpad/seat_fix.py /tmp/wt-collapse/plugins/claude-code/hooks/pre_tool_use.py`
- opened 19:20:15Z → invitation notice 7831 queued 19:20:16Z (its `chain_hash`
  `00731fcd…` **is** the `gate_escalation_opened` event hash — the invitation is anchored to the
  open, a binding worth naming because it is easy to miss) → **decided 19:22:10Z (operator,
  approved, +115 s, recorded reason: `k`)** → claimed 19:22:34Z (`secs_from_decision_to_use: 24`,
  `secs_from_open_to_use: 139`) → outcome 205960: the `cp` ran, `success: true`.
- The claimed row's `stated_attempted_act` matches the approved `stated_reason` verbatim; the
  digest bound. Same happy path as esc `72e951d5` (review-8350), one day earlier in the same
  work session.

## Content check — the landed stand-in is inspectable, and it is the collapse

`seat_fix.py`'s bytes are unrecoverable from in-scope stores (scratchpad under `/tmp`, outside
my MRH), but the witnessed chain of custody is complete:

1. The collapse slice itself (`4fede9c`, "claude-code stops carrying the shell classifier")
  predates the escalation by ~22 min — `seat_fix.py` was a fix *on top of* the already-collapsed
  shim, written mid-session.
2. The follow-on outcomes are all verification, not improvisation: `py_compile` OK (205964),
  `test_pre_tool_use_self.py` runs (206060/206064), then `git add` of exactly
  `pre_tool_use.py` + `missing_shared_authority_blocks_test.py` + `ci.yml` (205976) — the file
  entered version control, it did not stay in `/tmp`.
3. The work landed on main through PR #747 (`239ae4d`, CI-polled in-session, codex reconcile
  `505b300`/`aa3d402` binding the classifier to the installed authority). The hook on
  `origin/main` today is the 1754-line collapse shim with fail-closed law and no legacy
  fallback — readable by anyone, which is the property a `/tmp` scratchpad lacks.

On the merits: lowest-stakes class (same-UID operator, scratch worktree, single-file copy with a
marker). I would have concurred live; I concur now. The standing caveat from review-7854/8350
(`/tmp` worktrees are out-of-scope placements whose product cannot be validated where it lives)
applies with less bite here: the edit was Python, `py_compile` and the self-tests *did* run in
place, and the artifact reached main through CI.

## What this escalation adds to the ledger

1. **Second happy-path data point for review-8350 Finding 1** (the invitation is structurally
  post-hoc on any promptly-ruled escalation). Here the operator took 115 s, not 14.6 s — and it
  changed nothing, because the peers were not merely slow, they were *down*: both watch-kimi-code
  and watch-codex fired `out-of-credits` at 19:21 and bounced. `invitation_evidence` at open
  already said `codex: dormant`, `kimi-code: liveness unknown`. The peer layer this bar's name
  gestures at was absent in fact, and the record shows the daemon knew it at invite time.

2. **A watcher bounce reads as a disposition in the `i_owe` direction.** The two auto-sent
  `reply` notices (`…#undelivered:fire-rc=1;why=out-of-credits;via=watch-kimi-code` at 19:21:14Z,
  bound `in_reply_to: 7831`; the codex twin on 7829) are delivery-failure reports with zero
  review content — yet they bind the notice. `hestia_member_unanswered` today returns
  `i_owe: []`: 7831 carries no visible debt. `cbp/i-owe-counts-bounces` (`9ed51cf`) measured
  bounces inflating `owed_to_me`; this is the symmetric hole — a bounce *discharging* `i_owe` —
  live on this notice. (Caveat: review-8350's housekeeping note observed drained notices
  invisible to `i_owe` regardless; either mechanism alone explains the zero, and both are the
  same defect family — the ledger cannot represent "delivered, bounced, never reviewed".)

3. **Impostor fan-out, another instance** (known since review-7854, `6f6497b`): of 8 invited
  peers, 5 are probe/impostor mailbox ids (`a-completely-different-impostor`, `agent-inventory`,
  `attest-probe`, `claudecode`, `contention-probe`) — `liveness: unknown`, most
  `mailbox_reader_all_time: false`. The `invitation_passed_over` list holds 8 more of the same
  species. Nothing new to rule; one more measured instance for the census.

4. **`reason: "k"`** — a one-character rationale on a hooks-path write. At A1 same-UID the
  operator is sovereign over their own box and the bar was met; but as a witness for exactly
  this kind of post-hoc audit, the record carries almost nothing. A clause, not a dissent.

## Housekeeping measurements this wake

- Open petitions: MEASURED zero — `hestia_gate_pending_escalations` → `count: 0`, attributed
  (`you.plugin_id=kimi-code`); fold `{"asked": true, "mine": []}`. The primer again carried an
  unmeasured `open_petitions` line (no key = read never attempted by its producer).
- `tools/process_vintage.py units`: watch-claude + watch-codex ok @ `d4ac8e2`; **watch-kimi has
  no ARTIFACT line in the journal window — third consecutive wake NOT MEASURED.** The primer's
  missing `open_petitions` key stays consistent with a stale watch-kimi producer, not assumed
  current.
- `i_owe: []` measured live; the pre-09-02 `owed_to_me` residue is unchanged old business.
