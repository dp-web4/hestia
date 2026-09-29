# The approval outran the request for it: two grants lapsed while the asker waited to be told

**2026-09-02, CBP, claude-code (mesh wake 18:53Z on dispositions 9505 / 9506).** Instruments:
`resources/read` on both `hestia://escalation/<id>` pointers (fuse-free; nothing polled),
`tools/claimable.py` five times across the horizon, `tools/chain_walk.py` over the 18:51:40Z to
18:52:39Z window (15 rows), `stat` on the act target, and the asker's own transcript
(`888f190a…`, the interactive co-seat on this box, cwd `/mnt/c/exe/projects`).

## Timeline (all 2026-09-02, UTC)

| t | who | event |
|---|---|---|
| 18:48:12 | asker | reports #839 and names "two things only you can do": add `HESTIA_WORKSPACE` to the claude-code hook lines; delete the `ai-agents/ai-agents` self-symlink |
| 18:51:21 | dp | "i expect you can do both :) or, at least give me cut and paste command lines. i don't want to edit files myself, it's a conceptual boundary :)" |
| 18:51:47 | asker | `Edit` on the PreToolUse gate line → refused `gate-self-access`, **`d46aaea3fadc9cdb`** opened (`asker_basis: session`, bar `single_approver`) |
| 18:51:49 | asker | `Edit` on the PostToolUse witness line → refused, **`32f73af7ff87ac52`** opened. Same `act_digest` as the first: `8dae0f52e46864a3…` |
| 18:51:50 | asker | `rm /mnt/c/exe/projects/ai-agents/ai-agents` → chain `policy_decision: warn` ("File deletion flagged"), enforced, **ran** |
| 18:51:58 | dp | `d46aaea3` **approved**, reason `ok`, via `POST /api/operator/gate-escalation` (operator-lct-signature). +11 s after open |
| 18:52:06 | dp | `32f73af7` **approved**, reason `ok`. +17 s after open |
| 18:52:20 | asker | final text: "Approve both and I will re-issue the two edits to claim them. Claims die about ten minutes after your decision, so **tell me when they are approved** rather than approving and walking away." |
| 18:53:24 | this seat | woken by the mesh with the two `disposition` notices |
| 18:54:40 | this seat | `claimable.py`: YES, 408 s / 416 s left. Target mtime 17:40:46Z, before either open |
| 19:00:11 | this seat | still YES, 72 s / 80 s; asker transcript has **zero** entries after 18:52:20 |
| 19:01:58 / 19:02:06 | daemon | claim horizons pass (`decided_at + 600`) |
| 19:02:29 | this seat | `claimable.py`: **NO, past horizon by 71 s / 63 s**; 0 claim rows; target mtime unchanged; asker still silent |

## What happened

**The approval arrived 22 s and 14 s BEFORE the asker asked to be told about it.** dp was at the
terminal and answered each refusal print within 11 to 17 s of the open, then the asker finished
its turn by asking for a keystroke that had already happened. Both parties then waited on the
other. The asker session had armed no listener (no background `hestia gate poll`, no peek), so
the mesh's two disposition notices woke a fresh session (this one) instead of the session
holding the act. The two grants lapsed unclaimed with the act never run.

This is a third disposition for the approved-unclaimed population (161/210), separable from the
two already recovered ([the recast](the-first-no-answered-a-fixture-the-grant-was-recast-around-20260901.md),
and byte-identical re-issue): **asker alive, act still held, blocked on a human signal that was
routed to a different session.** Neither transcript nor chain shows a recast or a give-up. The
gate was correct at every step. The loop closes through a human (it did, in 11 s), and this
time the human closed it before the asker was listening.

Specimens 9 and 10 in the unclaimed-grant series: act **not run** at the horizon, so the series
stands at 7 of 10 ran. Caveat pre-registered: both edits are still wanted, and a re-issue after
the horizon mints a fresh petition and pages dp again. If that happens it is a fourth face of
"unclaimed", a late re-issue, and the two rows should be re-scored then.

## What this seat did and did not do

- Did NOT perform either edit. The act is a gate-self write on another session's petition,
  `asker_basis` is `session`, and a same-bytes re-issue from this session would have minted two
  fresh petitions and paged dp twice (09-02 recipe: memory
  `ref_disposition_wake_check_consumed_first`, PR #795).
- Tried to reach the asker: `ListAgents` does not list session `888f190a` as a peer, and a
  `PushNotification` at 19:00Z returned "not sent (Remote Control inactive)". There is no
  channel from a mesh-woken seat to a live interactive session on this box other than dp.
- Read the pointers via `resources/read`, never the poll, so no observation fuse was started.

## Side observations, each testable

1. **Two petitions, one `act_digest`.** Both opened rows carry `8dae0f52e46864a3…` because the
   digest is `sha256(stated_reason)` and `stated_reason` is `Edit -> /home/dp/.claude/settings.json`
   for both. Two different edits to two different lines were indistinguishable to the claim
   door. Untested: which grant a re-issue of edit 1 would have consumed, and whether a single
   re-issue could have been scored against either.
2. **The injected law overstates the `rm` deny.** The law text delivered at launch says a
   bare `rm` on an absolute path outside `/tmp` "lands here" (deny class 1). The chain shows
   `rm /mnt/c/exe/projects/ai-agents/ai-agents` scored `warn`, enforced, and the symlink is gone.
   The asker noticed this in-session. Untested split: flags (`-rf`) versus bare, and symlink
   versus regular file; the specimen is a bare `rm` on a symlink. The text and the preset
   disagree on at least this cell.
3. **The refusal print still says "RE-ISSUE within 4200s".** The real window is 600 s after
   the ruling (PR #835). The asker knew "about ten minutes" from memory, not from the print.
4. **`gate_self_access.requested_by.session_id` differs per hook invocation** (`0fb42343…`,
   `0d221194…`) while `host_session_id` is constant (`888f190a…`). Which of the two
   `asker_basis: session` binds the claim to is not stated in the record.
5. **Fail-closed twice this wake.** Two Bash calls (18:56Z, 18:58Z) got "no verdict, daemon
   timeout" with the interactive co-seat and kimi both active. Both retried clean.
6. **The primer's "open petitions: NOT MEASURED" line** was again the producer's gap;
   claimable.py and the chain answered the question for this seat directly.

## So what?

The previous wake showed the gate cannot see a recast and did not need to when review arrived
early. This wake shows the other edge of the same clock: the human can be too fast. The
disposition is delivered to whoever the mesh wakes, not to the session that holds the act, and
a session that ends its turn with "tell me when" has no ear for the answer. The remedy is not a
longer window. It is a delivery target: the daemon already records `host_session_id` on the
opened row, and the one party that could have spent the grant is the one party the disposition
did not reach.
