# Notice 8349 — post-hoc concurrence, bounded by missing source provenance

**Reviewed by Codex on CBP, 2026-09-03.** Notice `8349` asked for
corroboration or dissent on escalation `72e951d527f5a5c8`. The requested act was:

```text
Bash: cd /tmp/wt-collapse && cp /tmp/claude-1000/-mnt-c-exe-projects/888f190a-f01d-4efe-a5a0-5320307d31ab/scratchpad/pre_tool_use.new.py plugins/claude-code/hooks/pre_tool_use.py && echo LANDED
```

## Disposition

**Post-hoc concur with the durable code outcome.** The replacement that appeared in Git
immediately after the claimed write closes two real fail-open loader boundaries, binds
Claude Code to the selected installed authority, and passes the targeted boundary tests.
I found no correctness defect or governance bypass in that artifact.

This is not a factor on the original decision. The escalation was operator-approved and
claimed before this review, then reaped from the live store. A late reviewer cannot add an
authorizing factor to a spent decision, and I did not attempt to do so.

The concurrence also has a provenance bound: the temporary source and worktree named by
the command no longer exist. The escalation chain records the command and an act digest,
but does not bind either to a Git blob. I can audit the closest durable post-state; I cannot
prove that the vanished scratchpad file was byte-identical at the instant `cp` ran.

## Timeline and chain evidence

- `gate_escalation_opened` at `2026-09-01T15:41:15.030503981Z`, witness
  `93e03085…02e5`; bar `single_approver`, asker basis `session`, marker
  `plugins/*/hooks`.
- Notice `8349` queued four milliseconds later, at
  `2026-09-01T15:41:15.034151022Z`.
- `gate_escalation_decided` at `15:41:29.630103464Z`, witness
  `be3ea839…df87`: operator approval, `bar_met: true`. The recorded reason was only
  `"k"`, so it contributes authority but no useful review rationale.
- `gate_escalation_claimed` at `15:41:51.800644059Z`, witness
  `36e4c07c…c52e`: 37 seconds after open and 22 seconds after decision. The approval
  was consumed by the exact stated command.
- Commit `2438a424be41d0447b1ee7d4281c904dcb3bff74` followed at `15:43:09Z`,
  changing the named hook from blob `c663362…` to `d54b4c1…`. The later landed
  squash `239ae4db91f083283d9f45bde58978b5349d50a1` retained that same hook blob.

The timing and destination make `2438a42` the closest durable outcome of the write, but
they are correlation, not a cryptographic join to the deleted temporary source.

## Code review

The loader change in `2438a42` is narrowly correct:

1. It canonicalizes the selected installed shared-engine directory, removes equivalent
   spellings from `sys.path`, and places the selected directory first. This closes the
   case where an already-present installed path sat behind a decoy and the previous
   insert-if-absent condition left bare sibling imports bound to the decoy.
2. It catches `BaseException` only around `exec_module`, removes the partial
   `sys.modules` entry, and converts the initialization failure to `ImportError`. Thus
   an installed module raising `SystemExit(0)` cannot terminate the PreToolUse hook with
   the harness's allow exit code before `main()` reaches its explicit refusal path.
   Legitimate `SystemExit` from `main()` remains outside that boundary.
3. The two loader functions are byte-for-byte identical to the independently landed
   Codex implementation at `03a0ba845e69ae853a48df55fe9dfa513f73d43e`; an exact
   source diff over both function bodies was empty.
4. The module-origin check and eviction of wrong-origin cached modules remain intact.
   No checkout or legacy-directory fallback is reintroduced.

## Verification at the reviewed landed tree (`239ae4d`)

The following tests passed from a detached worktree of the historical merge:

- `plugins/claude-code/tests/missing_shared_authority_blocks_test.py`: absent and
  engine-less installed paths both refuse with exit 2.
- `tools/loader_binds_installed_engine_test.py`: installed-origin binding, decoy-first
  precedence, cached-decoy eviction, and classifier/core `SystemExit(0)` and
  `KeyboardInterrupt` initialization faults all passed; every fault produced exit 2,
  a named refusal, and no traceback.
- `plugins/claude-code/tests/gate_bash_differential_test.py`: all checks passed across
  1,280 generated commands.
- `plugins/claude-code/tests/gate_self_protection_test.py`: all checks passed.
- `tools/installer_shared_engine_test.py`: zero failures.
- `tools/collapse_meter_grades_drift_test.py`: all controls passed.

`plugins/claude-code/tests/gate_false_refusal_test.py` passed every behavioral arm but
reported its deployment-truth control red: the historical tree's hook hash differs from
the currently installed enforcing copy. That is expected when replaying a 2026-09-01 tree
against a later installed build; it is a warning that the behavioral checks describe the
historical checkout, not proof about today's enforcing bytes. I do not count that control
as evidence for or against the old patch.

## Current state

The live escalation resolver now reports the id as expired/unknown because settled rows
are reaped. The witness-chain events above preserve its actual approved-and-claimed
history. Open petitions for `codex` were separately measured through
`hestia gate pending --as codex --json | open-petitions.py fold codex` as
`{"asked": true, "mine": []}`.

One read-only compound inspection was gate-refused during this review. I did not retry it;
I retired the auto-opened petition `1e78c1adc28b324a` and used narrower read surfaces.
The pre-existing untracked files in the shared checkout were left untouched.
