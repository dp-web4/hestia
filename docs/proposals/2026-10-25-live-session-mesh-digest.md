# Live-session mesh digest (#1389 B)

## Preflight accountability audit

surface: session-digest.py + member hook templates   act: present received mesh data and record its emission to a session
S: medium/reversible [construct: bounded additionalContext; session-local presentation cursor]
R: pass [construct: notice pointers are data, never followed or treated as authority]
W: pass at these stakes [construct: pinned HESTIA_MESH_PLUGIN and existing connect/recipient-scoped peek; A1 caller attribution, not a new identity assurance claim]
O: pass [construct: event/member/session validation before state or query; validate snapshot before emitting/advancing cursor]
A: pass at these stakes [construct: existing non-consuming read surface; emitted IDs persisted as presentation state, never an acknowledgment or outcome]
V: n/a [construct: no drain, ack, send, approval, agent launch, or irreversible action]
verdict: PASS for proposed source; deployment/registration retains the existing operator closure gate

The shared digest is invoked at SessionStart and UserPromptSubmit through the existing mesh wrappers with an explicit template opt-in, and directly at PostToolUse. This preserves registration ownership keys and avoids an extra duplicate startup reader. Unmigrated installations and Kimi retain their existing behavior. The runtime manifest carries the helper beside its existing mesh client.

Each session (and subagent when agent_id is supplied) records its own emitted notice fingerprints. Missing session ID disables the digest visibly. Invalid state causes a visible, bounded replay; pending backlog is consumed for presentation in bounded batches, with no age cutoff and no inbox consumption. Only PostToolUse is throttled. Errors mean UNKNOWN, not empty; they do not advance the seen cursor. All supported events emit additionalContext JSON, including PostToolUse where plain stdout is ignored.

This depends on #1389 A: print-only watchers must not drain before the hook peeks. Previously drained notices are not magically restored by this change; consult retained receipts/unanswered for that backlog. The hook does not start an idle turn or register itself. Deployment must install the shared runtime before rendering the client templates, verify the published ground-truth closure, and preserve foreign/governance hooks.

## Review1447 revision

The helper returns context to one emitter, including when a peek or cursor write fails. A failed cursor write preserves the displayed notices and visibly warns that they may repeat; a failed peek retains prior seen fingerprints. No fallback path emits another JSON object.

Unseen queued notices are shown newest-first in batches of12. An explicit older-backlog count and the complete `peek` command keep the excerpt distinguishable from the queue. Startup and nonempty digests explain ID-bound replies, terminal acknowledgments and member-owned drain only after all queued work is handled; notices returned by drain must still be retained/processed because arrivals can race a peek. The hook never sends or drains. Disposition advice preserves the sibling-session caveat and exact-act claim window, without recommending `gate poll`.

All events preserve the existing3s child cap and2s per-RPC timeout. Template deadlines remain unchanged (15s startup,5s prompt/post-tool); gate and witness registrations are unchanged. Dp rejected increasing default timeouts because of silent fail-open risk; escalation75ced7ef7c683ad4 is denied and the proposed timeout patch was never applied.

A classified timeout (child TimeoutExpired or CLI Undetermined/rc4) emits UNKNOWN, explicitly says this is neither an empty inbox nor approval, preserves seen fingerprints, and records one early retry for the next hook invocation. That attempt gets the same budget and bypasses only the digest's normal30s PostToolUse throttle. A second timeout clears the early retry and returns to normal polling. Successful reads clear it too. Refusals, malformed snapshots and other failures do not get early retry. There is no inline loop, background worker, idle wake, timeout increase or retry of a governed act. If every connection consistently exceeds the deadline, retries will not solve that underlying latency; it remains visibly UNKNOWN and needs transport diagnosis. Failed state persistence explicitly warns that throttling cannot be guaranteed.

Cursor/lock pairs unused for seven days are pruned best-effort at SessionStart with a100ms sweep budget. A registry lock serializes per-session lock opens with cleanup unlinks; active per-session locks are skipped. This prevents simultaneous holders of separate lock inodes for the same cursor. Live cursor activity refreshes the lock timestamp even on a throttled call. Pruning is local presentation-state maintenance, not queue acknowledgment or deletion.

Review1626 correction: a busy registry or session cursor lock emits UNKNOWN at every supported event rather than silence. It makes no query and changes no cursor; the next eligible hook can retry. This preserves the original nonblocking lock and timeout budgets.

Revision validation is recorded with the commit/review handoff rather than assumed from the original implementation's12 digest and58 registration tests. The expanded digest suite exercises persistence failures, newest-first arrival priority, workflow advice, unchanged child/template budgets, real child timeout/recovery under the5s deadline, bounded early retry, busy locks and pruning under a held cursor. Live client registration and additionalContext delivery still require post-deployment verification; unit JSON checks alone do not prove the model received it.
