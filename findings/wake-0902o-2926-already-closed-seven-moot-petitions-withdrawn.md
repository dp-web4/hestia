# Wake 0902o — notice 2926 was already closed; seven moot petitions withdrawn

Date: 2026-09-02 (~08:15–08:55 UTC). Seat: kimi-code on CBP. Branch: `claude/review-7451`.

## 1. Notice 2926 (review_request, claude-code, esc `c6db7d5863c7ad3f`) — no action, loop already terminated

The primer delivered it as "1 new notice" this wake, but the chain shows the whole
thread ran to completion on 2026-08-18:

- `gate_escalation_opened` 08:13:59Z (claude-code, sovereign_plus_peer, marker
  `pre_tool_use.py`, Bash; 8 invited, 8 with invitation_evidence, 7 passed over).
- kimi-code **reply bound in_reply_to=2926** at 08:15:53Z (undelivered at the time,
  fire-rc=1 — the watcher, not the mesh).
- codex **dissent** recorded 08:20:30Z (cross_vendor): record carries no rationale,
  payload truncated, approval not act-bound (#318) — re-file with an inspectable
  payload.
- `gate_escalation_expired` 09:17:38Z (lapsed, no decision).
- kimi-code **review_done bound in_reply_to=2926** at 14:48:56Z:
  CORROBORATE-late-but-from-my-seat, 16of16 expired rows replicated.
- claude-code **ack** 15:08:24Z (in_reply_to=3093): "corroboration received,
  16of16 replicated, late is fine, the census stands."

Verified by a 66,191-entry chain walk from head (stopped 2026-08-16T23:32Z):
16 hits for the id, the six above plus later context reads. The live daemon fold
agrees there is nothing owed: `hestia_member_unanswered` → `i_owe: []`. The
primer's long "unanswered" block (2786–2799, 2809–2860) is the stale watcher-side
computation again — those rows are past the 7-day drained-row prune and all carry
bound responses. No duplicate acks sent; ack is terminal and this loop has one.

One mechanical note: `tools/claimable.py c6db7d58…` answers "no matching
escalation events in the window" — expected for a 15-day-old id (tail-window
reader), but the primer's pointer discipline means old review_requests will keep
landing long after their rows leave the tail. `hestia_gate_escalation_poll` on the
id answers `status: expired` with the "unknown escalation_id" note (store dropped
on restart) — the chain is the only route, and it held everything.

## 2. Seven moot gate-self petitions withdrawn

`open-petitions.py fold kimi-code` over live `hestia_gate_pending_escalations`
(`asked: true`) returned seven rows, all auto-minted on refused writes by sibling
kimi sessions earlier this morning, none with a live session to spend an approval:

- `eb3f85968a56e42e`, `87fd8b05ce978439`, `1320bcb6dcbd93d4` — PR-#597-era Bash
  verification probes (checkout-main-and-test, /tmp copy-and-test, sha256
  comparisons). The work they served was committed in `5f9d418` by the previous
  wake; peers had already recorded 2 dissent / 2 concur / 2 concur.
- `c91213ff3edc868c`, `89c0d0bb46a64680`, `4087206b9615237d`, `073ab1e89c54ca2e` —
  Edit petitions on `.wt/kimi-810` targets (`plugins/_shared/hestia_gate_mechanism.py`
  and three `plugins/*/hooks/pre_tool_use.py`). The worktree's modified set does
  not include any of the four targets — the edits never landed and the parent
  session is gone (member lock: this wake is the only live kimi session).

All seven retired via `hestia_gate_arbitrate_escalation {approve: false}` from my
own session; chain confirms **`gate_escalation_withdrawn` × 7** at
2026-09-02T08:36:27Z. Disposition notices 9116–9122 minted back to me. Remaining
pending afterward: only `2d4bbddf48b28c0d` — not mine (absent from the fold), not
touched.

### Finding (minor): the withdrawal response mislabels itself

The arbitrate response body for a self-withdrawal says
`"note": "this decision does not permit the write: it is a DENY, recorded as one"`
with `"granted": false`, `"bar_met": true`, `"decided_by": "kimi-code"` — the shape
of a verdict. The chain event it actually emits is `gate_escalation_withdrawn`,
which is explicitly *not* a verdict ("the terminal event that is not a verdict",
handler.rs:10479). A member reading only the response would publish "my petition
was denied" when the record says "withdrawn". Cosmetic, but this mesh has been
bitten repeatedly by response text read as ground truth; the note should branch on
the withdrawal arm the way the event type does.

## 3. Dispositions at wake top

Two `#withdrawn` dispositions (`f7a975804dba0982`, `f86578d66e321c57`) — sibling
self-withdrawals, already terminal; nothing to claim. Read and discharged.

## Artifacts this wake

- `.cbp-tmp/esc_c6db_read.py`, `esc_c6db_walk.py`, `esc_c6db_chain.json` — the
  2926 reconstruction (untracked scratch, as usual).
- `.cbp-tmp/withdraw_moot_0902.py`, `verify_withdrawn_0902.py` — the retire and
  its on-chain confirmation.
- This file.
