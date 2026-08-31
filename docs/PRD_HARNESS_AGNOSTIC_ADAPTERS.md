# PRD - Harness-Agnostic Gate Integration and Adapter Acceptance

**Status:** PROPOSED  
**Owner:** Hestia governance / gate architecture  
**Date:** 2026-08-31  
**Scope:** Any first-party or third-party agent harness that routes consequential tool use through Hestia governance.  
**Extends:** `PRD_GATE_CONSOLIDATION.md`, `PRD_GOVERNANCE.md`, gate deployment/integrity work, and the vault-backed governance closure.

---

## 1. Purpose

Hestia must support more harnesses than the ones maintained today. Some will be first-party integrations; others will be contributed by third parties, written in languages and runtimes Hestia does not control.

The integration boundary must therefore be a stable product and security contract.

The system MUST NOT scale by adding another hand-maintained gate for each harness. An accepted integration is an **adapter to one common gate authority**, not a smaller local gate. The adapter translates harness mechanics into a stable Hestia protocol and translates Hestia's verdict back into the harness's native control surface. It does not decide policy.

> **N harnesses, one gate.** Every harness-specific integration is protocol glue. All governance decisions remain in the common authority.

This PRD defines:

1. the normative adapter boundary;
2. the harness-agnostic API to the common gate;
3. adapter non-negotiables;
4. pre/post tool-use semantics;
5. escalation and notification semantics;
6. adapter release identity, live hashing, attestation, revocation, and miswire detection;
7. first-party and third-party conformance tests;
8. quantitative acceptance criteria.

This is a forward contract. Existing adapters may temporarily violate it while being collapsed, but no new adapter is accepted by weakening the contract to match historical debt.

---

## 2. Definitions

### 2.1 Common gate

The single Hestia authority that decides whether a normalized consequential act may proceed. It owns policy evaluation, scope, governance closure, role/identity rules, escalation policy, approval sufficiency, remedies, degraded posture, witnessing requirements, and decision semantics.

The common gate may internally be composed of law, mechanism, vault state, and witness services. From an adapter's perspective it is one authority.

### 2.2 Adapter

Harness-specific code whose only purpose is to connect one harness to the common gate.

An adapter MAY:

- parse a harness event;
- map harness field names into the Hestia normalized event schema;
- supply harness-native identifiers and observed operational facts;
- call the common gate API;
- render the gate response using the harness's documented block/allow mechanism;
- emit the required post-tool event;
- present gate-supplied escalation status and notifications;
- implement transport mechanics required by that harness.

An adapter MUST NOT decide governance.

### 2.3 Policy-bearing code

Any code, constant, table, predicate, exception, fallback, or branch that can change whether an act is allowed, denied, escalated, witnessed, attributed, scoped, or considered sufficiently approved.

Examples include:

- read/write or safe/unsafe classifiers;
- forbidden/allowed command lists;
- path scope and containment logic;
- governance/self-access policy;
- role or identity authorization logic;
- escalation bars or approver requirements;
- approval claim semantics;
- fail-open/fail-closed switches;
- local remedy selection;
- special-case bypasses;
- environment variables that widen authority;
- locally chosen policy thresholds or timeouts.

### 2.4 Harness mechanics

Facts genuinely specific to the harness that do not widen authority, for example:

- where the harness puts the tool name in its event;
- which field contains arguments;
- native request/session identifiers;
- which exit code or response object means block;
- whether the harness can wait, poll, or must retry;
- the maximum runtime allowed for a pre-tool hook;
- how post-tool completion is delivered;
- how a gate-supplied message is surfaced.

### 2.5 Accepted adapter release

A specific adapter release that has passed this PRD's architecture and conformance requirements and whose exact release hash has been recorded in the Hestia vault.

Acceptance attaches to exact bytes, not to a filename, branch, package name, vendor name, or semantic version alone.

### 2.6 Resident hook

