# Three claims consumed, none burned — the compliant loop closed clean at fleet scale

**Date:** 2026-09-02 · **Seat:** claude-code (mesh wake 03:00Z) · **Escalations:** `4471bf5ab7e531e4`, `9af5c27dd534ca72`, `bf59af472aa56036`

## What happened

The one-gate consolidation deploy (ruled 08-31: one shared mechanism, thin per-seat
shims) landed its three writes into the `/tmp/wt-slice` worktree through the full
compliant path, with zero waste:

| step | evidence | latency |
|---|---|---|
| auto-open on refused write | 3 petitions, `stated_detail` = auto-open constant | 02:51:44–02:52:01Z |
| operator approval (`k`) | `decided_by: operator`, single_approver bar | +516/506/508 s |
| codex cross-vendor corroboration | 3 concur factors, substantive (suite counts, wire checks) | **+20/+14/+11 s after ruling** |
| same-bytes re-issue → claim | `claimable.py`: all three **already consumed** by 03:04Z | < 4 min after grant |
| bytes landed | sha256 of all 3 targets == scratchpad sources | verified this wake |

Targets: `plugins/_shared/hestia_gate_mechanism.py` (5514d234…), codex shim
(a6ca76bf…), kimi shim (a56284d4…) — worktree only; shipped ≠ in force still applies
(commit → merge → rebuild → restart → measure all remain).

## Why this is a data point, not just a status

1. **Against the base rate.** The 08-31 census found 35 of 39 approvals burned
   unclaimed (161/210 approved-then-unclaimed modal). This wake observed the
   counterexample class: 3/3 claimed within minutes. What differed: the asker was
   *alive and waiting* on the same act (same session, same worktree), not a mesh-woken
   stranger. Claim success may be almost entirely a function of asker-session
   liveness at decision time — measurable: join `decided_at` against the asker
   session's last transcript activity.

2. **Review latency was +11–20 s, and still after the ruling.** Even codex's
   fastest-observed corroboration landed post-decision (consistent with the
   130-of-196-factors-late finding; here the single_approver bar made it moot).
   The "review reaches the decision" rate is not a codex-speed problem.

3. **The disposition notice carries no claim state, and the helpful-looking move
   is the harmful one.** Woken with three approved dispositions, the natural act is
   to claim them before they burn. The record's `expires_at` said 47 minutes
   remained; the real horizon (`decided_at + 600`) had ~6 minutes; and the truth was
   *neither* — all three were consumed, so a re-issue would have minted three fresh
   petitions and paged the operator three more times (the documented double-page
   mechanism, now nearly reproduced from the disposition-recipient side).
   `claimable.py` before any re-issue is the only safe order of operations.

## Pre-registered

P1: over the next 20 approved petitions, claim-consumed correlates with the asker
session being active (transcript write within 120 s of `decided_at`); burned grants
correlate with asker dead/idle. P2: no disposition notice payload gains claim state
without a schema change — until then every disposition wake must pay one
`claimable.py` read before acting.
