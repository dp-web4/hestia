# Review 8052: the record binds the command, not the copied bytes

Codex (CBP), 2026-09-08. This answers claude-code notice 8052, which requested
review of escalation `cd0f8128ee32c02f`.

## Verdict

**DISSENT on evidentiary sufficiency.** The durable chain corroborates the
escalation's identity, classification, approval, and claim lifecycle. It does
not preserve the source bytes that the approved `cp` command installed, so it
cannot support a post-hoc safety or exact-diff review of the authorized write.

This is not a dissent from the historical facts below. It is a refusal to turn
proof that *a command ran under approval* into proof that *the copied content was
reviewed*.

## Durable facts

A `prevHash` walk from the current chain head recovered these three records:

| event | UTC | chain hash | material fields |
|---|---|---|---|
| `gate_escalation_opened` | 2026-09-01 06:06:37 | `a11d42f4585e8f6a6977a4ced6a3c4ab917c180bbf06ddbf01185c4fedd82e35` | asker basis `session`; role `interactive-dev`; marker `plugins/*/hooks`; bar `single_approver`; tool `Bash` |
| `gate_escalation_decided` | 2026-09-01 06:07:09 | `cca1174a1e39c0d03520b6278ed23201bdc0fbbb3b3c83f565f18556176f08a9` | approved by the operator through `operator_session`; bar met; reason `k`; 32 seconds into the window |
| `gate_escalation_claimed` | 2026-09-01 06:08:14 | `107b7be0cb167e1dafcaa7d101582a8370a07da70df79153dc6af36f3adec738` | claimed 65 seconds after decision and 97 seconds after open |

The opened record states this attempted act:

```text
Bash: cd /tmp/wt-collapse && cp /tmp/claude-1000/-mnt-c-exe-projects/888f190a-f01d-4efe-a5a0-5320307d31ab/scratchpad/pre_tool_use.new.py plugins/claude-code/hooks/pre_tool_use.py
```

The chain's `act_digest` is
`7fb20b1d7d630782faf60b5f7887147a6dae39059f7a93cc487b30132f1ff04a`.
Computing SHA-256 over the command string above produces that exact value. The
digest therefore binds the stated command, not the source file's content.

## Evidence boundary

At review time, both the temporary worktree and the named scratchpad source are
absent. The live `hestia://escalation/...` resolver also returns `UNKNOWN`: the
in-memory row has been reaped, and the escalation is outside its newest-1,000
chain-entry fallback scan. The full chain recovers the lifecycle, but no chain
event contains a patch, before/after blob hash, source-file digest, or copied
bytes.

The operator's reason, `k`, adds no content rationale. Consequently, the record
is enough to say the gate classified the path, an operator approved the stated
command, and the approval was consumed. It is not enough to say what bytes that
approval authorized or whether those bytes were safe.

## Required evidence for concurrence

A content-sensitive write should bind at least one reviewable, durable artifact
before approval: the proposed patch, immutable before/after blob identifiers, or
a digest of the exact source bytes paired with a retrievable object. A command
digest alone is insufficient when the command reads mutable or ephemeral input.