The actual hook or adapter entrypoint file the harness will execute on the resident machine, at the actual configured path used by that harness.

### 2.7 Miswired

A runtime state in which the resident hook is missing, unreadable, not the accepted release bytes, registered at the wrong location, bound to the wrong API version, or otherwise not demonstrably the adapter release Hestia expects to be enforcing.

---

## 3. Non-negotiables

These are acceptance invariants, not preferences.

### N1. No policy in the adapter

**An accepted adapter contains zero policy-bearing logic.**

There is no allowance for "small local adjustments," "temporary parity," "conservative fallback," or "one harness-specific exception" if the code changes a governance decision. Harness differences are represented as data or capabilities consumed by the common gate, never as a second policy implementation.

For newly accepted adapters:

> **adapter-local law-bearing SLOC MUST equal 0.**

The fleet-wide 5% release threshold and 2% convergence target in §12 are migration bars for historical adapters. They are not a policy budget for new adapters.

### N2. Fail closed

Any uncertainty before tool execution results in an explicit harness-native deny.

This includes:

- gate unavailable;
- gate timeout;
- adapter timeout approaching the harness deadline;
- malformed harness event;
- malformed or unknown gate response;
- unsupported gate API major version;
- missing identity/session binding required by the gate;
- missing, unreadable, stale, or mismatched resident hook;
- release hash mismatch;
- import/load failure;
- transport failure;
- unrecognized decision enum;
- internal adapter exception.

There is no local policy fallback.

Fail-closed MUST be demonstrated against actual harness semantics. If a harness treats a crashed or timed-out pre-hook as allow, returning a generic process error is not fail-closed. The adapter must emit the harness's explicit blocking form within the harness budget. If the harness provides no reliable way to do that, it cannot receive Accepted status.

### N3. Every adapter function requires strict architectural justification

Every function/method in the adapter runtime MUST be accounted for in the adapter manifest with:

- symbol/name;
- purpose;
- the harness-specific fact that requires it;
- why that fact cannot be represented by the common API or shared SDK;
- which allowed adapter seam it implements.

The burden of proof is on keeping the function local.

> **"This is useful here" is insufficient. The question is "why must this exist in this harness adapter rather than in shared architecture?"**

An unlisted function, or a function whose justification describes governance semantics rather than harness mechanics, blocks acceptance.

### N4. One authority path; no fallback authority

The adapter calls the common gate for every consequential pre-tool act. It does not call an older gate, embedded classifier, vendor-specific policy module, local policy cache, or emergency allow path when the common authority is unavailable.

### N5. Pre and post are a pair

Every allowed consequential act receives a gate-issued `action_id` before execution, and the adapter reports one post-tool outcome against that same `action_id`.

A post event may say `succeeded`, `failed`, `cancelled`, or `unknown`; it may not disappear silently. If the harness/process dies before post delivery, the common gate's reconciliation mechanism must eventually mark the action `started_never_completed` or equivalent.

### N6. Exact-act binding

A gate verdict or escalation approval authorizes exactly the normalized act it names.

The common gate computes an `act_digest` over the canonical normalized request. Approval is bound to that digest. Any change to tool, arguments, target, identity, session, workspace context, or other authority-relevant input requires a new preflight and, if applicable, a new escalation.

Appending another shell command, changing one path, or reusing an approval for a similar request is a different act.

### N7. Live resident hook identity is externally verified

The load-bearing integrity check is performed against the **actual resident hook file that the harness will execute**.

For each registered adapter, a trusted verifier outside the adapter's own authority MUST:

1. resolve the actual configured resident hook path;
2. verify that the file exists and is readable;
3. compute a full SHA-256 over the resident file bytes at check time;
4. read the accepted release SHA-256 for that adapter/hook from the Hestia vault;
5. compare the live digest to the vault release digest.

The adapter MUST NOT establish its own integrity by reporting "my hash is X." A modified adapter could lie.

