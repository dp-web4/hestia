# Same command, different bytes, one digest (2026-09-09, claude-code / CBP)

Wake context: two `disposition` notices (12399, 12400) for co-seat petitions
`0587d26c1f4e55a8` and `68b9952f1f04564a`, both approved by dp at 01:06Z and claimed by
the co-seat 20-24 s later. Neither was mine; the disposition kind is not counted in the
owed fold, so nothing was answered on the mesh. The value of the wake is the third
petition that opened 66 s after the second was spent.

## The instance

| escalation | opened | act_digest | full cp command | source-file bytes at that instant |
|---|---|---|---|---|
| `68b9952f1f04564a` | 00:27:41Z | `46006450…` | 236 chars, sha256 `45a60142…` | `18844cfe…` |
| `4a1e3136d6b02488` | 01:07:31Z | `46006450…` | 236 chars, sha256 `45a60142…` | `5afcfde4…` |

- Both digests recompute as sha256 of the 228-char preview (#627's identity holds).
- The full command, recovered from the co-seat transcript, is byte-identical across all
  four issues of it tonight. Truncation plays no part in this pair.
- The source file changed at 01:07:25Z (3-line re-patch after the suite exposed a second
  pinned test); the command was re-issued at 01:07:30Z.
- kimi-code's concur on `68b9952f` (00:34Z) pins the payload as `18844cfe` in free text.
  The claimed write landed exactly that (verified on disk). The next ask, under the same
  digest, would land `5afcfde4`.

## What it bounds

1. #627's remedy ("digest the full act") and #929's prerequisite ("persist `act`") together
   still leave these two rows identical on every field. For cp/mv/install/patch-shaped acts
   the payload is a file the command names, absent from `tool_input` entirely — one step
   past #616, where the payload is in `tool_input` and merely unread.
2. `open_or_coalesce` folds a new ask into a pending twin on `(plugin_id, marker,
   act_digest)` (`gate_escalation.rs:1554`). With the re-patch before the ruling instead of
   60 s after the claim, the second payload would have ridden the first petition and its
   peer factor. Counterfactual: supported by the code path, not measured.
3. The only content hash on the chain is prose inside a factor; nothing compares it.

Repair already named by codex (notice 10215): bind a content-addressed before/after.
Sequenced behind #929. Posted to #627 (issuecomment-5594237719).

## Cost of the shape

One logical change, three approvals, 24 peer invites of which 18 went to names with no
mailbox reader. dp approved the third petition at 01:09:53Z, 2 min 22 s after it opened;
a peer factor landed at 01:11:18Z, after the decision, the #648 modal shape.
