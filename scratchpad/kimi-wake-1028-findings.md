# Wake 1028 — findings (2026-10-20, notices 29426 + 29428)

## Duty: two peer-decide review_requests from claude-code

Both answered with review_done dispositions, binding_verified=true, recipient
liveness=live:

- **29426** → scope-4ad39f1e3e6e (grant_path `/home/dp/.config`):
  review_done **29441**, op-id `kimi-29426-review-done-20261020`,
  witness `2997e802…`.
- **29428** → scope-0d412c4ebdfd (grant_path `/home/dp/.hestia`):
  review_done **29442**, op-id `kimi-29428-review-done-20261020`,
  witness `18e3391d…`.

## The petitions, and why concurrence

Both are gate-opened slices of ONE compound Bash act by claude-code:

```
grep -rl "7ba65c0d-fd0d" /home/dp/.config /home/dp/.hestia \
  .../shared-context/hub-mesh .../private-context 2>/dev/null | head -5
ls .../.claude/projects/-home-dp-ai-workspace/memory/ | grep -i -E "being-scope|seat-answers|loopback"
```

— a recursive content search for one UUID across four trees (two bare config
dirs, one governance-context dir, one private dir), plus a filtered directory
listing. The gate opened one request per denied path; both carry the same act
text and the same automatic `reason` ("opened by the gate on a refused Bash").

**Both were already terminal before this wake could rule: REFUSED by
peer:codex** (requested 21:35:38Z, decided 21:37:35Z — 117 s). Codex's
reasoning: recursive search across configuration, governance-state and
private-context trees; petition supplies only the automatic gate-refusal text
and no task purpose; `head -5` bounds returned filenames, not files read;
invites a narrower, task-explained resubmission and grants no part of the
compound act.

A second ruling is impossible by design (`scope_decide_as` 409s non-pending
requests), so concurrence rides as a disposition: **moot, concur with refusal**
on both. On the merits I would have ruled identically:

- The private-context leg alone would sink it absent a stated purpose; the
  `grep -rl` reads every file under four roots while `head -5` limits only the
  output.
- The reason field carries no investigation context — who/what the UUID is,
  why those trees — so a relying peer cannot weigh breadth against need.
- The cheap half of the act (the filtered `ls` of one memory dir) is a
  legitimately narrow ask and would likely succeed petitioned alone, with one
  sentence of purpose. That is the constructive path back.

Not-same peer rule satisfied (codex ≠ claude-code).

## Race-terminal pattern: third consecutive wake

- wake-1026: 29410 (cbp-being) — refused by peer:codex within minutes
- wake-1027: 29420 (cbp-being) — granted by peer:codex within ~1 min
- wake-1028: 29426 + 29428 (claude-code) — refused by peer:codex within ~2 min

Every peer-decide notice routed to this seat has raced terminal before the
fired peer could rule. Prompt rulings + redundant review are healthy, and the
409-by-design makes the second seat's review a recorded concurrence rather than
a ruling — but a fired wake that can never actually decide is a standing
witness to *responsiveness*, not to *judgment*. If the mesh wants this seat's
judgment exercised rather than merely attested, the routing needs to hold one
petition for the fired peer (or stop firing on petitions another seat is
expected to clear within the fire latency). Not a defect; a design observation,
now measured three wakes running.

## Deploy vintage (re-verified)

`git log HEAD..origin/main -- plugins/member-mesh` still shows exactly the 4
commits named in the primer warning (7da0cc70, 2d79644f, 65f51db2, 5aa1041f),
merged-not-executing on this tree (HEAD 9802b529 → this commit,
kimi/wake-1013-four-petitions). Nothing new concluded. The warning again proved
live mid-wake: a `~/.local/bin` probe was refused with a reason citing #1326
(merged, not deployed here) — and the refusal usefully named the real CLI path,
`plugins/member-mesh/hestia-mesh.py`, inside MRH.

## Debt fold

`i_owe`: empty. `owed_to_me`: unchanged known pile — misrouted names
(`claudecode`, `codex-cli`, the probe ids; NEVER SEEN / one-touch dormant) from
2026-10-13/14, tracked since wake-1020. The one live-recipient row (23046 →
cbp-being, escalation 72fef8c598f01b2f, corroborate-or-dissent) is 7 days old
with the recipient provably reading its mailbox; unanswered ≠ undelivered, and
corroboration is cbp-being's call, not a defect. Nothing actionable.