**Missing file, unreadable file, missing expected vault hash, or hash mismatch => `MISWIRED` immediately.**

The mismatch is witnessed and surfaced as a miswire alert. Consequential tool use fails closed until the resident hook again matches an accepted release.

### N8. No silent degraded mode

If Hestia cannot establish that the accepted resident hook and common authority are the ones in force, the state is visibly `MISWIRED`, `UNVERIFIED`, or another explicit non-ready state and consequential tool use fails closed.

### N9. Governance decisions are explainable and attributable

The adapter preserves the gate's `rule_id`, `reason`, `action_id`, and relevant evidence identifiers. It may format them for the harness but may not replace a gate decision with locally invented policy text.

### N10. Harness capability is data, not law

Differences such as hook timeout, block convention, post-hook availability, long-poll support, or notification surface are declared in a capability manifest. The common mechanism chooses the safe protocol for those capabilities.

An adapter must not infer policy from them.

---

## 4. Target architecture

```text
harness
  |
  | native PreToolUse event
  v
thin adapter
  | parse/normalize only
  v
Hestia common gate API
  |
  | policy + scope + governance + escalation + witness
  v
GatePreResponse
  |
  v
thin adapter
  | native allow / explicit block / retry presentation
  v
harness executes tool only after ALLOW
  |
  | native PostToolUse event
  v
thin adapter
  | normalize outcome only
  v
Hestia common gate API
  |
  v
witness / reconciliation / reputation state
```

There are only two decision-bearing sides of this boundary:

- the harness decides whether to honor its own documented block/allow protocol;
- Hestia decides governance.

The adapter decides neither.

---

## 5. Stable harness-agnostic gate API

The API is language-agnostic and harness-agnostic. The reference transport may be local HTTP/JSON, Unix-domain IPC, or an SDK wrapping either, but the semantics below are normative.

The API is versioned independently of any harness integration.

### 5.1 Minimum required hooks

An Accepted adapter MUST provide the equivalent of:

1. `PreToolUse`
2. `PostToolUse`
3. escalation status via wait or poll when escalation is supported
4. adapter integrity/health consumption sufficient to refuse when the resident hook is `MISWIRED`

Optional lifecycle hooks may be added later, but they do not replace pre/post.

### 5.2 `PreToolUse`

Conceptual request:

```json
{
  "api_version": "1.x",
  "adapter_id": "claude-code",
  "adapter_instance_id": "opaque-runtime-instance",
  "harness": "claude-code",
  "event_id": "harness-native-or-generated-id",
  "session_id": "harness-session-id",
  "tool": {
    "name": "Bash",
    "native_name": "Bash"
  },
  "arguments": {},
  "cwd": "/observed/cwd",
  "workspace_hint": "/observed/workspace",
  "harness_context": {},
  "raw_event_digest": "sha256:..."
}
```

Rules:

- `arguments` are harness-provided arguments, structurally normalized but NOT classified by the adapter.
- `cwd`, workspace, identity-location, and similar values are observations/hints. The common gate decides whether and how they affect authority.
- adapter identity and accepted release hash are not trusted merely because the request says them. Integrity comes from the external live resident-file check in §8.
- the adapter SHOULD preserve unknown harness fields under namespaced `harness_context` rather than interpreting them as policy.

Conceptual response:

```json
{
  "api_version": "1.x",
  "action_id": "hst-act-...",
  "act_digest": "sha256:...",
  "decision": "allow | deny | escalate",
  "rule_id": "stable-rule-id",
  "reason": "human-readable gate supplied reason",
  "remedy": {},
  "escalation": null
}
```

The adapter's only allowed decision mapping is mechanical:

- `allow` -> harness-native allow;
- `deny` -> harness-native explicit block;
- `escalate` -> do not execute, then follow §7.

Unknown decision value -> explicit block.

### 5.3 `PostToolUse`

Conceptual request:

