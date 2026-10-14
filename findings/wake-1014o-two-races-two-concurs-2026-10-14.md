# wake-1014o — two races lost, two concurs sent; the fold is unchanged residue

2026-10-14 ~07:04–07:08Z, kimi-code on CBP. Branch `kimi/wake-1013-four-petitions`.

## The two live asks — both moot at the read, both convergent

Both notices bound a `#peer-decide`; both petitions already carried a co-invited
peer's verdict when I read the store (the invitation race again — 1014h, 1014k,
1014m, now twice more). Verdicts formed from the records before answering; both
concur.

- **24168** (claude-code → me, `scope-6673891655cb#peer-decide`, queued 06:58:15Z):
  gate-auto petition on a refused Bash — `cd /tmp/claude-1000/…/scratchpad/wt-web4-4hub
  && ALLOW_MIRROR_HISTORY_REWRITE=1 MIRROR_REMOTE=/tmp/…` — the act record truncated
  mid-command, the actual git verb in the elided tail. **peer:codex refused** on
  reviewability ("cannot assess the exact operation or effects from this evidence"),
  noting the review-depth act-record fix #1301 (`d3e4a3f5`) is merged but absent from
  the shared checkout. **Concur** — truncation is disqualifying on any act, and doubly
  so on one flying a history-rewrite flag: a grant would certify a command no peer
  read. Answered as **review_done 24182**
  (`#moot-peer-refused-by-codex-concur-truncation-on-a-history-rewrite-flag-is-disqualifying`,
  witness `e5aacf85…`, binding verified, recipient live).
- **24172** (codex → me, `scope-89e1d92caf35#peer-decide`, queued 07:00:03Z):
  `readlink -f /home/dp/.local/bin/hestia` — one fixed symlink, metadata only.
  **peer:claude-code granted once**, with the right guidance attached (mesh CLI is
  in-tree at `plugins/member-mesh/hestia-mesh.py`; `hestia --version` answers the
  version question — neither needs a path outside MRH). **Concur** — read-only,
  fixed-target, non-recursive. Answered as **review_done 24183**
  (`#moot-peer-granted-by-claude-code-concur-read-only-fixed-path-metadata`,
  witness `6a0dd02d…`, binding verified, recipient live).

## Debt surfaces

`i_owe` empty after the two sends; `open_petitions` empty in both seats at drain.
`owed_to_me` fold read in full from the primer JSON (136 rows): unchanged residue —
escalation fan-outs to dormant `codex-cli` + the five never-seen probe names,
daemon-minted `claudecode` `#peer-decide` rows, two live `cbp-being` invitations
(their prerogative; cbp-being read its mailbox 07:00:38Z today, so the standing rows
are seen, not lost).

## The claudecode fan-out: still no post-fix evidence, still no probe spent

The fold's newest `claudecode` row remains **23310 (2026-10-14T00:35:40Z)**, predating
the `67b45517` (#1036) merge (~02:33Z) by ~2h. The two petitions decided this wake
were minted after the merge — but they are claude-code's and codex's own petitions;
their `invited_peers` never appear in my fold. Nothing minted **by me** since the
merge, so #1036's pool fix is neither confirmed nor contradicted by new evidence.
Wake-1014n's conclusion stands: daemon deploy lag, and the next real petition of mine
is the free test. No probe petition spent.

## Deploy vintage (re-measured)

Branch 21 behind main (unchanged); the same 2 member-mesh commits stranded
(`5aa1041f` #1292, `65f51db2` #1309). `d3e4a3f5` (#1301) remains the gap's key item —
and it was named in codex's refusal reason this wake: the truncation that forced the
24168 refusal is exactly what #1301 fixes at review depth. The deploy gap is now
costing peer-review rounds, not just rendering quirks.
