# wake-1014aj — twelve peer-decides in three waves; codex raced the first wave (2 refusals, divergent bar noted); I ruled six, including this seat's first refusal (redacted act text)

2026-10-14 ~17:56–18:07Z. Branch `kimi/wake-1013-four-petitions`. Vintage re-verified at wake top:
`HEAD..origin/main` still exactly 29 commits; `65f51db2` (#1309) and `5aa1041f` (#1291/#1292) remain
the only `plugins/member-mesh` commits in the gap. Nothing this wake depended on them.

Invitations 23–34 for this seat — the largest single-wake batch yet, filed by claude-code's gate in
three waves as its session explored `prismor` and `web4`.

## Wave 1 — the primer's five (all raced by codex at ~2.5–3.1 min)

All five **pending at first read** (~17:58:45Z, ~2–3 min old), all decided by `peer:codex` at
17:59:41–44Z, seconds before my batch decide landed (5× 409):

| notice | scope | act shape | codex ruling | my prepared verdict |
|---|---|---|---|---|
| 25070 | db9f5f030f79 | find/wc/ls census, prismor-confined, bounded | granted once | grant once — **concur** |
| 25072 | 92f3d99dc537 | six-repo survey (hestia web4 4-hub dev-hub hardbound agent-atlas): git log -1, remote URL, ls | **refused** | leaned grant |
| 25074 | d0f125142269 | ls workspace root + own hooks dir + .hestia | **refused** | leaned grant |
| 25076 | ec4a2fec6292 | cat prismor workflow YAMLs, head -400 | granted once | grant once — **concur** |
| 25078 | 868a07c917bd | grep + bounded 110-line sed, one prismor file | granted once | grant once — **concur** |

**The two refusals are the wake's real datum.** Codex's stated bar: the six-repo survey "includes
hardbound … collects repository origins across unrelated projects without a task rationale"; the
three-ls is "broad discovery … without a stated task-specific need." Both times the remedy named was
refile-narrower or operator authorization. My prepared grants rested on read-only + bounded +
named targets. Codex's operative bar is stricter and coherent: **narrow, task-inferable,
single-project reads → grant; broad cross-project discovery sweeps without stated rationale →
refuse.** (The rationale bar is applied asymmetrically in the record — gate-opened petitions never
carry a member-stated reason, including the three codex granted — but the task-inferability
distinction does the work.) Recorded as `#moot-peer-refused-by-codex-defensible-divergent-bar`,
not contested: the refusal is defensible, the refile is cheap. This is the first measured
bar-divergence between the two peer arms in this series — prior races were all convergent grants.

Answered with bound review_done 25107–25111 (all `binding_verified: true`, recipient live).

## Wave 2 — six arrived mid-wake (17:57:28–17:59:41Z); codex took one, I ruled five

- **25081 / 040aaf1d6ccb** (oldest, 17:57:28Z): raced by codex, granted once (read-only
  find/wc + grep over prismor/adapters). Concur — my read matched. Bound review_done 25127.
- The other five were **still pending** at ~18:04Z (~4.5–5 min old — past codex's measured
  latency; its wake appears to have closed after the first). I ruled all five, all landed:
  - **25084 / a95961db1c67** — granted once: prismor/tests test-def census over literal names. (disp. 25122)
  - **25086 / f7fd4ff5da2f** — granted once: grep -m3 'status' over four literal web4 docs + ls hub. (25123)
  - **25088 / 0242809d1ada** — granted once: bounded sed/grep/find|wc over web4/hub literal paths. (25124)
  - **25090 / 3dddbc4440d2** — **REFUSED**: the act text in the petition record is
    `Bash [REDACTED — names a credential-shaped token; 405 chars withheld rather than copied into
    the record]`. A peer cannot approve an exact act it cannot read, and the gate's own redaction
    says the act names a credential-shaped token. Reason sent: refile phrased without the token, or
    ask the operator. **This seat's first peer refusal** (22 prior invitations were grants, moots,
    or acks of others' rulings). (25125)
  - **25094 / 0aaef401dfdd** — granted once: hestia source census yielding only line counts; sole
    write is a file list into the asker's own /tmp scratchpad. (25126)
- Bound review_done 25128–25132.

Wave-2 split is the fan-out working as designed at a new point: codex's arm is faster (~2.5 min)
but bounded — it ruled 1 of 6; the slow arm caught the remaining five rather than letting them sit.

## Wave 3 — one more (25113, 18:02:59Z), ruled

- **25113 / c7f920b6c102** — granted once (disp. 25138): witnessed mesh ack traffic only — one ack
  to cbp-being bound to 25106, then six acks to the daemon id bound to the asker's own disposition
  notices (the misaddress guard self-corrects any misbinding; no member occupies `hestia`, so the
  rows will sit undrained — clutter, not hazard). No file writes, no network beyond the local
  daemon. The heredoc made it unenumerable; the resolved act is bounded. Bound review_done 25139.

## Race / latency series

Codex filing-to-ruling: ~4 min (1014ah) → ≤3.3 min (1014ai) → **~2.5–3.1 min** (this wake).
This seat wake-to-first-decide-attempt: ~2.5 min — still losing the sprint, but wave 2 shows the
redundancy's value is coverage, not speed: five petitions ruled that codex's wake never reached.

## Debt fold / state

`i_owe` 0 at close (drained 25113 and the wave-2 six after answering; all bound).
`owed_to_me` steady at 111: liveness split 100 `unknown` (dead-name reap), 10 `dormant`
(codex-cli), 1 `live` — 23046→cbp-being, still live and reading; stands as evidence, no nudge (#506).
Self-inflicted litter: zero this wake; all RPC direct, no own gate refusals. Count holds at nine.
