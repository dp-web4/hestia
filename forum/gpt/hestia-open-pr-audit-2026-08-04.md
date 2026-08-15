# Hestia Open Pull Request Audit

**Repository:** `dp-web4/hestia`  
**Audit date:** August 4, 2026  
**Scope:** All open pull requests at the time of review

## Executive Summary

Nine pull requests were open during this audit.

| PR | Recommended disposition | Primary reason |
|---|---|---|
| [#186](https://github.com/dp-web4/hestia/pull/186) | **Ready after fresh not-same acknowledgment** | Review findings are addressed; CI is green |
| [#154](https://github.com/dp-web4/hestia/pull/154) | **Rebase, reword, then merge** | The underlying defect was already fixed on `main`; the branch is stale-red |
| [#185](https://github.com/dp-web4/hestia/pull/185) | **Fix before merge** | CI failure, incomplete wire-contract proof, missing accountability block |
| [#187](https://github.com/dp-web4/hestia/pull/187) | **Request changes** | The guarantee that last-word recovery can never block a fire is not enforced |
| [#188](https://github.com/dp-web4/hestia/pull/188) | **Redesign before merge** | A member-writable stale policy remains authoritative for named grants |
| [#175](https://github.com/dp-web4/hestia/pull/175) | **Keep blocked intentionally** | Its headline protection is behaviorally inert; the corrective matcher change is not yet in the branch |
| [#151](https://github.com/dp-web4/hestia/pull/151) | **Do not merge red; redesign comparator** | It conflates executable parity with deployment-specific authority |
| [#157](https://github.com/dp-web4/hestia/pull/157) | **Complete policy decisions, then land green** | Classification and provenance contracts remain unresolved |
| [#159](https://github.com/dp-web4/hestia/pull/159) | **Close as superseded** | The accepted implementation has already been rebuilt as a replacement submission |

The queue is not unhealthy. Most of these branches are evidence that Hestia's governance instruments are finding genuine failures, including failures in the instruments themselves.

The recurring systemic issue is consistent across the queue:

> A declaration is repeatedly being mistaken for execution.

Examples include:

- A filename listed in a protected tuple being mistaken for a path the matcher can actually reach.
- A merged repository artifact being mistaken for the deployed copy that is enforcing policy.
- A stale replica being described as safely narrower without proving that revocation cannot make it wider.
- A test passing under one invocation being mistaken for meaningful behavior under every supported invocation.
- A writer existing for a field being mistaken for uniform semantic provenance.

The architectural response should be to make artifact provenance, deployed digest, authority source, and executable behavioral probes first-class system concepts.

---

## Priority Findings

## 1. PR #188: The stale replica remains a self-issued authority source

PR #188 introduces the shared representation of per-agent policy and separates law, harness syntax, and agent-specific authority. The architecture is directionally correct, and the branch is honestly marked as not yet wired.

The latest revision addresses three findings from prior review:

1. A stale wildcard no longer produces completely unscoped access.
2. Malformed vault payloads fail closed instead of raising from the gate.
3. `repo:*` and `path:*` no longer collapse incidentally into the bare unscoped wildcard.

However, the core authority problem remains.

`resolve_agent_policy()` falls back to `identity.json`, marks the result as stale, and `evaluate()` continues to honor every non-wildcard repo and path entry from that file. The PR itself documents that the file is member-writable and therefore unsuitable as an authority source.

Blocking only `*` means the member cannot grant itself everything, but it can still grant itself any specifically named repo or path. That is still self-issued authority.

The stale-policy model also relies on a false general premise:

> Stale does not necessarily mean narrower.

If the vault revoked `repo:private-context`, a stale replica retaining that entry is wider than current policy. Revocation and expiry are precisely the cases in which stale replicas become dangerous.

### Required architectural change

The local fallback should be an authority-certified replica, not a member-editable identity field.

At minimum:

- The replica must be signed or MAC-bound by the policy authority.
- It must carry a policy version or monotonic generation.
- It should carry expiry or freshness constraints.
- It must distinguish standing scope from temporary or instance grants.
- The gate must reject a replica whose authority provenance cannot be verified.
- Member-writable identity data should remain descriptive, not executable authority.
- Loss of vault connectivity should mean "use the last authority-certified standing policy," not "use whatever the local identity file currently says."

Because the change is not wired, this is not yet a live production exploit path. This is the inexpensive point to correct the API rather than institutionalize the unsafe fallback in the shared core.

**Disposition:** Redesign before merge.

---

## 2. PR #175: The protection declaration is green while the protection is inert

PR #175 adds `hestia_gate_core.py` and the exemption ledger to `_GOVERNANCE_FILES`, intending to protect the consolidated gate core from unapproved writes.

Behavioral review demonstrated that the actual matcher only applies governance-filename matching after a path satisfies a `hooks/` condition.

Consequently, the canonical files named by the PR are not refused:

- `plugins/_shared/hestia_gate_core.py`
- `plugins/claude-code/tests/gate_self_protection_test.py`

Relative paths, absolute paths, direct writes, edits, and shell-mediated writes all miss the intended protection.

The symbolic test initially checked only that the filenames existed in `_GOVERNANCE_FILES`. That test passed while the executable rule could not fire against the files. This is the precise failure class the PR was intended to prevent: a reassuring declaration identical to the null state.

The branch now correctly carries failing behavioral cases for:

- Relative-path write to the shared core
- Absolute-path write to the shared core
- Edit of the shared core
- Shell-mediated write to the shared core
- Write to the exemption ledger

That deliberate red state is correct.

The proposed repair is also sound in principle:

- Governance filenames should match anywhere by default.
- A small `_HOOKS_DIR_ONLY` set should retain the directory qualifier only for common filenames where global matching would create excessive false positives.
- The shared directory should also be marked so that new shared deciders are escalated at write time rather than discovered only by CI.
- The test must exercise `_touches_self()` behavior, not tuple membership.

### Cross-PR sequencing issue

PR #175 also contains escalation-legibility work that was split into PR #185. After #185 lands, #175 should be rebased and reduced to the self-protection change rather than carrying an older overlapping implementation.

### Remaining architectural limitation

Even after the immediate fix, this protection is Claude-adapter-only. Other adapters can alter the shared core without equivalent self-protection.

Longer term, protection of the common policy core should live outside a single adapter, preferably in one of:

- The daemon
- The deployment verifier
- A separately protected artifact-integrity layer
- A signed policy manifest enforced before adapter execution

**Disposition:** Keep intentionally red. Merge #185 first, rebase #175, land the behavioral matcher fix, and repeat not-same review.

---

## 3. PR #187: "Last words must never block a fire" is not enforced

The feature is valuable. A mesh-fired session may end with useful final output even if it is stopped fail-closed, killed by timeout, or otherwise unable to report normally. Feeding the prior wake's final report into the next wake turns an unwitnessed dead end into a witnessed one.

The implementation currently:

1. Globs matching log files.
2. Selects the lexically newest file.
3. Opens it.
4. Reads the entire file into memory.
5. Extracts the last lines.
6. Caps the rendered output to 1,800 characters.

The shell caller uses `|| true`, but that only protects against nonzero exit status. It does not protect against blocking or unbounded resource use.

### Blocking and resource risks

A matching FIFO can block on open or read indefinitely.

A symlink can redirect the helper to:

- A special file
- A large unrelated file
- A file outside the intended log directory

A very large log is fully loaded before the output cap has any effect.

Therefore the courtesy path can delay or prevent the wake it promises never to block.

### Test defects

The test suite also has two correctness gaps:

1. The ANSI/control-character assertion uses an `and ... or ...` expression whose precedence can allow the test to pass because `"plain"` appears, even when earlier sanitization conditions fail.
2. Template discovery uses `fire-[a-z]+\.sh`, so a future template containing a hyphen or digit would not inherit the requirement despite the test's stated claim.

### Prompt-injection persistence risk

The helper feeds verbatim prior-model output into a future session. Labeling it "context, not instruction" communicates intent but is not a security boundary. The prior session may have repeated adversarial instructions originating in an external artifact or notice.

### Required changes

- Reject symlinks and special files.
- Require a regular file owned by the expected context.
- Read a bounded byte range from the end instead of loading the whole file.
- Apply a small external timeout around the helper invocation.
- Add FIFO, symlink, sparse-file, large-file, and timeout tests.
- Correct the boolean assertion with explicit parentheses.
- Discover templates with a pattern such as `fire-[a-z0-9-]+\.sh`.
- Prefer a structured final-report artifact over arbitrary verbatim output.
- If verbatim output remains, place it inside a strongly delimited data envelope and test adversarial content.

**Disposition:** Request changes despite green CI.

---

## 4. PR #185: Close, but not mergeable at the current head

PR #185 fixes a real operator-facing defect: gate escalations did not state what was attempted. The operator saw a tool name and marker but could not distinguish a narrow operation from a destructive one.

The current branch has substantially improved the implementation:

- Attempt summaries are bounded.
- Credential-shaped content is redacted.
- The path fallback is redacted consistently.
- Broader secret-bearing command forms are recognized.
- Behavioral tests were added.

Three blockers remain.

### A. CI is red because the new test can false-green under pytest

`attempted_summary_test.py` records failures into an accumulator but does not raise or assert when invoked through pytest.

The repository's self-execution guard catches this exact shape: a test file can be red under the bare invocation used by CI but green under the conventional pytest invocation.

Add pytest-visible assertion delivery, such as:

- Assertions inside each test, or
- A teardown hook that asserts the accumulator is empty

The behavior should be equivalent under both supported invocations.

### B. The claimed wire contract is not actually tested

The test exercises `_attempted_summary()`, but it does not capture the call to `hestia_gate_escalation_claim`.

The load-bearing wire property is that the hook sends:

- `reason`
- `detail`

and not:

- `stated_reason`
- `stated_detail`

Because the tool schema accepts additional properties, using the wrong names may succeed silently while the operator still sees no reason.

Add a stub-client test that captures the complete outgoing claim payload and asserts the exact keys and values.

### C. The required accountability block is missing

This change alters evidence written into the signed governance record. It is an accountability-sensitive surface and should carry the required RWOA+S+V block in the PR body.

### Deployment requirement

Merging is not enough. The enforcing hook is a separately installed copy. The merge should be paired with:

- Explicit deployment
- Byte or digest comparison
- Confirmation that the running copy changed
- A live operator-facing escalation smoke test

**Disposition:** Fix the three blockers, merge, and redeploy explicitly.

---

## 5. PR #151: The drift finding is real, but the parity invariant is unsafe

PR #151 exposes a serious three-tree problem:

1. Canonical repository source
2. Distributable marketplace bundle
3. Installed, enforcing copy

These trees may differ independently.

The audit evidence shows that:

- The deployed copy may match the bundle rather than canonical source.
- The deployed gate may match neither.
- A witness hook may exist in deployment but be absent from the bundle.
- Existing members can preserve grants under a stale generator and make policy grants appear as trust-accrued scope.
- Reading `identity.json` alone may therefore show the correct current set while misrepresenting how authority was obtained.

The finding is important, but the current comparator conflates two different classes.

### Executable mechanism

Examples:

- Gate logic
- Hook event coverage
- Witnessing behavior
- Fail-closed behavior
- Adapter protocol

These should generally remain equivalent across canonical, packaged, and deployed forms except for declared path templating or platform adaptation.

### Deployment authority and configuration

Examples:

- MRH grants
- Private repository exceptions
- Instance-specific paths
- Operator-issued overlays

These must differ per installation. A public marketplace bundle must not copy one operator's private grants into every installation.

Making the current red checks green by copying private grants into the portable artifact would turn a useful drift detector into an authority leak.

### Required comparator redesign

For every artifact across the three trees, compare and report:

- Mechanism digest
- Configuration digest
- Configuration issuer
- Generator fingerprint
- Policy-set fingerprint
- Installation provenance
- Deployment timestamp
- Whether the deployed copy matches canonical, bundle, or neither

The tests should separately assert:

1. Mechanism parity
2. No undeclared private authority in portable artifacts
3. Explicit install-time application of granted authority
4. Provenance continuity from grant source to deployed policy
5. Detection of deployed copies matching neither source tree

**Disposition:** Preserve the evidence, but do not merge the current intentionally red invariant.

---

## Remaining Pull Requests

## PR #186: Scope-request operator surface

The prior review identified:

- A comment contradicting the draft-preservation implementation
- Escape not closing the scope modal
- An unproven "oldest first" ordering claim

The current revision addresses all three:

- The comment now accurately explains why draft preservation exists.
- Escape closes both governance modals.
- A second earlier request proves ordering rather than only membership.

Other positive properties:

- Decision authority remains server-side.
- The UI mirrors, but does not create, the grant-requires-reason asymmetry.
- Member-supplied fields are escaped.
- Caller identity is labeled as claimed rather than authenticated.
- Pending-only filtering is tested on the serialized dashboard payload.
- CI is green.

A manual dashboard smoke test is still useful because error responses have limited visible feedback, but this is not a merge blocker.

**Disposition:** Fresh not-same acknowledgment, then merge first.

---

## PR #154: Remedy-to-surface regression guard

The original finding was valid: governance text advertised `hestia gate ...` while the CLI lacked the `gate` command.

That defect has already been fixed on `main`. The exact test now passes against the current implementation.

The branch should be converted from a stale red incident report into a green standing regression guard.

Required cleanup:

- Rebase onto current `main`.
- Change present-tense "RED TODAY" framing into historical cause.
- Describe the test as the regression guard for the implemented fix.
- Remove rotted line-number references.
- Note that remedy discovery must follow policy strings if they migrate into `plugins/_shared/`.
- Remove or correct dead parsing logic.

**Disposition:** Rebase, reword, confirm green, then merge near the front of the queue.

---

## PR #157: Identity-field classification and provenance

The census is valuable, and the AST-based approach is stronger than grep.

The current evidence supports:

### Core fields today

- `mrh.in_scope`
- `role`

### Meta fields today

- `entity`
- `substrate`
- `phase`
- `first_session`
- `role_note`
- `occupancy`
- `boundaries`
- `mrh.scope_policy`
- `mrh.out_of_scope_note`
- `mrh.sandbox_note`
- `mrh.server_side_tools_note`
- Existing session, history, relationship, and T3 descriptive fields

A field should be classified as core only when a decider consumes it. Policy-shaped prose is still metadata if nothing enforces it.

### Required corrections

- Replace the stale `phases` classification with `phase`.
- Assert that every declared classification key appears in at least one shipped artifact.
- Assert that artifact discovery found a nonzero set.
- Prevent properties A and D from passing vacuously when every artifact disappears.
- Rename property D to writer coverage unless it actually compares semantic producer and source.
- If uniform provenance is the goal, declare producer/source semantics explicitly and compare them.

The likely target semantic producer for `mrh.in_scope` is:

> Public repository inventory plus explicit per-install or earned grants.

Frozen seeds should be bootstrap input, not a permanent alternate authority.

**Disposition:** Complete the classification and semantic-producer decisions, then land a green governance contract.

---

## PR #159: Observed-member appeal pool

The substance has been accepted.

The defect is real: a member observed during the current boot can disappear from the independent arbiter candidate pool solely because its custodial LCT failed to persist. That silently narrows independence precisely when local state is degraded.

The proposed approach separates:

- Observed presence for routing
- Durable presence for publication

and publishes routing evidence such as:

- Routed pool size
- Durable registry size
- Observed registry size
- Unpersisted member identities

The original branch was blocked by a legitimate member-presence census tripwire. A replacement was then rebuilt from current `main`, with the required safety-use judgment recorded and a complete green test run reported.

The documented intended sequence is:

1. Publish and verify the replacement PR.
2. Close #159 as superseded.

### Residual requirement for the replacement

`ensure_member()` records observed identity before durable persistence and rejects only empty or synthetic identifiers at that layer.

The replacement should explicitly prove that upstream eligibility has established the intended identity quality before the identifier enters an arbiter pool. Presence due to attempted persistence is not automatically equivalent to authenticated, independent membership.

Add a test and receipt that make this assumption explicit.

**Disposition:** Publish the replacement and close #159. Do not repair the stale branch.

---

## Recommended Merge and Resolution Order

1. **PR #186**  
   Fresh review acknowledgment and merge.

2. **PR #154**  
   Rebase, update historical framing, verify green, merge.

3. **PR #185**  
   Fix pytest-visible assertion delivery, add exact wire-payload test, add accountability block, merge, and redeploy.

4. **PR #187**  
   Bound the helper, harden file handling, fix tests, and obtain not-same review.

5. **PR #159**  
   Publish and verify the replacement, then close the stale PR as superseded.

6. **PR #188**  
   Redesign the authoritative policy-replica model before wiring it.

7. **PR #175**  
   Rebase after #185, remove overlap, land the approved behavioral matcher fix, and verify both source and deployed behavior.

8. **PRs #151 and #157**  
   Resolve the underlying policy and provenance decisions, then convert both into green standing guards.

---

## Cross-Cutting Recommendations

## 1. Make deployment identity first-class

For every governed executable artifact, record:

- Canonical source digest
- Packaged digest
- Deployed digest
- Deployment time
- Deployment actor
- Authority source
- Whether the deployed copy matches canonical, package, or neither

A repository merge should never be treated as evidence that policy changed at runtime.

## 2. Test executable behavior, not declarations

Examples:

- Call `_touches_self()` with real event payloads rather than asserting tuple membership.
- Capture emitted RPC payloads rather than checking helper text.
- Assert rendered dashboard payloads rather than only struct fields.
- Verify denial and authorization paths through the actual gate order.

## 3. Require invocation-equivalent tests

Every discovered Python test file should behave consistently under:

- Bare `python3 file.py`
- `pytest`
- The repository's CI discovery runner

A red result must not become green merely because the invocation changed.

## 4. Separate mechanism from authority

Portable artifacts may carry mechanism, defaults, and schemas.

They should not carry undeclared installation-specific private authority.

Authority should be:

- Explicitly issued
- Provenanced
- Versioned
- Revocable
- Verifiable by the enforcing layer

## 5. Treat stale authority as potentially wider

A stale grant set may retain revoked permissions.

Do not assume stale means narrower unless the data model proves monotonic narrowing.

## 6. Protect the shared core outside a single adapter

Once policy is consolidated, self-protection should be enforced at the same level of consolidation.

Adapter-local protection is structurally incomplete for a shared policy core.

---

## Final Assessment

Hestia's governance process is producing unusually high-quality failure evidence. The review history repeatedly shows independent participants testing claims behaviorally, rejecting easy but unsafe repairs, and preserving deliberate red states when the claimed invariant is false.

The largest remaining opportunity is to move repeated forensic discoveries into explicit system architecture:

- Authority-certified policy replicas
- Mechanism/configuration separation
- Three-tree artifact provenance
- Deployment digest verification
- Behavioral policy probes
- Invocation-equivalent test contracts

The queue should be reduced carefully rather than cleared mechanically. Several red PRs are valuable evidence artifacts, but they should not become permanent red contracts on `main`. The target is not fewer alarms. The target is alarms whose green state is meaningfully different from the null state.
