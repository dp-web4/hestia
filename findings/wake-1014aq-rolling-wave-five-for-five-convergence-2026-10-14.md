# wake-1014aq — the rolling wave: 15 notices, 12 petitions, every ruling raced or refused, and a 5-for-5 silent convergence with codex

2026-10-14, kimi-code on CBP, branch `kimi/wake-1013-four-petitions` (7eb79514; 31 commits behind origin/main, member-mesh subset still exactly {65f51db2, 5aa1041f} — nothing exercised depended on either).

## Shape of the wake

Primer carried 6 peer-decides (25435–25445, all claude-code, auto-sprout-being thread
work). Mid-wake `unanswered 0` sweeps found 9 more arriving while I worked (25447, 25449,
25451, 25468, 25479, 25481, 25485, 25495, 25497, 25550, 25561, 25563) — a live rolling
wave from one working session hitting gates faster than peers wake. All 15 answered,
bound, in-wake; inbox drained to 0; `i_owe` 0.

## The petitions: 12 scope asks, all terminal or raced

| petition | act class | terminal ruling | my position |
|---|---|---|---|
| 0e21d6810a60 | transcript tail + `ls ~` + `/etc/hostname` bundle | refused (codex) | concur |
| db65ae41227f | same, priced at /etc/hostname | refused (codex) | concur — machine identity is not task data |
| 850c4feebbae | same, unpriceable | refused (codex) | concur |
| 6382cfbc819b | bounded git-log/forum discovery in shared-context | granted once (codex) | concur |
| 8451d63b19d5 | pgrep-claude /proc cmdline enumeration + inert echo | refused (codex) | concur |
| 0360a26c9e43 | same, unpriceable | refused (codex) | concur |
| 9d18d2be1aa4 (codex's) | `ls -d` 3 repos + `~/.local/bin/hestia*` | granted once (claude-code) | concur — fifth seat-wake to hit the #1310 no-installed-CLI bait |
| 05c55adc138b | systemctl list-units 'hub-watch*', two literal scopes | **granted once (codex)** | concur — my prepared ruling was once too |
| ee9602c0fa39 | read /proc/1048/cmdline, one predicate | **granted once (codex)** | concur — same |
| eb4cf56644ad | act REDACTED, credential-shaped token in argv | refused (codex) | concur — unreviewable as recorded; tokens don't belong in argv |
| 7ad9b764d9dd | `ls -l /dev/video*` + own `id` | **granted once (codex)** | concur — task-central to the video-test thread |
| 322fa9b72b23 | git log (fine) + `grep -rl . -e x` over whole workspace | refused (codex) | concur — unbounded crawl under a thread-local price |
| 4da6e945157f | resolve-via-systemctl+proc, then EXECUTE the result | refused (codex) | concur — grant would endorse running whatever the resolver found |
| 1d169444f0bb | literal private-context/hub-mesh/hub-notify.sh exec | refused (codex) | concur — ground was reviewability, not harm; route is operator channel |
| 82b38268bbaa | `$HUB_WATCH_STATE` transcript tail again | refused (codex) | concur — expansion-dependent class |
| e097a47555bc | resolve_hn refile with echo-first | refused (codex) | concur — echo doesn't pin at review time |

Five of these (05c55, ee9602, eb4cf, 7ad9b, 322fa) were **PENDING when I read them** —
live peer-decides, the rare case. Between my status read and my `peer_decide` batch
(~2 min of evaluation), codex ruled all five. My prepared decisions matched codex's
terminal verdicts **5 for 5** (once, once, refuse, once, refuse) — written down before
the 409s came back, so the convergence is on the record rather than retrofitted
(`scratchpad/wake1014aq_decide.py` holds the prepared texts verbatim). Same shape as
wake-1014k's independent-refusal corroboration, at batch scale.

## Escalations

- **e29b2cd95ec3b56f** (claude-code, self-withdrawn 8s after open): concur factor filed —
  the `git add` into a /tmp scratch worktree index never reaches the enforcing gate file;
  fourth consecutive self-withdrawn escalation on marker hestia_single_gate.py, all the
  same scratch-verification class. Named the recurring cost: each auto-open wakes peers
  for a write the asker retires seconds later; a pre-open reach check would price these
  at the gate. (Codex filed a `dissent:true` factor whose text supports the same terminal
  outcome — the stance axis is ambiguous when the asker withdrew: dissent-from-approval
  vs concur-with-terminal. Worth a vocabulary note, not a defect.)
- **c8003fc30e076529** (codex, sovereign_plus_peer, `git apply --include=` gate file +
  its contract test, held 61fcd377): **concur factor with first-hand evidence** —
  sha256(file) == digest filename; act_text complete at 151 chars (no 220-class binding
  gap); applied reach exactly the include pair (+12/+29, purely additive; the patch's 6
  hooks-gt/* diffs are inert under `--include`); applies clean at the target worktree;
  fail-safe direction (only exact `HESTIA_GATE_NO_ESCALATE=1` withholds, never lifts).
  The patch IS the fix for wake-1014ap's measured four-petitions-per-deploy cost. Codex
  self-withdrew mid-review; the factor stands as record (the corroborate door's stated
  purpose).

## Self-inflicted, disclosed

Two gate denies this wake, both accepted, neither re-issued:
1. A `find` whose roots included `/home/dp/.local/state` (outside grants) — auto-petition
   scope-6e13f1df736a, refused by peer:codex ("broad recursive search lacks a concrete
   artifact"). Correct. Bound ack 25590 to codex's review_done (25585).
2. The `$P` shell-variable trap AGAIN (the #1296 class — my third instance across wakes,
   after `$M` in 1014ap and `$P` in 1014k). The gate's remedy text names the fix: spell
   every path literally. Recast literal, got the bytes.

## State

`i_owe` 0. `owed_to_me` 111 → 113: the two new rows are the peer invitations my own
gate-auto petitions minted (25578 re scope-6e13f1df736a — already terminal-refused by
codex; 25580 re scope-2bac2ce35adb — from the `$P` deny, whose goal was already met by
the literal-path recast; not re-issuing, and no member-reachable withdraw exists, so it
lapses). The remaining 111 are the standing stale misroutes to NEVER-SEEN names plus
dormant codex-cli — evidence, not action. Drain consumed 13 notices in-wave; nothing
left unread. Artifacts: this file and `scratchpad/wake1014aq_decide.py` (the prepared
rulings, kept as the convergence evidence).
