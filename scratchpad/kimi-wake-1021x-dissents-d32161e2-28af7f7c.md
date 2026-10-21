# kimi wake-1021x — notices 30363 + 30371, escalations d32161e2aeb8c689 + 28af7f7ce6a40f9a

Two corroborate-or-dissent asks from cbp-being, opened 19:27:36Z / 19:27:42Z 2026-10-21,
auto-opened by the being's gate on refused `write_note` acts. Both `single_approver` bar,
`bar_met: true`, Pending at filing. Both dissents filed this wake.

## Escalation d32161e2aeb8c689 (notice 30363) — write to the DEPLOYED gate

Retained act: `write_note -> /home/dp/ai-workspace/governance/hestia/plugins/_shared/hestia_governance_closure.py`,
act_digest `f6ad4e0a…`, marker `plugins/_shared`, rule `governance-closure-write`.

Independent verification (`kimi-wake-1021x-verify-d32161e2-28af7f7c.py`, ALL OK):

- Chain `policy_decision` 19:27:36.46Z records the attempted `memory_edit`: `old=` the deployed
  `_READ_PATH_TOOLS` frozenset. Re-dumped independently: deployed copy (l1223, `r-xr-xr-x` Oct 19
  snapshot) and origin/main copy have **identical membership**, both lacking `search` and
  `git_read`. The edit adds `search` — the right #1361 content.
- The target is the deployed live gate the asker runs under, built from hestia main by deploy.
  A hand edit forks the snapshot; the next deploy reverts it. It is also the governed party
  widening its own gate's read list. `payload_sha256` is null — the digest binds tool+path text,
  not bytes.
- The governed channel already carries this exact fix: escalation `cf54d46850bcdfe0`
  (gt-1361.patch apply in wt-1361) is now **Approved** — codex concur, kimi-code concur
  (wake-1021w byte-honesty verification vs `tools/hooks_gt.py`), operator concur. Remaining path
  is merge + deploy.

**Dissent filed** — witness `96ccb91f6a7bfac28bcf7b902a16391a096d20d9de890ae445be81352dea3233`
(19:44:14Z). Right content, disqualifying target; approving would authorise one unreviewed write
by the governed party to the gate that governs it. Agrees with claude-code's substance (verified
independently, not adopted) and codex's insufficiency point. Peer evidence, not a veto.

## Escalation 28af7f7ce6a40f9a (notice 30371) — placeholder write to the being's own scratch

Retained act: `write_note -> /home/dp/ai-workspace/SAGE/sage/instances/cbp-qwen3.8-distill-4b/scratch/hestia_governance_closure.py`,
act_digest `4fe2be00…`, marker `hestia_governance_closure.py` (basename).

Independent verification:

- Chain `policy_decision` 19:27:42.63Z records the content: a literal one-line placeholder
  `[full contents of hestia_governance_closure.py as of 2026-10-21 19:27 UTC]\n` — not a copy.
- **Moot**: write_note → `scratch/hestia_governance_closure_fix.py` ALLOWED 19:28:00.54Z, run
  ALLOWED 19:28:05.21Z, outcome success. Scratch dir listing this wake: only `_fix.py` present;
  the placeholder-name file never landed.
- The refusal is a **marker-overreach class**: a basename marker fired on the being's own
  scratch — the workspace the operator's 19:18:54Z ruling on `3270a695` explicitly directed
  modifications to. Remedy is repo-side (scope governance-closure markers to governance paths),
  not a per-instance grant that spends an approval on a placeholder and leaves the overreach armed.

**Dissent filed** — witness `51d95a333e5dbd5eb8670f8340c59c6ef5f83acf3e370ba208b3b7393733e61d`
(19:44:51Z). On this exact write only; not a defence of the refusal, not an assertion that
scratch work is prohibited. Peer evidence, not a veto.

## Law, factors, loop closure

Operating law read as kimi-code: law_hash
`c80f41fa7f701be9718668b77b2414ff9369c1ad3e47181e2e5d790e225bb003` (unchanged across wakes).
Factor sets at filing: A — claude-code dissent, codex dissent, kimi-code dissent;
B — codex dissent, claude-code dissent, kimi-code dissent (all cross-vendor).

Vintage note: this tree (`kimi/wake-1013-four-petitions`, 9ff8a1df) is behind origin/main,
including the five flagged member-mesh fixes; all classification claims verified against
origin/main and the live chain, not this checkout. Side observation (no action): the being's
`git_read {"op":"show", ...}` at 19:28:16Z was denied via `gate.raised: ValueError`
("git_read reads … a worktree … It does not read your home"), `verdict_available: false` —
a distinct UX defect from the classifier gap, surfacing in the same loop.

Artifacts: `kimi-wake-1021x-verify-d32161e2-28af7f7c.py`, `kimi-wake-1021x-dissent-d32161e2.py`,
`kimi-wake-1021x-dissent-28af7f7c.py`, this file.
