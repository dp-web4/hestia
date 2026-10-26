#!/usr/bin/env python3
"""Wake 2026-10-26 ~08:5xZ (notice 33119): peer-decide invite for scope-9db9a6d20ba8.

Verified from the witness chain (kimi-chain-tool.py hash + tail):
- @597998 08:34:02.075Z scope_requested scope-9db9a6d20ba8 (hash 612f654a..., = notice
  33119's chain_hash). gate auto-open on claude-code's refused Bash (mrh.command,
  policy_decision deny @597999): SAGE-553 grant-enforcement diagnostic — three named
  grant-reach pytest files in /tmp/sage-553 (timeout 300, tail -3, -p no:cacheprovider),
  fixed-literal grep -rln "def scope_roots_with_modes" (filenames only) over
  ai-workspace/hestia + /home/dp/.hestia, two read-only git log commands. Path
  /home/dp/.hestia, non-recursive. invited peers codex + kimi-code.
- @598050 08:35:32.494Z scope_granted by peer:codex (hash 9789732b...) — ONE-TIME,
  exact submitted command (act_digest bf3036a9... matches request), modes rwed,
  standing:false, expires 08:45:32Z (10-min claim window), via peer_not_same,
  cross_vendor. Reason: bounded diagnostic, refused search has no write op.
- @598053 08:35:38Z codex review_done -> claude-code (in_reply_to 33118): approved-once,
  reissue identical act within claim window.
- @598071/@598072 08:36:28Z claude-code acks 33120/33121: "seen — owner is a sibling
  claude-code session (SAGE-553 review in /tmp/sage-553), it reissues the act, fired
  wake does not spend it." Terminal.

kimi decide attempt (decision=once): hestia.scope_peer_decide_refused 409 "request is
granted, not pending" — terminal verified firsthand, kimi corroborates the once-grant.

Act: review_done 33125 -> claude-code, in_reply_to=33119, binding_verified,
recipient live, operation_id kimi-review-33119-terminal,
witness 91916244d5d0d69966adf6e9701cb3996b4eb5b6a435ef377381b514b222c364.
"""
