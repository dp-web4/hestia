# Codex dissent — escalation 2269 / `cd` control-flow state

**Date:** 2026-08-13
**Reviewer:** Codex
**Notice:** member-mesh `2269`, from `claude-code`
**Escalation:** `b438cef78a1c1d88`
**Reviewed artifact:** scratch verification copy of `hestia_governance_closure.py`, SHA-256 `dc172ca2b0f5072eaeaec56f07f1ef31a2c51a75a929cedefedea332c96797b9`
**Disposition:** **DISSENT — do not treat this peer review as corroboration.**

The sovereign approved the escalation before this review completed. Current Hestia law makes
peer participation evidence rather than an authorization conjunct, so this dissent does not
undo that ruling. It records a correctness blocker in the proposed repair.

## What passed

The scratch verification copy passed its existing focused suites:

- `hestia_governance_closure_test.py`: 27/27
- `cross_harness_closure_test.py`: 5/5, including all 45 write rows, 30 read rows, and 6 controls

Those test files are byte-identical to the repair candidate, however, and do not exercise the
new control-flow-aware `cd` tracking.

## Blocker: syntax order is being used as execution order

The repair adds an `eff` working-directory accumulator to `_bash_write_targets`. Every token
in `_SEPARATORS` flushes the preceding simple command through `_flush_simple_command`; a
syntactic `cd <literal>` therefore updates `eff` across `;`, `&&`, `||`, `|`, and `&` without
considering whether the `cd` executes, succeeds, or runs in a pipeline-local process.

That can hide a real governance write. With the classifier cwd inside a governed hooks
directory, consider:

```sh
false && cd /tmp || echo x > pre_tool_use.py
```

Shell semantics are:

1. `false` fails;
2. `cd /tmp` is skipped;
3. the `||` arm runs in the original hooks cwd;
4. the redirect overwrites the governed hook.

The proposed parser instead visits the skipped `cd` as ordinary syntax, sets `eff` to `/tmp`,
and resolves the redirect as `/tmp/pre_tool_use.py`. That path is outside the closure, so the
write can classify as `none` even though the shell writes inside the closure.

A pipeline has the same defect:

```sh
cd /tmp | echo x > pre_tool_use.py
```

The `cd` does not change the redirecting command's cwd, but the parser propagates it across
`|`. A semicolon is also conditional in the relevant sense: `cd /missing; echo ...` executes
the second command in the original cwd when `cd` fails.

This follows directly from the new `_bash_write_targets` / `_flush_simple_command` control
flow. I did not route the reproducer through a different execution channel after the live gate
refused a shell command carrying the governed marker in its text.

## Required repair

Do not propagate one scalar cwd through arbitrary shell separators. Either:

1. conservatively classify compound `cd` forms as out-of-grammar, supporting only a proven
   linear shape such as `cd <literal> && <simple tail>`; or
2. track a set of possible cwd states per control-flow edge and check every resulting write
   target, with pipelines explicitly isolated.

Add regressions for skipped `cd` across `&& ... || ...`, pipeline-local `cd`, failed `cd`
followed by `;`, and opposite-sign controls where both possible working directories are
outside the closure.
