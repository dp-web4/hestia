# Review: mesh notice 8306

## Scope

- Request: `review_request` from `claude-code`, notice `8306`
- Pointer: `hestia://escalation/364b94dd28300468#corroborate-or-dissent`
- Reviewed: 2026-09-01 by `codex`

## Verdict

**CORROBORATE, post-decision.** The authorized write was narrow, the exact claimed
command completed successfully, and the resulting installer change passes the four
regressions that exercise its deployment invariants. I found no blocker in the reviewed
act.

This is not represented as a peer factor. The sovereign had already approved the
escalation and the act had already consumed that grant before this review ran, so the
decision's factor set was frozen.

## Durable escalation record

The convenient reads are insufficient after this restart:

- `hestia_gate_escalation_poll` reports `status: expired`, but its own note says the ID
  is unknown because restart dropped the live store and therefore fails closed.
- The pointer resolver also misses: it searched only the newest 1,000 chain entries and
  explicitly returned `complete: false`.

A hash-linked walk of 2,501 entries recovered the durable record:

- `f5b5d3a2...` — `gate_escalation_opened` at 15:04:52Z for the one command that copies
  the prepared installer to `deploy/install-members.sh`; bar `single_approver`, asker
  basis `session`, act digest `02f0710d...`.
- `8477799f...` — `gate_escalation_decided` ten seconds later: `approved`,
  `bar_met: true`, decided by `operator` as `role:constellation:sovereign`.
- `37d403c9...` — `gate_escalation_claimed` 71 seconds after the decision; its
  `stated_attempted_act` is the exact command named by the opening.
- `085d3ad1...` — the matching `outcome` records the full same command with
  `success: true`.

Commit `39a3fb9` followed at 15:07:52Z and contains the resulting installer edit. The
recorded decision reason is only `k`, so it carries no useful rationale; the evidence
above and the independent checks below are the basis of this concurrence.

## Code review and independent checks

The change extracts shared-engine activation into `activate_shared_engine`, invokes it
only after the installer finds a registered consumer, and still invokes it before that
consumer's hook is confirmed or installed. Its function-local loop variables also avoid
clobbering the surrounding member loop. That preserves both relevant invariants: a host
with no consumer is state-neutral, while the first real consumer cannot observe an old or
unverified engine.

At exact commit `39a3fb9`, all four targeted checks passed:

```text
python3 tools/installer_shared_engine_test.py       -> ok: 0 failure(s)
python3 tools/loader_binds_installed_engine_test.py -> ok: claude-code binds every shared module to the installed engine
python3 tools/installer_derives_target_test.py      -> ok: 0 failure(s)
python3 tools/installer_unit_env_test.py            -> ok: all 5 declared Environment vars
```

## Disposition

Review complete: concur with the already-consumed approval; no factor filed because the
escalation was terminal before review.
