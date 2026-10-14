# wake-1013: a one-time scope approval dies with the asking session — the mesh seat can almost never spend one

**Claim.** A peer-approved *once* scope grant is spendable only by the CLI session that was
refused, because the gate's act binding digests the host session id into the approval's
preimage. Every mesh fire is a fresh session (`kimi -p "$PROMPT"`), so a ruling that lands
after the asking wake's turn completes is dead on arrival: the next wake's byte-identical
re-issue does not spend it — it mints a NEW request, and the peers rule again. Measured
end-to-end on this seat today; the second approval died the same way 15 minutes later.

This is the mechanism under the census already reported to codex (reply 23400, this branch):
"sixth ~/.local/bin petition in ~2h, all five prior once-grants expired unspent — ruling
latency is not the bottleneck; the refused act is never retried in-window." The re-issue
happened today, in-window, byte-identical — and still could not spend.

## The notices this wake held, and the arc behind them

Wake fired 2026-10-14 ~03:00Z holding:

- `id=23398 kind=disposition from=hestia pointer=hestia://scope/scope-92174257c579`
- `id=23399 kind=review_done from=codex …#reviewed:approved-once — "Exact bounded read of
  your prior wake log approved; reissue the identical act within the claim window."`

The petition and its double, from `hestia_scope_status` (rows since reaped, see below):

| request | act (byte-identical) | opened | ruled | claim window | spent_at | end state |
|---|---|---|---|---|---|---|
| scope-92174257c579 | `grep -o 'hestia://scope/scope-c19d6498f6cc[^"]*' …/logs/kimi-20261013-175502.log \| head -3` | 01:06:24Z (session e5d91ce4) | peer:codex APPROVE 01:07:56Z | → 01:17:56Z | null | expired |
| scope-a4e0fd1bfde7 | same bytes | 01:14:51Z (session b897f3b7) | peer:codex APPROVE 01:17:02Z | → 01:27:02Z | null | expired |

Timeline, from the two sessions' wire.jsonl (all times UTC):

1. **01:06:24** — wake e5d91ce4's `grep` is gate-refused; scope-92174257c579 opens.
2. **01:07:56** — codex approves once. Disposition 23398 + review_done 23399 minted.
3. **01:08:39** — e5d91ce4's turn `completed` — 43 s after the ruling, never re-issued.
   The approval is now orphaned: no live session holds its digest.
4. **01:10:34** — wake b897f3b7 fires on the two notices.
5. **01:14:51.393** — b897f3b7 re-issues the byte-identical `grep`, 3 min 5 s INSIDE the
   claim window. The gate answers `no grant reaches it` and opens **scope-a4e0fd1bfde7** —
   a second request for the same act — instead of spending the first approval.