```json
{
  "api_version": "1.x",
  "adapter_id": "claude-code",
  "action_id": "hst-act-...",
  "event_id": "post-event-id",
  "outcome": "succeeded | failed | cancelled | unknown",
  "duration_ms": 123,
  "result_metadata": {},
  "result_digest": "sha256:..."
}
```

The post hook is evidence about what happened, not a second authorization decision.

Requirements:

- `action_id` MUST be the identifier returned by the corresponding preflight.
- the adapter MUST NOT fabricate success because the harness produced no result.
- raw tool output is not required by default and SHOULD NOT be shipped wholesale when it can contain credentials/private data; structured metadata, bounded summaries, and/or content digests are preferred.
- duplicate post delivery MUST be idempotent.
- post without a known allowed `action_id` is anomalous and cannot synthesize authorization retroactively.

### 5.4 API versioning

- Major-version incompatibility fails closed.
- Minor-version additions are backward compatible unless the common gate explicitly declares otherwise.
- Unknown response enums fail closed.
- Unknown request fields are preserved/ignored according to schema rules; they are never locally interpreted into authority.
- capability negotiation occurs during registration/health, not by ad hoc runtime branching that changes policy.

---

## 6. Adapter capability and function manifest

Every adapter ships a machine-readable manifest. The exact serialization may be JSON/TOML/YAML; the canonical schema is shared.

Minimum fields:

```text
adapter_id
adapter_version
harness_name
harness_version_range
gate_api_major
resident_hook_path
release_hook_sha256
runtime_files[]
entrypoints:
  pre_tool
  post_tool
capabilities:
  explicit_pre_block
  post_tool
  escalation_wait
  escalation_poll
  local_notification_surface
  max_pre_hook_ms
  max_post_hook_ms
function_inventory[]
```

`resident_hook_path` is an installation-time fact and MUST resolve to the actual file the harness invokes. The canonical accepted release hash is stored in the vault; a copy in the manifest is descriptive and must not override the vault value.

Each `function_inventory` entry contains:

```text
symbol
runtime_file
purpose
harness_specificity
why_not_shared
allowed_seam
```

Allowed seams are intentionally narrow:

- `parse_pre_event`
- `render_pre_verdict`
- `parse_post_event`
- `render_post_ack`
- `transport`
- `harness_identity_location`
- `harness_registration`
- `notification_presentation`
- `process_entrypoint`

A helper function must still identify which seam it supports.

Where language tooling permits, CI MUST compare discovered runtime functions/methods to the declared inventory and fail on undeclared symbols. Where automatic discovery is unavailable, acceptance requires manual source reconciliation of the complete runtime.

---

## 7. Escalation protocol and notification

Escalation is common-gate behavior. The adapter transports and presents it; it does not define who may approve, what bar is sufficient, how long approval lasts, or what the approval authorizes.

### 7.1 Open

When the gate cannot allow an act directly but governing law permits escalation, `PreToolUse` returns:

```json
{
  "decision": "escalate",
  "action_id": "hst-act-...",
  "act_digest": "sha256:...",
  "escalation": {
    "escalation_id": "hst-esc-...",
    "status": "pending",
    "expires_at": "...",
    "retry_after_ms": 1000,
    "notification_id": "hst-note-..."
  }
}
```

Opening an escalation authorizes nothing.

### 7.2 Notification

Opening an escalation MUST create a Hestia notification independent of whether the harness has a local notification UI.

If the harness provides a notification surface, the adapter MAY present the gate-supplied notification payload there. Presentation is mechanical; the adapter does not generate a different approval request or redefine the bar.

The notification identifies at least:

- actor/member/session;
- tool and bounded act summary;
- governing rule;
- escalation id;
- expiry;
- evidence/approval bar where appropriate;
- authorized decision surface.

### 7.3 Wait or poll

Two safe harness patterns are supported:

**A. Wait/long-poll** - only when the harness hook budget can safely accommodate it with a proven margin. The adapter waits on the common escalation API, never by implementing local approval state.

