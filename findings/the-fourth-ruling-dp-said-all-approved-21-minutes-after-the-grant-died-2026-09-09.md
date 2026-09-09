# The fourth ruling: "all approved" arrived 21 minutes after the grant died (2026-09-09, claude-code / CBP)

Wake context: one `disposition` notice (12423) on co-seat petition `6d8b8991f18b9f5e`,
approved by dp at 01:41:38Z. Not mine, not in the owed fold, nothing answered on the mesh.
This is the fourth petition tonight for one logical change, and the one that finally
landed (`wttarget/plugins/_shared/sprintE_test.py` now hashes `5afcfde4…`, equal to the
patched source; the prior wake measured it at `18844cfe…`).

## Timeline (2026-09-09 UTC, chain via `tools/chain_walk.py`, asker via its host_session jsonl `9261dc9a…`)

| t | who | event |
|---|---|---|
| 01:07:30 | asker | re-issues the `cp`; refused; `4a1e3136d6b02488` opens, digest `46006450…` |
| 01:07:36 | asker | "Once that's in I re-issue the write" — then idle |
| 01:09:53 | dp | approves `4a1e3136` (reason `k`), +2m22s |
| 01:11:18 / 01:13:35 | codex / kimi | factors on `4a1e3136`, both after the decision |
| 01:19:53 | daemon | claim horizon passes: `decided_at + 600` (`decided_horizon`, `gate_escalation.rs:921`). No chain row. |
| 01:41:15 | dp | types "all approved" into the interactive session |
| 01:41:23 | asker | re-issues the byte-identical `cp`; refused; **`6d8b8991f18b9f5e`** opens, same digest `46006450…` |
| 01:41:38 | dp | approves `6d8b8991`, +17s |
| 01:41:52 | asker | claims, 14s after the ruling; the copy runs; suite passes |

`tools/claimable.py 4a1e3136d6b02488` at 01:46Z: `NO — past horizon by 1605s`. The grant
dp ruled on at 01:09:53 was spendable for ten minutes and nobody who could spend it was
told inside those ten minutes.

## What is new here

Not the shape. The 2026-09-02 finding
(`the-approval-outran-the-request-for-it-two-grants-lapsed-while-the-asker-waited-to-be-told`)
is the same seat, the same interactive session type, the same "tell me when they are
approved". This is its second specimen, seven days later, and this time the asker's
recovery (a fresh ask) was measured through to the claim.

**The census.** Chain walk, 30,000 entries, 2026-09-02 07:14Z to 2026-09-09 01:43Z:

| | count |
|---|---|
| approvals recorded | 103 |
| approvals never claimed (lapsed) | 26 |
| lapsed approvals with an `expired` chain row | 0 of 26 (the 4 `gate_escalation_expired` rows are all undecided petitions) |
| lapsed approvals re-asked later under the same `(plugin, act_digest)` | 9 |
| of those, re-approved | 9 of 9 |
| of those, then claimed | 6 of 9 |
| of those, lapsed a second time | 3 of 9 (`ef121b31`, `32f73af7`, `34f5ff4f`; `32f73af7` was itself re-asked and claimed on the third id) |

Nine second rulings in seven days on questions dp had already answered, every one
approved again. The re-ask is the modal recovery from a lapse, it always succeeds, and it
costs the operator one more ruling plus the peers one more 8-way invitation
(`invitation_evidence` on `6d8b8991`: codex and kimi live, six names with no mailbox
reader). kimi's wake on this petition fired at 01:41:42Z, 10 s before the claim; its
poll on the chain is at 01:42:52Z, a minute after the write it was invited to review.

## What it bounds, against #366's acceptance list (dp, 2026-08-31)

1. *"no claim/authorization window is keyed to … poll observation"* — still keyed.
   `decided_horizon` is `min(observed_at.or(decided_at) + 600, expires_at + 600)`. The
   window opened at the ruling, and the ruling reached the asker 31 minutes later through
   the only channel an interactive session has: dp typing into it.
2. *"duplicate escalation on blind retry is eliminated by canonical-action dedupe (#668)"* —
   eliminated for a **pending** twin only. `open_or_coalesce` (`gate_escalation.rs:1554`)
   folds on `(plugin_id, marker, act_digest)` into a petition that is still open; an
   approved-and-lapsed twin under the same digest does not coalesce, it mints. Tonight's
   4th id, and 9 of the 26 lapses above, are the blind-retry case #668's closure claims
   is gone.
3. The lapse itself is invisible on the chain. An approval that dies unclaimed writes no
   row; the 26 are computed by absence (decided minus claimed), the same
   one-sign-record shape as #668's original headline, now on the decided side of it.

## What this seat did not do

Did not reply on the mesh (disposition rows are not booked). Did not poll `4a1e3136`
(`hestia gate poll` arms the seat's fuse, #732; `claimable.py` reads the resource). Did
not touch the co-seat's worktree. Did not file a new issue: #366 holds the residual and
this is a specimen for it, posted there.

## Not measured

Whether the 17 lapsed approvals that were *not* re-asked were abandoned wants or acts done
by another route (the 2026-09-02 finding's "7 of 10 ran" was measured from the transcript;
this census was not). That is the number that says whether the lapse costs the operator
nine rulings or seventeen acts.
