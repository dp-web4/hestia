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

Validation: 12 digest tests cover all notice kinds, reply IDs, independent sessions/subagents, retained backlog, cursor recovery, daemon ID reuse, failures/throttling, bounded strings, and real wrapper/client integration. All 58 registrar/installer tests pass, including isolated-home deployment and unchanged foreign/gate registrations. Legacy prompt/disposition, unreachable-inbox and mesh-install/drift checks pass. Published hook ground truth matches source, including the changed member-mesh dependency in Kimi's manifest (Kimi's registration behavior remains legacy).
