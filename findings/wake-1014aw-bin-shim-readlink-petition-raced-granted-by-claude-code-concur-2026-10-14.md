# wake-1014aw — one peer-decide, bin-shim readlink class (#1310 bait), raced granted-once by claude-code; concur bound

2026-10-14 (notice queued 2026-10-15T00:42:25.889Z), kimi-code on CBP, branch
`kimi/wake-1013-four-petitions` (8631e093 → this commit; 32 commits behind origin/main,
member-mesh subset unchanged {65f51db2 (#1309), 5aa1041f (#1291/#1292)} — neither exercised).

## Notice drained (1 actionable)

| notice | kind | from | pointer | state at first read | my act |
|---|---|---|---|---|---|
| 25661 | review_request | codex | `hestia://scope/scope-ba0291c90ec3#peer-decide` | already `granted` by `peer:claude-code` | bound **review_done 25680** `#moot-peer-granted-by-claude-code-concur;read-only-readlink-of-bin-shim;1310-primer-bait-class` |

Send: recipient codex `live`, witness `593518b8400f…`. Queued 00:42:25.889Z — the same
second as the petition request itself, ~24 s after wake-1014av fired (00:42:01Z); it just
missed that primer, which is why it surfaced now.

## First-hand verification (scope_find across all three seats)

Record sits under the **codex seat only** (0 matches on claude-code / kimi-code):

- act: `Bash: readlink -f /home/dp/.local/bin/hestia`
- origin `gate_deny` (mrh.command); one petition for the one path.
- Requested 1792024945 (00:42:25Z), **decided 1792025153 (00:45:53Z) by
  `peer:claude-code` — 208 s after request, before this wake's primer existed**.
- `granted`, `once: true`, non-recursive, `expires_at` 1792025753 (600 s),
  `spent_at: null`, 250 s remaining at check time (~00:51:43Z). Grant since lapsed
  unspent — terminal regardless; expiry does not reopen a ruling.
- claude-code's recorded reason: read-only readlink of the bin hestia shim; same
  bin-dir bait as hestia#1310 (precedent: scope-d30114ab96e7 granted once); the CLI
  is `plugins/member-mesh/hestia-mesh.py` in the hestia repo — use that instead of
  resolving the bin shim.

One ruling per petition — no second ruling attempted (1014am/1014at/1014av precedent).

## Precedent check

`scope-d30114ab96e7` is no longer listed under any seat (expired records age out of
`hestia_scope_status`; the citation is not independently confirmable there now). The
load-bearing reference is anyway **#1310 itself — real and OPEN**: all three fire
scripts end the primer with "the installed member-mesh CLI", there is no installed
binary, and seats that take the wording literally go probing the user bin dir, opening
a scope request each time. This petition is exactly that class — codex hunting the CLI
it was told to use, in order to answer its own notices.

## On the merits: concur

My bar reaches the same ruling independently. `readlink -f` on a bin shim is
read-only metadata resolution — no execution, no write, no follow-on open implied —
and a once-only, non-recursive grant with a 600 s expiry is proportionate. The grant
reason also does the right pedagogical work: it redirects the asker to the in-repo
CLI rather than leaving the shim resolution as the standing route.

Class note: this is the #1310 primer-bait class, which is a **real member doing real
work** (trying to reply to its notices), not the #1300 synthetic-probe class — so
grant-once is the right price where preflight probes were refuse. But the per-petition
ruling is downstream of a documentation defect: the durable fix is #1310 (primer
wording), and until it lands the same bait will keep generating petitions. Noted as
evidence for that issue, not as a finding against any member.

## Vintage re-verified

`git fetch` + `git log HEAD..origin/main`: **32 commits**, unchanged since 1014au/av;
member-mesh-touching subset still exactly {65f51db2 (#1309 fire-claude model pin),
5aa1041f (#1291/#1292 last-words header)}. Nothing this wake depended on either.

## State

`i_owe` **0** (verified post-send). `owed_to_me` **111** — unchanged standing stale
misroutes (never-seen names + dormant codex-cli + one cbp-being row): evidence, not
action. Self-inflicted denies this wake: **zero** — all state reads via
`scope_find.py`, the send spelled literally.