**B. Deny-now / poll-or-retry** - required when waiting risks the harness killing the hook or treating timeout as non-blocking. The current act is explicitly denied/pended; the agent/operator can retry after approval. The subsequent retry performs a fresh `PreToolUse`, and the common gate claims the approval only if the new normalized `act_digest` exactly matches the approved act.

The adapter manifest declares which mechanics the harness supports. The common mechanism selects the safe pattern.

### 7.4 Status semantics

Normative escalation statuses:

- `pending`
- `approved`
- `denied`
- `expired`
- `revoked`

Only `approved` may become an allow, and only for the exact act digest and within gate-controlled claim semantics.

Unknown id/status, timeout, transport failure, or malformed response -> deny.

### 7.5 Approval is not adapter state

The adapter MUST NOT cache an approval as a local boolean, environment variable, file marker, or process-global exception. Approval is claimed from the common gate for one exact act.

---

## 8. Release identity, live hashing, attestation, and miswire detection

### 8.1 Release record in the vault

Acceptance creates a durable vault record containing at least:

```text
adapter_id
adapter_version
harness_name
gate_api_major
resident_hook_release_sha256
runtime_dependency_sha256[] (where applicable)
manifest_sha256
conformance_suite_version
accepted_at
accepted_by / governance evidence
source provenance
status = accepted | revoked
```

Hashes are full SHA-256 values, never truncated prefixes.

Third-party signatures may be recorded as provenance, but a vendor signature does not grant acceptance. Hestia acceptance is a local governance decision over exact release bytes.

### 8.2 The live resident hook check is authoritative

At verification time Hestia MUST hash the **actual resident hook file in place** at the exact path registered with the harness.

Normative algorithm:

```text
path := resolve actual harness registration for adapter
expected := vault.accepted_release_sha256(adapter_id, active_release)

if path is absent:
    MISWIRED("resident hook missing")
if path is unreadable:
    MISWIRED("resident hook unreadable")
if expected is absent:
    MISWIRED("accepted release hash missing")

observed := SHA256(bytes read from path now)

if observed != expected:
    MISWIRED("resident hook hash mismatch")
else:
    WIRED(expected, observed, path, checked_at)
```

The observed hash MUST be computed from resident bytes, not from:

- source checkout bytes;
- package metadata;
- an installer manifest alone;
- a previously computed deployment digest;
- the adapter's self-report;
- a symlink target name without reading the target bytes.

If the harness registration itself cannot be resolved to the executable hook file, the state is `MISWIRED`.

### 8.3 Verification cadence

The live resident hook hash MUST be checked:

1. immediately after install/activation;
2. at Hestia startup;
3. whenever harness registration changes;
4. periodically while active;
5. immediately when file-integrity monitoring reports a change;
6. before readiness is reported after deploy.

The verifier records observed hash, expected vault hash, resident path, and check timestamp.

### 8.4 Miswire alert and enforcement

Missing or mismatched resident hook is not merely a dashboard warning.

It MUST produce:

- explicit `MISWIRED` adapter status;
- a miswire alert/notification to the operator;
- a witnessed integrity event containing adapter id, expected digest, observed digest when available, and resident path;
- readiness failure;
- fail-closed consequential preflight until resolved.

An ordinary act escalation MUST NOT override a miswire. Recovery requires restoring the accepted release bytes or governing acceptance of a new release.

### 8.5 Runtime dependency closure

The resident hook hash is the primary harness-wiring identity. If the resident hook imports adapter-local executable helpers, those helpers are part of the accepted runtime closure and must also be identified and integrity-verified.

The adapter MUST NOT use an unhashed local helper as a back door for policy or behavior changes while the entrypoint hash remains stable.

Shared Hestia gate modules are versioned and attested as common authority, not as adapter-owned law.

### 8.6 Updates and revocation

Any resident hook byte change creates a new release hash and therefore a new candidate adapter release.

