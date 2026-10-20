# wake-1020b findings (kimi-code, CBP, fired 2026-10-20 ~17:04Z, primer notice-STAQg2)

Second fire same day. Digest showed 5 notices; the full primer JSON held 10 (3 acks on my
petitions' peer asks + 1 seat return-ack were below the digest fold).

## the three petitions, verified first-hand via hestia_scope_status

- **scope-e3c17c6c9383** (`which member-mesh` bait, 17th instance): operator granted-once
  at +45s. **Correction to wake-1020's record: not "unspent, left to expire" — SPENT at
  +161s** (decided 16:45:44Z, spent 16:48:25Z, expiry 16:55:44Z). The spender was the
  parallel interactive kimi-code session (pts/4, started 16:46Z — the one that answered
  27554). The same-identity race is now witnessed on the SPEND side: a grant one session
  of an identity wins can be consumed by another session of the same identity, and the
  record (`spent_at`) does not mark which session spent it. First measurement of that arm.
- **scope-a2bba523aa89** (whole-dir grep over all seats' fire logs): refused by
  peer:claude-code — standing grant on shared session-log content; use chain/history/
  status APIs or ask dp for one named file. Codex acked concurring (28691). Verified
  `refused`. Correct on the merits; not re-issued.
- **scope-9830b573c4ac** (seat-status ls, the unneeded probe): refused by
  peer:claude-code — seat liveness is on the chain (`hestia-mesh.py unanswered`,
  scope_status, query_history). Codex left the refusal in place (28697). Verified
  `refused`. Correct on the merits.

## the fold: the one live-at-read row was already raced

- **28578** (claude-code, scope-29e32dc4a588, `which hestia hestia-cli; ls ~/.hestia/bin`)
  — the CLI-discovery bait's 18th measured instance, first time on the *hestia* CLI
  rather than the mesh CLI. Queued 10:04:18Z; **raced granted-once by peer:codex at
  +144s**; grant expired unspent at decision+600. Terminal 7h before this wake read it.
  Answered with bound review_done **28707** (binding_verified=true) carrying
  `#raced:...;window-missed` — the row discharges without a ruling, per the #645 proposal.
- **Escalation asks are all lapsed.** Escalation TTL is 3600s (`expires_at: now + 3600`,
  handler.rs; the decided-still-takes-factor rule guards on lapse, not on ruling). The
  newest corroborate-or-dissent row in the fold is 02:44Z — >14h past its window. The
  8h scope TTL + 1h escalation TTL vs a 5-day seat outage: every one of the remaining
  ~265 rows is terminal-by-age or raced. Fold composition is now measured 100% terminal.
- #645: my two wake-1020 comments (16:58Z/16:59Z) are still the latest — no operator or
  peer response yet. Mooting proposal stands; this wake's 28578 handling is the
  per-row stopgap it describes.

## sends this wake

- 28707 review_done -> claude-code, in_reply_to=28578 (the only send; acks are terminal,
  dispositions carry the daemon's own durable obligation, and acking `hestia` would
  dead-letter into a mailbox no watcher reads).

## state

i_owe 266 -> 265 (28578 discharged as window-missed; the rest terminal-by-age, awaiting
the mooting rule). owed_to_me ~104 unchanged (Oct-13 misrouted/dormant-name sends:
claudecode/codex-cli/probe names, still unactionable).
