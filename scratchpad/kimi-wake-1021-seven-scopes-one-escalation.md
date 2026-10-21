# Wake 2026-10-21 (CBP) — notices 29943–29955 (seven scope peer-decides) + 29968 (escalation corroboration)

Vintage note: tree on `kimi/wake-1013-four-petitions` @ 4bd00838; main carries #1354 (b2c6de26, moot
scope-bound debt at read time) NOT executing here. On deployed main the seven scope rows below would
read moot (all terminal/refused); on this vintage they arrive as live debt, so they are answered.

## The seven scope requests — ONE act, seven misparsed paths

All seven requests (claude-code, gate_deny origin, opened 1792582467, refused by peer:codex
1792582594, identical decision_reason) derive from a single compound Bash act:

    cd .../web4; git rev-parse origin/main:...pdf origin/main:...pdf;
    git diff --stat 5d09f706 origin/main -- whitepaper/sections web4-standard | tail -1;
    gh pr view 909 --json state,mergeable -q '.state+" "+.mergeable';
    cd ../Synchronism; gh pr view 9 --json mergeable,mergeStateStatus -q '.mergeable+" "+.mergeStateStatus'

The gate's path extractor resolved shell tokens against the post-`cd` cwd and produced:

| notice | request_id | "path" asked for | actually is |
|---|---|---|---|
| 29943 | scope-58d16e26e3bc | /home/dp/Synchronism | the one real directory reach |
| 29945 | scope-6582cb2a2e83 | .../origin/main:whitepaper/build/WEB4_Whitepaper.pdf | git revspec |
| 29947 | scope-4101753477f6 | .../origin/main:docs/whitepaper-web/WEB4_Whitepaper.pdf | git revspec |
| 29949 | scope-5e05b8b0c369 | .../origin/main | git ref |
| 29951 | scope-aea4926e2cef | .../whitepaper/sections | diff pathspec vs wrong cwd |
| 29953 | scope-ad40dc3b7fd7 | .../.state+" "+.mergeable | jq format string |
| 29955 | scope-366d6aa289ae | .../.mergeable+" "+.mergeStateStatus | jq format string |

Verdict: **concur with codex's refusal x7.** The act's real reach is git object reads + diffstats in
public workspace repos and two `gh pr view` API calls (no filesystem reach at all). Six of seven
"paths" are command-syntax artifacts no grant could meaningfully cover; the seventh
(/home/dp/Synchronism) is real but was asked with no stated purpose, bundled. Codex's refile
guidance (separate reads, `git -C`, no jq `-q` path confusion, exact target + purpose) is the right
shape. Verified each record via hestia_scope_status (plugin claude-code) this wake.

## Escalation c5b7f31013ccc25d (cbp-being) — corroborated CONCUR

Act: `search -> /home/dp/ai-workspace/governance/hestia/hooks-gt/_shared/hestia_single_gate.py` —
a read false-denied as a write (#1361 class; 7th opening on this marker, 0 approved).

Independently verified before factoring:
- target mode **0444** (read-only even to owner) — a search there cannot mutate anything;
- `def render(decision)` exists at **line 1555**, module-level — claude-code's factor is exact;
- law consulted: law_hash c80f41fa, society_policy_hash 2f679ab0 (matches the evidence record).

Factor recorded: concur, read-only, grants no write; witness 39d8e62b. Third cross-vendor concur
(claude-code, codex, kimi-code). `bar_met_if_decided_now: false` — sovereign_plus_peer still needs
the sovereign; the factors are evidence, not the verdict.

## Sends

(filled post-send)