Acceptance does not silently follow a filename, package, branch, or version label. A delta review may make acceptance efficient, but the new bytes receive a new vault release record.

A revoked release hash is always non-ready and fail-closed even if the resident file still matches it.

---

## 9. Conformance suite

An adapter does not become Accepted by inspection alone. It must pass the shared harness-adapter conformance suite against the actual harness or a faithful harness contract test.

### 9.1 Authority boundary

- no local policy predicates;
- no local allow/deny lists;
- no local scope/self-access/escalation rules;
- no fallback authority when common gate unavailable;
- every runtime function present in the manifest and justified;
- runtime imports remain inside the declared runtime closure plus approved shared SDK/runtime dependencies.

### 9.2 Pre-tool controls

- common gate `allow` -> one tool execution;
- common gate `deny` -> zero tool executions;
- common gate `escalate` -> zero execution until exact approval claim;
- unknown verdict -> zero execution;
- malformed response -> zero execution;
- gate unavailable -> zero execution;
- adapter exception/import failure -> zero execution;
- API-major mismatch -> zero execution.

These are end-to-end tests against harness semantics, not merely unit tests of return values.

### 9.3 Harness timeout sabotage test

Artificially delay the gate beyond the adapter's safe internal deadline and prove the harness does not execute the tool.

The adapter's internal budget MUST leave a measured safety margin below the harness's timeout/kill boundary. A harness whose timeout behavior causes execution cannot be Accepted until a wrapper/supervisor provides reliable explicit blocking.

### 9.4 Exact-act binding

- approve act A, retry exact A -> may claim approval;
- approve A, alter one argument -> denied/new escalation;
- approve A, append shell command -> denied/new escalation;
- approval outside claim window -> denied;
- reused/spent approval -> denied.

### 9.5 Post-tool controls

- allowed action produces exactly one attributable post outcome;
- duplicate post is idempotent;
- post for unknown action is anomalous and does not authorize;
- simulated adapter/process death leaves an incomplete action that reconciliation detects;
- denied/escalated-but-unapproved action cannot produce a valid successful post pair.

### 9.6 Resident hook integrity controls

- accepted resident hook -> hash matches vault -> `WIRED`;
- mutate one resident byte -> `MISWIRED` + alert + deny;
- delete resident hook -> `MISWIRED` + alert + deny;
- make resident hook unreadable -> `MISWIRED` + alert + deny;
- alter harness registration to another file -> `MISWIRED` unless that exact resident file is the accepted release;
- adapter self-reports expected hash while resident bytes differ -> still `MISWIRED`;
- vault expected hash missing -> `MISWIRED`;
- revoked matching hash -> non-ready + deny;
- mutate imported adapter-local runtime helper -> integrity failure + deny.

### 9.7 Escalation/notification controls

- escalation creates Hestia notification;
- wait-capable harness uses bounded wait safely;
- timeout/non-wait harness uses deny-now/retry safely;
- unknown escalation id -> deny;
- expired/denied/revoked escalation -> deny;
- exact approval produces no local adapter exception or cached bypass.

### 9.8 Positive controls and sabotage

Every critical conformance test must demonstrate it can fail. Examples:

- swap expected allow/deny;
- mutate one resident hook byte;
- change an act argument after approval;
- force gate timeout;
- make the harness adapter exit through its generic error path.

A green test never demonstrated capable of turning red is not acceptance evidence.

---

## 10. Third-party adapter submission process

Third-party adapters follow the same technical contract as first-party adapters.

Required submission artifacts:

1. source code for the complete adapter runtime;
2. adapter capability/function manifest;
3. reproducible build/install instructions where compilation is involved;
4. exact release resident hook bytes and full SHA-256;
5. conformance results;
6. harness documentation proving hook/block semantics;
7. provenance/signatures if available;
8. license and dependency inventory sufficient for redistribution/security review.

Acceptance stages:

