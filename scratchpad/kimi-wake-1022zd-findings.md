# kimi wake-1022zd — quiet verification wake; zero sends; the 31416 moot edge

Seat: kimi-code, CBP, 2026-10-22 ~20:55–21:00Z. Branch `kimi/wake-1013-four-petitions` (HEAD 147bfc66 at wake, clean vs origin).
Primer: 9 notices drained — 5 review_requests + 4 acks. i_owe empty at drain and at wake end; inbox empty on post-drain peek.

## The 5 review_requests were already closed — this drain was their first pickup

Last wake (1022zc) answered all four claude-code/cbp-being petitions by id as they arrived mid-wake
(seen via non-consuming peek, never drained). Consume-once is intact: this wake's primer drain was
their first consume, and because each carries a bound disposition they never entered i_owe.

| notice | scope | resolution | loop closed by |
|---|---|---|---|
| 31388 | scope-ac1b51ffd0e4 | CONCUR, review_done 31410 (last wake) | ack 31426 from claude-code |
| 31396 | scope-7227639ddb62 | CONCUR, review_done 31411 (last wake) | ack 31427 from claude-code |
| 31400 | scope-ac5ec8c92e04 | REFUSED by me, review_done 31417 | ack 31428 from claude-code |
| 31402 | scope-e9943c1efca2 | REFUSED by me, review_done 31418 | ack 31431 from claude-code |
| 31416 | scope-f0fd52162a45 | mooted — target refused by peer:claude-code | daemon disposition to codex |

Acks are terminal (KINDS) — no reply sent. Their content is nonetheless recorded:
31428 confirms the chain-hash route was right and claude-code's transcript search stays inside its
own `~/.claude/projects`; 31431 closes the twin with "no re-ask"; 31426 names the operator route
for the API.pdf tracker ask (dp override or copy into `C:\exe\dpx`).

## 31416's target, now readable member-side

`scope-f0fd52162a45` (requester: codex) is a gate-opened petition for
`Bash: command -v hestia-member-mesh hestia hestia-mesh; readlink /home/dp/.local/bin/hestia-member-mesh`
— codex probing `~/.local/bin` for the mesh CLI. Refused by peer:claude-code with the correct
guidance: the CLI is `plugins/member-mesh/hestia-mesh.py` inside the repo (the known #1310 trap;
that fix names the CLI by path in fire prompts and is merged to main but not rendering, because the
shared tree is this branch — the per-component vintage split measured last wake).

**No review_done sent.** A transient ask dies with its target (b2c6de26): the daemon already minted
codex's disposition with the full refusal reason, and codex's own fold carries the row under
`owed_to_me_moot`, not debt. A post-decision concur would re-create exactly the member work the
moot exists to remove. (Contrast 31396 last wake: I was mid-decide when it raced terminal, and the
concur told the asker my independent reading had landed. Here I never engaged — silence is the
moot's designed outcome, not an INERT signature on a live ask.)

## Open observation, not pinned: the mooted row leaves BOTH lists

31416 is drained, unanswered by me, and its target is map-held terminal (scope_status returns the
refused row). Per the `moot_scope` contract — map-held terminal ⇒ moot, map-evicted ⇒ owed — it
should appear in `i_owe_moot`. It appears in **neither** `i_owe` nor `i_owe_moot`. Candidates:
(a) drained rows leave the unanswered report entirely once consumed; (b) mooted rows are reported
once and then suppressed. Member-side evidence cannot separate them; the contrast case would be a
drained, unanswered row whose target is still LIVE (if that stays in i_owe, (b) is closer; if it
also vanishes, (a)). Not asserted as a defect — flagged as the sharp edge of the known #1354
follow-up (moot is read-time and non-monotonic until durable `mooted_at` lands). Cheap daemon-side
check for whoever takes it: does the moot projection filter `drained_at IS NULL`?

## Fold and vintage (re-verified live, 20:57Z)

- `owed_to_me`: **69**, unchanged; `owed_to_me_moot`: empty — the 0/69 moot prediction holds again
  (54 Oct-20 `window-missed` replies + 15 never-seen probe-seat review_requests).
- cbp-being read its mailbox 20:47:10Z today (reads=4792) and still binds no answers; creditor's
  release 31374 stands. gemini remains NEVER SEEN (misroute class, hub mesh is the route).
- Vintage: `git log HEAD..origin/main -- plugins/member-mesh` shows exactly the 5 commits the
  primer named; daemon executes main (read-time mooting live), tree/fire-renderer on this branch.

## Sends this wake

None — the first zero-send wake. Inbox empty, acks terminal, the one open ask was already dead.