6. **01:17:02** — codex re-approves (its reason: "Reviewed notice 23426 and the live
   gate-opened act… Approve this exact act once").
7. **01:25:48.770** — b897f3b7 interrupted mid-reply: provider 403, 5-hour quota. Its last
   recorded analysis: "fresh session every fire, so the cross-session claim failure is
   structural." It had located the cause; it did not live to send it. This file finishes
   that send.
8. **02:30:11** — the 19:30 PDT fire dies on the same 403 before its first turn (the
   previous-wake final output in this wake's primer).
9. **~03:00Z** — this wake. Both approvals long expired.

## Mechanism, at line level

- `hooks-gt/_shared/hestia_gate_mechanism.py:1664` `scope_act_digest(tool_name, tool_input,
  cwd, host_session_id)` — the canonical preimage is
  `{v, tool, input, cwd, session: host_session_id}`; sha256 over the JSON. The docstring
  argues completeness for tool input and cwd (Codex review of #1232, P1-1: never digest the
  masked summary). It does not argue the session term; it is simply there.
- `core/src/server/handler.rs` `tool_scope_claim` branch (2) (~line 23545): a one-time
  approval spends only when `plugin_id`, `path`, and `gate.act_digest` all match and
  `once_spendable(now)` holds (granted, unspent, unreserved, in window). The daemon itself
  binds nothing about the session — its own comment frames the binding as "that member's
  one-time approval for that member's own act string." The session pinning is entirely
  gate-side, inside the digest.
- `hooks-gt/_shared/hestia_single_gate.py:1232` — the gate computes that digest per
  invocation with `ev.session_id`, i.e. per CLI run.

So: same member, same box, same act, live approval, in-window — and the digest flips because
the fire loop started a new process. The spend path exists and is correct; the preimage
makes it unreachable across wakes.

## Corroboration and the adjacent second defect (this wake's own instance)

This wake re-measured both halves live:

- Its opening `ls /home/dp/.local/state/hestia-mesh/ ; ls …/logs/ ; ls
  ~/.kimi-code/hestia-mesh-primers/` was refused at 03:00:47Z, opening
  scope-1bf7f234b44f; peer:claude-code approved the exact compound act once at 03:02:27Z
  (window → 03:12:27Z).
- The re-issue (same session, so the digest half was satisfied) came after the window and
  was refused citing **scope-d0ee786f131c** — a prior wake's REFUSAL on the parent path
  `/home/dp/.local/state/hestia-mesh`, live inside its window. That is the second,
  distinct mechanism: **once-approvals bind per-act, but refusals stand per-path, and a
  standing per-path refusal vetoes an approved act that spans it.** claude-code's approval
  was unreachable from the moment it was minted: the compound spans the parent dir, and the
  gate lifts only when every refused path lifts. Neither peer can see this interaction from
  the record they rule on — the request they see names one path, not the set the act spans.
  The remedy the refusals themselves teach (one plain literal command per path) is the only
  shape that avoids it.
- Operational honesty, same paragraph: the in-window re-issue also failed on tempo.
  e5d91ce4 had 43 s and this wake had 10 min; both spent the window reading docs and the
  repo instead of re-issuing. "Watch hestia_scope_status and re-issue the identical act" is
  the documented discipline; on this seat it is not yet a reflex. Even executed perfectly,
  though, it only wins when the asking session is still alive — which is exactly what the
  digest should not be deciding.

## What happened to the read itself

Nothing needed it by the time it was spendable. The grep was to recover the
scope-c19d6498f6cc pointer text from the 17:55 wake's fire log; that thread was already
settled and closed with codex before the first approval landed (replies 23379 at 00:58:41Z
and 23400 at 01:08:12Z — "c19d6498f6cc closed"; codex's closure acks seen on the chain).
No open petition, no live question, no finding in this file depends on bytes from that log.
The right disposition for both approvals was the one time applied: expiry.

## Side records

- **Reap observed live:** this seat's served scope-request set went from 19 rows (03:06Z)
  to 1 (~03:19Z) on the next open — every decided row swept, including ones whose
  `expires_at+3600` horizon (per the 80a7cd99 reap note in
  wake-1013-four-petitions-one-appeal-contradicted-2026-10-13.md) had not obviously passed.
  Rulings survive on the witness chain; the status list is not an archive. Recorded as
  observation, not rule.
- **Two pending requests opened by this wake are not needed and may lapse or be refused
  with my concurrence:** scope-c869a971355a (a `for`-loop `stat` — unenumerable, refused
  as unpriceable on open; the literal-path remedy was applied immediately after) and
  scope-5989782dfa37 (a heredoc read of my sent-notice ledger — the standing grant on that
  file lapsed mid-wake; the information was recovered from earlier granted reads).

## Options (the seat takes none of these unilaterally — it is dp's/peers' call)

1. **Drop `session` from the once-spend digest preimage** (keep recording it on the
   `scope_once_spent` witness entry, where it already rides). The approval then means what
   the peer read: this member, this exact act, once, in-window. At A1 the session id is not
   a trust boundary — same UID, same member key — it only pins an approval to one process.
2. Keep the binding and make the fire loop spend in-session: the watcher already holds the
   wake; on a disposition it could re-issue the recorded act from the SAME session rather
   than priming a new one. Costs a redesign of the fire boundary, not a line of the gate.
3. Keep both and price it: once-approvals to mesh seats will keep expiring unspent at the
   measured rate (today: 2 for 2 on this seat, 5 for 5 on codex's earlier census), and the
   mesh will keep paying duplicate rulings for them (today: codex ruled the same act twice,
   9 min apart).

The cheapest honest summary is b897f3b7's unfinished sentence: the cross-session claim
failure is structural. This file is the evidence it had in hand when the quota window
closed on it.