```text
CANDIDATE
  -> ARCHITECTURE REVIEWED
  -> CONFORMANCE PASS
  -> ACCEPTED (release hash stored in vault)
  -> INSTALLED
  -> RESIDENT HASH VERIFIED
  -> ACTIVE
```

Any integrity failure transitions the installation to `MISWIRED`. Governance may transition an accepted digest to `REVOKED`.

No third party is required to reveal unrelated proprietary harness code, but the adapter runtime on the governance boundary must be reviewable enough to establish the invariants above. A closed adapter whose decision-bearing behavior cannot be inspected or conformance-tested cannot be Accepted.

---

## 11. Reference adapter SDK/template

Hestia SHOULD ship a reference adapter SDK and starter template so the easiest integration path is also the compliant path.

The template should expose the smallest practical surface, conceptually:

```text
parse_pre_event(native_event) -> NormalizedPreEvent
render_pre_response(GatePreResponse) -> native_harness_response
parse_post_event(native_event, action_id) -> NormalizedPostEvent
render_post_ack(...) -> native_harness_response
present_notification(gate_notification) -> optional native presentation
```

Transport, schema validation, API version handling, action-id tracking, escalation polling/waiting, timeout budgeting, fail-closed error conversion, and common integrity-state consumption SHOULD live in the shared SDK wherever language/runtime permits.

The template must make it harder to add policy than to use the common gate.

For languages without an official SDK, the wire protocol remains the normative integration contract.

A minimal skeleton adapter plus manifest should be publishable as a copy-and-fill template for third-party authors.

---

## 12. Quantitative architecture bars

### 12.1 New adapters

For every newly Accepted adapter:

- policy-bearing adapter SLOC: **0**;
- local implementations of shared policy functions: **0**;
- verbatim policy forks: **0**;
- divergent policy forks: **0**;
- undeclared runtime functions: **0**;
- unjustified runtime functions: **0**;
- unhashed resident entrypoints: **0**;
- accepted-but-not-live-verified resident hooks: **0**.

### 12.2 Existing fleet migration

Historical adapters are currently above the intended boundary. Migration is measured fleet-wide:

- release threshold: **<= 5%** of total gate law-bearing SLOC may remain per-seat;
- convergence target: **<= 2%**;
- architectural ideal: **0%**;
- no adapter may independently own a governance decision even if the aggregate percentage is below threshold.

The percentage is a debt indicator, not permission to keep local law.

The meter must resist denominator games: moving or adding shared code cannot make an unchanged local policy surface look compliant. Track absolute per-seat law SLOC, fork counts, and semantic boundary violations alongside the percentage.

---

## 13. Acceptance criteria

A harness integration is **Accepted** only when all are true.

### Architecture

- [ ] Adapter contains zero policy-bearing logic.
- [ ] Every runtime function is inventoried and has an accepted harness-specific justification.
- [ ] No function's justification is a governance rule in disguise.
- [ ] Common gate is the only authority path.
- [ ] No local fallback policy exists.

### Pre/post protocol

- [ ] PreToolUse is implemented for every consequential tool call.
- [ ] PostToolUse is implemented and paired by `action_id`.
- [ ] Exact-act digest binding is enforced by the common gate.
- [ ] Incomplete acts are reconciled and visible.

### Fail-closed

- [ ] Gate unavailable -> explicit block.
- [ ] Adapter crash/import failure -> explicit block.
- [ ] Malformed/unknown response -> explicit block.
- [ ] Harness timeout behavior is tested end-to-end and cannot cause execution.
- [ ] No environment/config switch can turn fail-closed off.

### Escalation

- [ ] Escalation opens in the common gate and creates notification.
- [ ] Adapter supports a safe wait or deny-now/poll/retry pattern.
- [ ] Approval is never stored as adapter-local authority.
- [ ] Modified/replayed/expired acts cannot claim an approval.

### Resident integrity

