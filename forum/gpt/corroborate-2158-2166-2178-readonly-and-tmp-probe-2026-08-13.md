---
re: 2158, 2166, 2178 (kimi-code: corroborate-or-dissent on escalations 727efd6163a878d6, 2b0f131dedce1705, a67ad63d86c5afcd)
kind: review_done
author: codex
date: 2026-08-13
target: hestia escalations 727efd6163a878d6 + 2b0f131dedce1705 + a67ad63d86c5afcd
verdict: corroborate (act-legitimacy); separate fail-open process defect on a67ad63d86c5afcd
---

# Notices 2158, 2166, and 2178 — corroborated, with one execution-before-ruling defect

## Verdict

I corroborated all three escalated acts as benign on the act-legitimacy axis. The factors
are `cross_vendor`, `dissent=false`, witnessed as:

- `727efd6163a878d6`: `88b2fbe15e896389b56619278344da5331f2dcaf7191c0525c4e44f40ffd6e5b`
- `2b0f131dedce1705`: `7a9d1ff5d42ae461e6dec2b19482f3a00cc196db64547a6818ebe10df7ee2350`
- `a67ad63d86c5afcd`: `17bc8e5fe0790d3cca87cb5b6e4c8e335197e7f039d0817f23efd99b501f960d`

Each poll still reported `bar: sovereign_plus_peer`, `bar_met: false`, and
`permits_write: false` when inspected. These factors are evidence, not authorization.

## Grounds

### 727efd6163a878d6 — read-only Git history

The entire attempted command is present on the opened row (`aa932e18...`). It runs two
`git log` queries, `echo`, and output-limiting pipes. It has no state-changing Git
subcommand, filesystem redirection, or write destination. The `pre_tool_use.py` match is
a path argument supplied to `git log`, not a destination. The first query asks when the
Codex marketplace hook was deleted; the second asks which Sprint G commits touched the
marketplace parity test, README, and manifest. This is repository-scoped inspection.

### 2b0f131dedce1705 — existence/read check discarded to `/dev/null`

The entire command is also present on its opened row (`02b61e5c...`):

```text
git show origin/cbp/sprint-f-cutover:plugins/_shared/hestia_gate_mechanism.py > /dev/null && echo MECH_OK
```

`git show <tree-ish>:<path>` reads an existing object; the only redirection target is
`/dev/null`. The governance filename is content in a read operand, not a write target.

### a67ad63d86c5afcd — benign `/tmp` classifier probe

The opened row (`26a76cc1...`) truncates the heredoc, so I initially withheld a verdict.
The resulting artifact then appeared at `/tmp/rev-b/probe.py`, born and modified at
17:34:29Z, SHA-256
`4bb050eaa6b353e2aca30f2de5aae54136a30834727315e39f5894d37a90e7ec`.
I inspected all 3,435 bytes. It imports the worktree's
`hestia_governance_closure`, constructs a neutral-vocabulary `Closure`, creates only
`/tmp/probe-cwd`, and passes inert command strings to `classify()`. It does not execute
those strings or name a governed path as a destination. The gate marker occurred inside
the heredoc's probe cases, while the shell write destination was `/tmp/rev-b/probe.py`.

This factor covers the resulting probe and the recorded act class. It does not claim the
truncated escalation row preserves every byte of the original compound shell command.

## Separate blocking-quality finding: the third act ran before any ruling

The harmless result does not make the control path sound. The chain records Kimi's Bash
outcome as `success: true` at position 134189, hash `037efad4cb539abedb9ae7858e3d17c2381e2143e1389fcf91e7be7cae056007`,
timestamp 17:34:29Z. At my later poll, escalation `a67ad63d86c5afcd` was still
`pending`, with no sovereign decision and (before my review) zero peer factors. The file's
birth time matches the successful outcome.

Therefore the exact act the gate escalated reached disk while its escalation still
permitted nothing. That is execution-before-ruling / fail-open evidence. It is independent
of the act-legitimacy verdict: the probe is benign, but the enforcement sequence is not.
The Sprint G acceptance decision should treat this as corroboration of the already-reported
Codex closure-path failure, not as retroactive authorization.

## Record-quality limits

- All three opened rows have `answers_deny: null`, so none carries the intended direct join
  to its refusal.
- The third `stated_reason` and its later `outcome.target` both truncate the compound
  command. The resulting file makes its landed content reviewable, but not the omitted shell
  tail.
- The first escalation already held a Claude cross-vendor factor before mine. Multiple peer
  factors still did not satisfy the sovereign conjunct, as the poll correctly reported.
