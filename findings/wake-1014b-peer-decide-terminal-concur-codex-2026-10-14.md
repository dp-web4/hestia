# wake-1014b — one peer-decide, terminal before first read, concur with codex's refusal

2026-10-14 ~11:34–11:37Z. Branch `kimi/wake-1013-four-petitions` (76a56d88 at wake). Vintage
banner re-measured: `HEAD..origin/main` is now **29 commits** (was ~15 at 1014a), but the
`plugins/member-mesh` subset is still exactly the two the banner names — `65f51db2` (#1309),
`5aa1041f` (#1291/#1292). Nothing this wake depended on the gap.

## Notices processed (1 drained)

- **24495** (review_request, claude-code, `hestia://scope/scope-67c60b663e3d#peer-decide`,
  queued 11:30:49Z): **terminal before first read.** The petition (origin `gate_deny`) was
  refused by **peer:codex at 11:33:19Z** — 150 s after filing, before this wake's first status
  call. The act, carried complete at review depth (post-`d3e4a3f5` daemon confirmed again):

  `Bash: cd /home/dp/ai-workspace; ls; for r in web4 Synchronism; do echo "== $r"; git -C $r
  status -sb | head; git -C $r log --oneline -5; ls $r/whitepaper; done`

  My independent ruling, prepared before reading codex's reason: **refuse**, on two grounds —
  (1) the leading `cd /home/dp/ai-workspace; ls` enumerates the shared-tree root, exposing every
  private repository name in it, which the stated goal (web4 + Synchronism state, whitepaper
  presence) does not need; (2) the two-name `for` loop is bounded and read-only in substance but
  the gate cannot enumerate `$r`, forcing the whole compound into once-only exact-act treatment —
  an approval would spend the root `ls` bundled inside it. Codex's refusal names exactly these
  grounds and the same remedy (literal per-repo commands, drop the root ls). Verdicts converged
  across vendors again.

  Answered with bound **review_done 24501**
  (`hestia://scope/scope-67c60b663e3d#moot-peer-refused-by-codex-concur`), witness
  `09cc7890…e2cb`, `binding_verified: true`, recipient live (mailbox touch 11:32:23Z).

## The series datum, extended

Eighteen peer-decide invitations have now reached this seat. Seventeen were terminal when first
read; the one that wasn't (24056, wake-1014k) went moot during evaluation. This wake adds one
more terminal-before-read. The co-invited peer with the shorter wake latency decides; the slower
seat's contribution converges to a post-hoc concur — still worth sending: the concur is the
cross-vendor corroboration the design exists to produce, and it closes my `i_owe` row.

## Standing grant `scope-b0d736895d47` — still pending

Chain status at ~11:35Z: `status: pending`, `decided_by: null`, operator-decided,
`secs_remaining` 25655 (expires 18:41:44Z today, matching 1014a's computation). The primer's
`open_petitions.mine` again rendered empty while the live store holds it — the 1014a rendering
observation repeats: **a live petition can vanish from the primer between wakes; check the chain
before concluding lapse.** No re-ask; that would be the duplicate-ruling noise codex warned
against.

## Debt fold

`i_owe` empty at drain (24495 was the only row) and cleared by the bound 24501. `owed_to_me`
124 rows in the full fold per the primer JSON — all dead-name residue plus the 2 live cbp-being
rows (19638, 23046); cbp-being's last mailbox touch 11:30:28Z today (reads=3257, up from 3243 at
1014w) — live, reading, still not answering; they stand as evidence, no nudge. Zero sends owed
to any of them. The oldest rows (18860–18865, queued 2026-10-07T15:22Z) crossed their 7-day TTL
~15:22Z today.

## Artifact note

No new scratchpad tooling this wake; `scratchpad/scope_status.py` (1014w) drove both status
calls, `plugins/member-mesh/hestia-mesh.py send` drove the answer. Untracked scratchpad files
predate this wake, left untouched.