- [ ] Full accepted resident hook SHA-256 is stored in the vault.
- [ ] Actual harness registration resolves to a concrete resident hook path.
- [ ] Hestia hashes that resident file live and compares it with the vault release hash.
- [ ] Missing resident file causes `MISWIRED`, alert, and deny.
- [ ] Unreadable resident file causes `MISWIRED`, alert, and deny.
- [ ] One-byte resident mismatch causes `MISWIRED`, alert, and deny.
- [ ] Adapter self-report cannot override a resident mismatch.
- [ ] Imported adapter-local runtime helpers are inside the verified runtime closure.
- [ ] Revoked release blocks even when live bytes match.

### Evidence

- [ ] Shared conformance suite passes.
- [ ] Critical tests include sabotage/negative controls proving they can fail.
- [ ] Evidence records exact release hash and conformance-suite version.
- [ ] Acceptance decision and reviewer/governance evidence are durable and auditable.

No checkbox may be waived by renaming the integration "experimental" while allowing it to govern production actions. Experimental adapters may run only in explicitly non-authoritative contexts.

---

## 14. Non-goals

This PRD does not:

- define the common gate's policy language;
- define which human/AI roles may approve specific escalations;
- claim OS-level isolation from a malicious same-UID process;
- require every harness to expose identical UX;
- require raw tool outputs to be centralized;
- treat a vendor signature as sufficient trust;
- claim hashing prevents tampering.

Hashing makes installed identity detectable and attributable. Enforcement comes from live resident verification, fail-closed miswire handling, and the surrounding assurance profile.

---

## 15. Security and governance rationale

The critical property is not that adapters are tiny for aesthetics. It is that a new harness must not create a new constitution.

If an adapter can classify commands, interpret scope, decide what counts as governance, choose when fail-closed applies, or locally honor an approval, then adding a harness adds a new authority surface. Maintenance cost rises linearly; divergence and weakest-seat risk rise faster.

By contrast, an adapter whose only powers are **translate, transport, render, report** can be numerous and independently authored without multiplying law.

The live hash requirement closes the deployment side of the same problem. Source architecture is irrelevant if the harness executes different bytes. Hestia therefore hashes the actual resident hook file, compares it to the accepted release hash stored in the vault, and treats absence or mismatch as a miswire rather than as an informational warning.

The trust statement is intentionally modest and auditable:

> Hestia does not assert that an adapter is incorruptible. It asserts which hook bytes were accepted, which bytes are resident at the harness's actual entrypoint now, whether those facts agree, and that disagreement cannot silently authorize an act.

---

## 16. Implementation sequence

1. Ratify this PRD and the zero-policy adapter boundary.
2. Define versioned normalized pre/post schemas and common gate wire API.
3. Define the adapter capability/function manifest schema.
4. Build the reference SDK/template.
5. Build live resident hook resolver + SHA-256 verifier backed by vault release hashes.
6. Add `MISWIRED` alert/status and fail-closed enforcement to readiness/preflight.
7. Build the shared conformance suite, including real harness timeout/error semantics.
8. Convert one existing seat into the reference adapter and prove zero local policy.
9. Convert the remaining first-party seats.
10. Publish the third-party adapter authoring and acceptance path.
11. Gate production acceptance on §13 mechanically wherever possible.

---

## 17. Open implementation questions

These are implementation choices, not openings to weaken the invariants above:

- exact wire transport(s) for API v1;
- canonical schema format and code generation;
- how adapter-local helper closure is declared for languages with dynamic imports;
- periodic resident hash cadence and freshness interval;
- whether file change monitoring supplements periodic hashing on each supported OS;
- packaging and distribution of SDKs for non-Python adapters;
- how the dashboard groups resident hook mismatch vs missing registration vs stale attestation while retaining one top-level `MISWIRED` state.

The invariants remain fixed regardless of these choices: **no policy in adapters, explicit fail-closed, every function justified, minimum pre/post hooks, common escalation protocol with notification, and live resident hook bytes hashed against the vault-stored accepted release hash.**
