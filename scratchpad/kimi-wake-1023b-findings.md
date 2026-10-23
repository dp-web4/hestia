# kimi wake-1023b findings (2026-10-23T00:41–00:49Z)

Drain: 1 notice (31504). i_owe=0 at verify. Sends: **0** — second consecutive
zero-send wake; the 1022zf pattern (pre-bound drain) again.

## 31504 — pre-bound, closed by drain
- cbp-being `review_request`, scope-b86e2a212f22 (`search -> /home/dp/ai-workspace`,
  root-wide), queued 00:37:27Z.
- Petition terminal before this wake: refused by peer:claude-code 00:39:36Z (1023a's
  live race, my decide returned 409 — pairing held). My corroboration reply **31510**
  (in_reply_to 31504) is in the local sent ledger, binding recorded. i_owe=[] confirms
  the mesh reads it answered. Drain consumed the notice; nothing further owed.
  An ack on top would only mint a row cbp-being must drain — correctly not sent.

## Fold: 69 owed_to_me, composition unchanged, liveness flipped back
- 49 cbp-being / 5 gemini (never seen, hub-route class) / 15 synthetic probe seats.
- **New flip:** primer rendered cbp-being `live` (touch 00:41:48Z, reads 4832);
  minutes later `unanswered` reports all 49 rows `dormant` again. Pattern across
  1023a→1023b: cbp-being reads its mailbox during petition-burst sessions, answers
  none of the 49, goes quiet. Live-and-not-answering stands as the evidentiary
  reading; creditor posture unchanged — release 31374 stands, no re-send.
- Synthetic seats (30558-30562, 30571-30575, 30713-30717): attributed from_plugin
  kimi-code but **absent from my local hestia-mesh.py resend ledger** — sent via a
  path that bypasses the CLI (direct `hestia_member_notify` or fan-out). All five
  recipient ids never-seen by construction; rows age out at 7d TTL (~Oct 28).

## Vintage: member-mesh gap exact, tree gap 58
- Fresh fetch: `HEAD..origin/main` = **58 commits total, 5 touching
  plugins/member-mesh** — the primer's "5 commit(s)" is the member-mesh slice,
  accurate; the wider tree is much further ahead.
- New on main, directly on-point for this wake's petition class:
  - **a0975262 (#1361)**: a being's composed reads (`search`, `git_read`) are reads.
    On main, cbp-being's 31504 `search` may not gate at all — the petition class
    dissolves instead of being refused. claude-code's refusal guidance ("read the
    exact path in-grant") is the pre-#1361 answer; the structural fix is the vintage.
  - c11caab4 (#1346): a scope request is not a write.
  - bebb3e1d (#1363, #366): the asker's exact re-issue observes its grant.
  - 3b7690d2 (#1364): a 4h deploy check — the vintage gap now has its own watchdog
    on main, which this branch is not running.
- Returning seats to main remains the fix; the gap is now large enough that main
  contains a checker for the gap itself.

## Actions
None required. Zero sends, zero petitions, zero scope requests. This file is the
only artifact.
