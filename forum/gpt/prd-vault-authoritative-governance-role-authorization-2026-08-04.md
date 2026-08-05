# PRD: Vault-Authoritative Governance, Role Authorization, and the Single Gate

**Status:** Proposed  
**Date:** 2026-08-04  
**Repository baseline:** `dp-web4/Hestia` at `400875684012fed31689207934243f3369413191`  
**Initial implementation domain:** Hestia  
**Federation target:** 4-hub / Web4 policy substrate  

---

## 1. Product statement

Hestia governance must operate at machine speed without removing the human from control.

The human is not placed in the loop for every act. The human stays in the loop by authoring and amending the law. The law then remains in the loop for every governed act.

This PRD establishes one authority model:

1. **All information that can steer a governance decision is authoritative only inside the encrypted vault.**
2. The vault state is validated and loaded into one immutable in-memory governance snapshot.
3. **Only that memory snapshot is consulted during actual decisions.**
4. Plaintext files are generated for transparency, but are never accepted as decision inputs.
5. Policy has a global baseline and explicit role, agent, and agent-in-role amendments that may tighten or loosen it.
6. Policy may be changed only through an operator-presence UI. No CLI, MCP tool, hook, config file, or connector may edit law.
7. An escalation is a request to amend policy. It is not a one-use bypass around policy.
8. An agent may fill a role only after proving sufficient authority for that role.
9. Harness-specific Python hooks are syntax shims only. One global, vault-assured gate makes every decision.
10. The gate verifies its own approved build and independently verifies the exact harness shim on every call. Any uncertainty fails closed.
11. Member acts and role acts are witnessed on separate chains and linked through RDF describing **agent X filling role Y**.
12. Hestia implements the model first and mirrors signed, MRH-filtered projections to Hub.

The intended result is not “human approval at machine speed.” It is:

> **Human-authored law, executed at machine speed, with human-visible and cryptographically attributable amendments.**

---

## 2. Goals

### 2.1 Primary goals

- Establish the vault as the sole authority for all governance inputs.
- Eliminate plaintext policy, identity, scope, role, and permission files as authoritative inputs.
- Maintain an immutable in-memory governance snapshot for low-latency decisions.
- Provide transparent, signed, non-authoritative file mirrors on launch and after every governance change.
- Support a global policy baseline plus explicit tightening and loosening for:
  - a role;
  - an agent;
  - an agent filling a particular role.
- Make the operator UI the only law-mutation surface.
- Recast escalation as a proposed policy amendment.
- Establish explicit authority levels and minimum authority requirements for roles.
- Check role authorization at the role-occupancy boundary, before role policy is selected.
- Replace harness-specific policy implementations with minimal syntax shims.
- Verify core and shim integrity against vault-approved artifact digests.
- Fail closed whenever policy, identity, role authorization, gate integrity, or shim integrity cannot be proven.
- Maintain separate member and role witness chains with RDF links between them.
- Mirror signed, MRH-adjusted governance projections to Hub without transferring local edit authority.

### 2.2 Secondary goals

- Make every effective permission explainable in the operator UI.
- Make the exact source of every allow, warn, deny, or escalation traversable.
- Make a policy change visible as a diff with blast radius, authority, reason, generation, and expiry.
- Make stale, forged, modified, or missing artifacts distinguishable from valid artifacts.
- Preserve local operation when Hub is unreachable, using the last valid Hub policy projection already committed into the Hestia vault where applicable.

---

## 3. Non-goals

This PRD does not:

- infer authority automatically from reputation, T3, V3, activity volume, model vendor, or self-declared role;
- allow an agent to modify its own policy, role, authority, MRH, or gate;
- use a plaintext mirror as an offline policy fallback;
- preserve a second policy implementation inside a harness shim;
- permit a gate decision while the authoritative memory snapshot is unavailable;
- permit direct Hub mutation of Hestia’s local law;
- merge member identity and role identity into one witness grain;
- make a role’s history indistinguishable from the histories of agents that filled it;
- make the operator approve each ordinary act;
- treat an appeal and an escalation as the same mechanism.

---

## 4. Product principles

### 4.1 The vault is authority

All governance-relevant state is stored inside the encrypted vault. This includes not only policy rules, but every value that may influence policy selection or role authorization.

No decision may be based on:

- `identity.json`;
- a generated policy file;
- an environment variable that grants authority;
- a harness-local exception list;
- a command-line policy switch;
- an uncommitted remote response;
- a caller-supplied identity or role claim;
- a locally edited mirror;
- a file replica used because the daemon is unavailable.

### 4.2 Memory is the execution surface

At launch, Hestia decrypts and validates a complete governance envelope, then builds an immutable `GovernanceSnapshot` in memory.

Every act is evaluated against that snapshot. No hot-path file read participates in a decision.

A governance change creates a new generation and atomically swaps the in-memory snapshot. In-flight decisions finish against the generation they began with. New decisions use the new generation.

### 4.3 Files are transparency, never authority

Hestia writes human-readable mirrors:

- on successful launch;
- after every committed governance update;
- after every role, authority, MRH, operator, artifact, or policy amendment.

A mirror may be inspected, copied, diffed, and published. It may also be modified or deleted without changing governance behavior.

Every mirror must say, prominently and structurally:

```json
{
  "authoritative": false,
  "source": "hestia-vault-memory",
  "warning": "TRANSPARENCY MIRROR ONLY — NEVER CONSULTED FOR DECISIONS"
}
```

Mirror divergence is detected, shown in the operator UI, witnessed, and repaired by regeneration. It is not imported.

### 4.4 The operator edits law; law governs acts

The operator does not approve routine acts one by one. The operator edits the law that decides them.

An ordinary act has no operator round trip. The memory-resident gate decides it immediately.

When the law blocks legitimate work, the agent may request a policy amendment. The operator can approve, modify, time-bound, or refuse the proposed amendment in the UI.

### 4.5 Authority is explicit, not inferred trust

Authority is a granted capability comparable to a security clearance. It is not a reputation score.

T3/V3, trust history, and witness evidence may inform the operator’s decision to grant authority, but they do not directly grant it unless the operator has explicitly authored a law that does so. For the initial implementation, no automatic authority-granting rule is permitted.

### 4.6 A role is an entity, not a label

A role has:

- its own LCT;
- a minimum authority requirement;
- an MRH;
- policy amendments;
- active occupancies;
- a witness chain;
- role-scoped trust and reputation.

An agent does not become a role by declaring a string. The agent requests occupancy and is authorized or refused at that boundary.

### 4.7 The shim never decides

A per-harness `.py` hook exists only to:

- parse the harness event syntax into a normalized request;
- render the gate verdict using the harness exit-code and output contract.

A shim contains no:

- policy rule;
- path scope logic;
- forbidden list;
- role logic;
- remedy choice;
- grant logic;
- allow/deny fallback;
- decision branch.

### 4.8 Uncertainty denies

The following states must deny:

- vault unavailable or sealed;
- governance snapshot absent or invalid;
- gate core build not approved by the vault;
- shim missing, modified, symlinked, incorrectly owned, or unregistered;
- harness identity not bound to an approved shim;
- member identity unproven;
- role occupancy absent, expired, revoked, or below required authority;
- policy generation invalid;
- conflicting or malformed governance state;
- Hub policy required for the act but no valid imported Hub projection exists.

---

## 5. Current-state gap matrix

Legend:

- **IMPLEMENTED** — present in current source and aligned with this PRD.
- **PARTIAL** — useful implementation exists but does not satisfy the target invariant.
- **MISSING** — no sufficient implementation found.
- **CONFLICT** — current behavior directly contradicts this PRD and must be removed or redesigned.
- **UNVERIFIED** — source suggests support, but live or end-to-end proof is absent.

| Requirement | Current status | Current source / observation | Required change |
|---|---|---|---|
| Vault stores global policy | **IMPLEMENTED** | `core/src/vault/policy_state.rs` stores active preset, overrides, custom rules | Retain and expand into complete governance envelope |
| Vault stores role and instance policy | **PARTIAL** | `role_overlays` and `instance_overlays` exist | Add explicit role, agent, and agent-role deltas supporting both tightening and loosening |
| Policy loaded into memory | **IMPLEMENTED** | `ServerState` builds base, role, and instance policy engines from vault | Replace mutable parallel maps with one immutable generation-tagged snapshot |
| Decisions consult memory only | **PARTIAL / CONFLICT** | Daemon policy is memory-resident, but harness gates still consult local identity/policy files and local logic | Remove all file-based and harness-local decision inputs |
| Transparency mirrors | **MISSING** | No complete generated governance mirror found | Generate signed non-authoritative mirror tree on launch/update |
| Global presets and modifiable rules | **IMPLEMENTED** | Preset, override, custom-rule APIs and dashboard UI exist | Move into versioned change-set workflow with generation CAS and exact diff signing |
| Per-role tightening | **IMPLEMENTED** | Role overlays fold strictest-wins | Generalize to explicit amendment semantics supporting loosening and tightening |
| Per-agent tightening | **PARTIAL** | `(plugin_id, role)` instance overlays exist and tighten only | Add agent-only and agent-role layers with explicit precedence |
| Per-agent loosening | **CONFLICT** | `instance_grants` are memory-only and disappear on restart | Represent temporary or durable loosening as time-bounded vault policy entries |
| Scope grants | **CONFLICT** | Current scope requests/grants are memory-only exceptions | Approval must create a vault policy amendment; retry is governed by new law |
| Policy only editable through operator UI | **CONFLICT** | `hestia policy set/override/add-rule` directly writes vault; HTTP endpoints are generic mutators | Remove CLI mutators; accept only operator-presence UI change sets |
| Operator-authenticated policy UI | **PARTIAL** | Operator challenge/session and dashboard policy editor exist | Bind signature to exact proposed diff and require user presence/quorum by stakes |
| Escalation as policy edit request | **CONFLICT** | Gate escalation currently authorizes a particular governance write/claim | Replace bypass token with proposed policy patch; no act proceeds until policy changes |
| Appeal remains adjudication | **PARTIAL** | Appeals are distinct from scope grants conceptually | Preserve separation and make it explicit in UI/remedies |
| Role has minimum authority | **MISSING** | Known role vocabulary exists; requested legacy role currently floors to `citizen` | Add authority levels, role requirements, grants, expiry, and revocation |
| Authorization checked before role occupancy | **MISSING** | `constellation_role` is normalized from caller declaration | Replace declaration with authorized occupancy establishment |
| Agent identity proven | **MISSING / P0** | `plugin_id` is caller-asserted in current connect path | Bind member LCT to key and authenticated connection |
| Operator UI edits agent and role permissions | **PARTIAL** | Per-member preset grants exist; no complete role/authority/MRH editor | Add role, agent, occupancy, authority, MRH, artifact, and escalation panels |
| One global gate core | **PARTIAL** | `plugins/_shared/hestia_gate_core.py` exists | Move decision service into the vault-loaded Hestia gate process and wire every harness |
| Shims are syntax only | **MISSING** | Shared core says shims should exist; no complete migrated shim fleet | Implement minimal shims and structural no-policy checks |
| Shim verified every call | **MISSING** | No per-call vault-manifest verification | Independently resolve and hash registered shim on every request |
| Gate core vault-assured | **MISSING** | No approved-build manifest controlling gate activation | Store approved core digest/version in vault and verify at startup and every call |
| Fail closed on gate/core/shim uncertainty | **PARTIAL** | Shared core states fail-closed intent; current harness behavior and local fallbacks vary | Central service becomes sole decider; no local read-class or file fallback |
| Separate member and role witness chains | **MISSING** | Current events carry role context in a shared chain | Add per-member and per-role chains with atomic dual append |
| RDF links agent and role | **PARTIAL** | `core/src/rdf.rs` emits separate `web4:entity` and `web4:role` edges for trust tensors | Add role occupancy and dual-chain act RDF entities |
| Mirror Hestia governance to Hub | **MISSING / PARTIAL SUBSTRATE** | `4-hub/web4-policy` provides a shared Law substrate; no signed operational mirror flow found | Add signed MRH projection, delivery, receipt, generation, and replay protection |
| Hub-adjusted MRH | **MISSING** | No complete projection contract found | Define export/import MRH transforms and cross-domain policy composition |

---

## 6. Target architecture

### 6.1 Four planes

The system is divided into four explicit planes.

#### A. Governance authority plane

- encrypted vault;
- operator identities and quorum;
- policy definitions and amendments;
- roles and authority requirements;
- agent authority and MRH grants;
- artifact approval manifest;
- Hub projection/import configuration;
- generation history.

#### B. Gate execution plane

- one Hestia global gate service;
- immutable in-memory governance snapshot;
- harness syntax shims;
- per-call artifact assurance;
- normalized request and typed verdict;
- fail-closed behavior.

#### C. Role occupancy and authorization plane

- proven member identity;
- explicit authority grants;
- role definitions;
- authorization check at occupancy boundary;
- generation-bound occupancy tokens;
- revocation and expiry.

#### D. Attribution and witness plane

- member witness chains;
- role witness chains;
- governance amendment chain;
- shared act IDs;
- RDF links between member, role, occupancy, authority evidence, and chain entries;
- Hub projection receipts.

No plane may silently substitute for another. In particular:

- witness history does not itself grant authority;
- a mirror does not become policy;
- a role label does not establish occupancy;
- a shim does not become a gate;
- an escalation does not become a bypass.

---

## 7. Authoritative governance data model

### 7.1 Governance envelope

The vault stores a versioned envelope:

```rust
struct GovernanceEnvelope {
    schema_version: String,
    generation: u64,
    previous_digest: Option<Digest>,
    created_at: Timestamp,
    state: GovernanceState,
    amendment: GovernanceAmendment,
    operator_signatures: Vec<OperatorSignature>,
    envelope_digest: Digest,
}
```

The envelope is sealed as part of the vault and atomically replaced on commit.

`generation` is monotonic. `previous_digest` forms a vault-contained amendment chain even if an external witness projection is temporarily unavailable.

### 7.2 Governance state

```rust
struct GovernanceState {
    global_policy: GlobalPolicy,
    role_definitions: Map<RoleLct, RoleDefinition>,
    role_policy: Map<RoleLct, Vec<PolicyDelta>>,
    agent_authority: Map<MemberLct, Vec<AuthorityGrant>>,
    agent_mrh: Map<MemberLct, Vec<MrhGrant>>,
    agent_policy: Map<MemberLct, Vec<PolicyDelta>>,
    agent_role_policy: Map<(MemberLct, RoleLct), Vec<PolicyDelta>>,
    operator_access: Vec<OperatorIdentity>,
    operator_quorum: OperatorQuorumPolicy,
    artifact_manifest: ArtifactManifest,
    hub_mirrors: HubMirrorPolicy,
    constitutional_settings: ConstitutionalSettings,
}
```

### 7.3 What must be in the vault

Any value that can alter an allow, warn, deny, escalate, role-occupancy, or artifact-acceptance result must be represented in `GovernanceState`.

This includes:

- active preset;
- complete preset definitions if operator-modifiable;
- rules, priorities, decisions, selectors, remedies, and escalation targets;
- global overrides;
- role policy deltas;
- agent policy deltas;
- agent-role policy deltas;
- role minimum authority;
- role MRH;
- member authority grants;
- member MRH grants;
- operator identities and quorum;
- gate-core approved digest and version;
- every shim’s approved digest, path, owner, mode, harness type, and profile version;
- imported Hub policy projections that participate in local cross-domain decisions;
- expiry, revocation, and generation information.

### 7.4 What does not steer decisions

The following may remain outside the vault because they are evidence or projections, not authority:

- witness-chain storage;
- trust and reputation observations;
- dashboard caches;
- transparency mirrors;
- pending escalation requests;
- pending appeals;
- Hub delivery queues;
- generated RDF;
- log files.

If any of those begins directly changing a decision, the relevant derived authorization must first be committed into the vault by an operator-authored policy mechanism.

---

## 8. Immutable in-memory governance snapshot

### 8.1 Snapshot shape

```rust
struct GovernanceSnapshot {
    generation: u64,
    envelope_digest: Digest,
    global_engine: PolicyEngine,
    role_engines: Map<RoleLct, PolicyEngine>,
    agent_engines: Map<MemberLct, PolicyEngine>,
    agent_role_engines: Map<(MemberLct, RoleLct), PolicyEngine>,
    roles: Map<RoleLct, CompiledRole>,
    authority: AuthorityIndex,
    mrh: MrhIndex,
    artifacts: CompiledArtifactManifest,
    hub_policy: CompiledHubPolicySet,
}
```

The snapshot is held behind an atomic `Arc` swap, not a broad mutable lock.

### 8.2 Launch sequence

1. Open and decrypt vault.
2. Read latest governance envelope.
3. Verify schema and envelope digest.
4. Verify amendment linkage and operator signatures.
5. Validate all policy, role, authority, MRH, artifact, and Hub projection references.
6. Compile the immutable snapshot.
7. Verify the running gate core against `artifact_manifest`.
8. Atomically publish the snapshot.
9. Generate transparency mirrors.
10. Start agent-facing gate service.

Until step 8 succeeds, every agent act is refused.

### 8.3 Update sequence

1. Operator UI displays current generation and exact proposed change set.
2. Backend validates the change and computes affected effective policies.
3. UI displays semantic diff, direction, blast radius, MRH impact, expiry, and simulation.
4. Operator signs the exact change-set digest with user presence.
5. Irreversible changes collect the law-required quorum.
6. Backend commits a new vault envelope using compare-and-swap on `generation`.
7. Backend compiles the new snapshot before activation.
8. Memory snapshot swaps atomically.
9. Mirrors regenerate.
10. Governance witness and Hub mirror events are queued.

If vault commit fails, memory does not change.

If snapshot compilation fails, the new envelope is not committed.

If mirror or Hub delivery fails, the local law remains active; the failure is visible, witnessed, and retried. A projection failure cannot roll back or silently alter local authority.

---

## 9. Policy model

### 9.1 Layers

Policy composes through four explicit layers:

1. **Global baseline** — selected preset plus global amendments.
2. **Role layer** — amendments applicable to anyone validly filling the role.
3. **Agent layer** — amendments applicable to the proven member across roles.
4. **Agent-in-role layer** — the most specific amendments for a member occupying a role.

### 9.2 Tightening and loosening

Every non-global amendment records its direction relative to the parent effective policy:

```rust
struct PolicyDelta {
    id: String,
    target_rule: RuleId,
    effect: PolicyEffect, // Tighten | Loosen | Replace | Add | Disable
    change: RulePatch,
    reason: String,
    granted_by: OperatorLct,
    created_at: Timestamp,
    expires_at: Option<Timestamp>,
    source_escalation: Option<EscalationId>,
}
```

Loosening is not a hidden grant channel. It is law, with the same provenance, expiry, witness, mirror, and generation semantics as tightening.

A temporary exception is represented as an expiring policy delta in the vault. It does not live only in process memory.

### 9.3 Precedence

For the same rule identity, specificity determines the effective amendment:

```text
agent-in-role > agent > role > global
```

Within one layer, each rule identity may have at most one live amendment. Duplicate live amendments are invalid governance state.

Independent matching rules continue to resolve using the policy engine’s priority and conflict rules.

The UI must show the complete provenance stack for an effective result:

```text
Global safety preset: deny
Role reviewer: no change
Agent member: loosen to warn until 2026-08-05T12:00Z
Agent-in-role reviewer: tighten to deny
Effective: deny
```

### 9.4 Constitutional code invariants

Not every fail-closed property is policy content.

The following are implementation invariants and cannot be loosened by ordinary policy:

- no decision without a valid memory snapshot;
- no policy mutation without operator-presence authorization;
- no unapproved gate core;
- no unapproved shim;
- no role act without authorized occupancy;
- no file mirror as a decision source;
- no silent failure-open behavior;
- no partial member/role dual-chain commit.

These invariants define what it means for the governor to exist. They do not decide whether a particular tool or path is allowed.

---

## 10. Operator UI as the only mutation surface

### 10.1 Required security property

Law mutation is accepted only through the operator-presence control plane served by Hestia.

The backend must require:

- authenticated operator LCT;
- fresh challenge;
- signature bound to the exact change-set digest;
- proof of user presence where supported;
- expected current generation;
- reason;
- required quorum based on stakes.

There is no generic bearer-only endpoint that accepts arbitrary policy JSON.

### 10.2 Surfaces that must not mutate governance

- CLI policy commands;
- MCP tools;
- harness hooks;
- direct vault-file manipulation;
- transparency mirror files;
- environment variables;
- Hub connectors;
- GitHub connectors;
- migration scripts after genesis;
- unattended scheduled tasks.

The existing `hestia policy set`, override, and add-rule mutation commands must be removed or converted to read-only commands that open the operator UI.

### 10.3 Required UI tools

#### Law editor

- select and edit presets;
- inspect all rules and priorities;
- add, change, disable, or remove rules;
- show semantic diff;
- run policy simulation against synthetic and recent witnessed acts;
- show effective policy generation and digest.

#### Role editor

- create and retire role entities;
- set role LCT and human label;
- set minimum authority level;
- set role MRH;
- set role policy deltas;
- view active occupancies;
- revoke occupancies;
- show role witness chain and role trust.

#### Agent editor

- inspect proven member identity and key binding;
- set authority grants and expiry;
- set agent MRH;
- set agent policy deltas;
- set agent-role policy deltas;
- show active occupancies;
- show member witness chain and role links.

#### Artifact assurance editor

- display running gate core digest and approval state;
- display every installed shim, expected path, actual digest, owner, mode, and status;
- approve a candidate core or shim digest for upgrade;
- revoke a digest;
- display last per-call integrity failure.

#### Escalation editor

- show the refused act and winning rule;
- show current effective policy stack;
- show proposed amendment and requested scope;
- allow operator to modify duration and blast radius;
- simulate effect;
- approve as a policy change, or refuse;
- never issue a bypass token.

#### Mirror and Hub status

- show file-mirror generation/digest/divergence;
- show Hub mirror generation, MRH projection, delivery, receipt, and lag;
- allow retry of delivery without changing law.

---

## 11. Escalation and appeal

### 11.1 Escalation is a policy amendment request

A gate denial may include a structured amendment request template:

```rust
struct PolicyEditRequest {
    id: EscalationId,
    requester: MemberLct,
    requested_role: Option<RoleLct>,
    denied_act_digest: Digest,
    current_generation: u64,
    winning_rule: RuleId,
    requested_change: ProposedPolicyDelta,
    reason: String,
    evidence: Vec<EvidenceRef>,
    requested_expiry: Option<Timestamp>,
}
```

The request does not grant anything.

If approved, the operator UI commits a new vault generation. The original act must be retried and evaluated normally against the amended law.

### 11.2 No one-shot bypass

Remove the conceptual path:

```text
deny -> approve this write -> claim approval -> bypass policy
```

Replace it with:

```text
deny -> request policy amendment -> operator edits law -> new generation -> retry -> ordinary evaluation
```

### 11.3 Appeal remains separate

An appeal asks:

> Was the prior governance decision correctly applied and attributed?

An escalation asks:

> Should the law change for future evaluation?

An appeal may repair conduct attribution or expose a defective rule. It does not itself edit policy or grant access.

The UI may offer “create policy amendment from upheld appeal,” but that remains a separate operator-signed act.

---

## 12. Authority and role occupancy

### 12.1 Authority model

Initial authority is explicit and ordinal:

```rust
struct AuthorityGrant {
    subject: MemberLct,
    level: u32,
    mrh: MrhExpression,
    granted_by: OperatorLct,
    reason: String,
    issued_at: Timestamp,
    expires_at: Option<Timestamp>,
    revoked_at: Option<Timestamp>,
    grant_id: GrantId,
}
```

A role declares:

```rust
struct RoleDefinition {
    role_lct: RoleLct,
    label: String,
    minimum_authority_level: u32,
    required_mrh: MrhExpression,
    occupancy_ttl: Option<Duration>,
    active: bool,
}
```

Authority is evaluated within MRH. A level granted for one domain does not automatically authorize another.

### 12.2 Authorization boundary

The authorization check occurs when an agent attempts to fill a role.

Order:

1. authenticate the member and resolve its member LCT;
2. resolve the requested role LCT;
3. load the role definition from the memory snapshot;
4. find a live authority grant for the member;
5. require `grant.level >= role.minimum_authority_level`;
6. require the authority grant MRH to encompass the role’s required MRH;
7. require no revocation or expiry;
8. create a generation-bound `RoleOccupancy`;
9. witness the successful occupancy on both member and role chains;
10. only then select role policy and permit role-context acts.

An unauthorized attempt:

- is refused;
- is witnessed on the member chain and governance chain;
- does **not** create a role-chain act, because the role was never validly occupied.

### 12.3 Occupancy token

```rust
struct RoleOccupancy {
    occupancy_id: Uuid,
    member_lct: MemberLct,
    role_lct: RoleLct,
    authority_grant_id: GrantId,
    governance_generation: u64,
    began_at: Timestamp,
    expires_at: Option<Timestamp>,
}
```

The occupancy is session state derived from the vault. It may live in memory because it is not independent authority.

Every governed act verifies that:

- the occupancy remains live;
- the member identity still matches;
- the current governance generation has not invalidated the role or authority grant;
- the authority grant still satisfies the role.

A governance update that changes role requirements or authority grants invalidates affected occupancy tokens. The next act must reauthorize occupancy.

### 12.4 Role declaration is not role assignment

Harness input may request a role, but the resulting session role is assigned only by the authorization boundary.

Unknown role, insufficient authority, expired grant, or MRH mismatch all fail closed to **no role occupancy**, not to a silently substituted privileged role.

A low-risk default member role may exist, but it must still be an explicit role definition with an explicit minimum authority requirement, not a string fallback that acquires authority by convention.

---

## 13. Single global gate and syntax shims

### 13.1 Global gate location

The authoritative gate runs as a Hestia-owned local service with direct access to the immutable `GovernanceSnapshot`.

It should be implemented in the Hestia daemon or a tightly coupled Hestia gate process, not as separately imported policy logic inside each harness process.

Harnesses communicate over a local authenticated transport:

- Unix domain socket with peer credentials on Unix-like systems;
- named pipe with client-process identity on Windows.

### 13.2 Shim contract

Each harness shim implements only:

```python
def parse_event(raw_event) -> NormalizedGateRequest: ...
def render_verdict(verdict: GateVerdict) -> HarnessResponse: ...
```

The normalized request contains no authority selected by the shim. Identity, role occupancy, MRH, policy, and artifact approval are resolved by the global gate.

### 13.3 Per-call shim assurance

On every call, the gate independently:

1. obtains the peer process identity from the local transport;
2. resolves the executing script path from the peer process, not from caller JSON;
3. maps that exact path to one registered shim in the memory artifact manifest;
4. opens it with no-follow semantics;
5. requires regular-file type, approved owner, and approved mode;
6. hashes its current bytes;
7. compares the digest to the vault-approved digest;
8. verifies the harness profile/version and registered event contract;
9. rejects on any discrepancy.

A modified shim cannot claim the digest of another approved shim because the gate derives the path from the peer process and the vault manifest.

### 13.4 Gate-core assurance

The artifact manifest contains:

```rust
struct GateCoreApproval {
    build_digest: Digest,
    version: String,
    approved_at: Timestamp,
    approved_by: OperatorLct,
    revoked: bool,
}
```

At startup, the gate compares its embedded build digest to a live approved entry.

On every request, the running digest identifier is compared to the memory snapshot’s approved core digest. This is cheap and prevents a governance generation from silently approving a different execution engine.

If the core is unapproved, Hestia exposes only the operator recovery UI. It processes no agent acts.

### 13.5 Upgrade flow

1. Candidate core or shim is installed but inactive.
2. Operator UI displays old and new digest, diff metadata, version, and affected harnesses.
3. Operator approves the candidate digest into a future governance generation.
4. New artifact activates only after that generation is committed.
5. Old digest may remain valid for a bounded overlap window or be revoked immediately.
6. The UI shows which running processes still use the old digest.

### 13.6 No local fallback

A shim never evaluates a read class locally and never consults a policy mirror because the central gate is down.

If the gate cannot be reached, the shim returns a typed fail-closed refusal.

“Stop the daemon, then act” must never be a bypass.

---

## 14. Separate member and role witness chains

### 14.1 Chain model

Every member LCT has a member witness chain.

Every role LCT has a role witness chain.

A governed act performed while occupying a role appends one event to each chain in one storage transaction.

```rust
enum WitnessChainKind {
    Member(MemberLct),
    Role(RoleLct),
    Governance,
}
```

### 14.2 Shared act envelope

```rust
struct GovernedActEnvelope {
    act_id: Uuid,
    member_lct: MemberLct,
    role_lct: RoleLct,
    occupancy_id: Uuid,
    governance_generation: u64,
    policy_decision_digest: Digest,
    action_digest: Digest,
    timestamp: Timestamp,
}
```

The member event records what the agent did and under which occupancy.

The role event records what was done in the role’s capacity and by which member.

Both reference the same `act_id` and `occupancy_id`.

### 14.3 Atomicity

Member and role entries are committed atomically.

If either append fails, neither entry commits and the act fails closed before execution where the gate is pre-act.

There must never be a successful role act with no corresponding member accountability event, or a successful member-as-role act with no role history.

### 14.4 RDF link model

After both chain entries exist, Hestia emits a graph projection:

```turtle
@prefix web4: <https://web4.io/ontology#> .
@prefix hestia: <https://hestia.local/ontology#> .

<urn:hestia:act:ACT_ID> a hestia:GovernedAct ;
  web4:entity <MEMBER_LCT> ;
  web4:role <ROLE_LCT> ;
  hestia:occupancy <urn:hestia:occupancy:OCCUPANCY_ID> ;
  hestia:memberWitness <urn:hestia:chain:MEMBER_ENTRY_HASH> ;
  hestia:roleWitness <urn:hestia:chain:ROLE_ENTRY_HASH> ;
  hestia:governanceGeneration "42" .

<urn:hestia:occupancy:OCCUPANCY_ID> a hestia:RoleOccupancy ;
  hestia:filledBy <MEMBER_LCT> ;
  hestia:fillsRole <ROLE_LCT> ;
  hestia:authorizedBy <urn:hestia:authority:GRANT_ID> .
```

The exact new predicates remain in the Hestia namespace until coordinated additions land in the Web4 ontology.

### 14.5 Trust and reputation separation

- Member-chain evidence updates member-scoped trust.
- Role-chain evidence updates role-scoped trust.
- Agent-in-role derivation can traverse both through the occupancy link.
- The role does not inherit the agent’s unrelated history.
- The agent remains accountable for acts performed in a role.
- Replacing the agent filling a role does not erase role continuity.

---

## 15. Transparency mirrors

### 15.1 Mirror tree

Recommended layout:

```text
<HESTIA_HOME>/mirrors/governance/
  current.json
  history/<generation>.json
  global-policy.json
  roles/<role-lct>.json
  agents/<member-lct>.json
  effective/<member-lct>--<role-lct>.json
  artifacts.json
  hub-status.json
  rdf/governance.ttl
```

### 15.2 Mirror requirements

Every mirror includes:

- non-authoritative marker;
- source vault generation;
- source envelope digest;
- generated timestamp;
- schema version;
- projection MRH;
- signature or MAC over canonical bytes;
- explicit omitted-field list;
- local divergence state if applicable.

### 15.3 Mirror failure behavior

A mirror-write failure does not change policy or roll back an active generation.

It must:

- raise an operator-visible critical warning;
- append a governance witness event;
- retry;
- expose stale generation and last successful mirror time.

The gate continues to use the valid memory snapshot.

---

## 16. Hestia-to-Hub mirroring

### 16.1 Direction and authority

Hestia is authoritative for its local constellation governance.

Hub receives a signed projection. Hub cannot edit the Hestia source state.

Hub may use the signed projection as authoritative evidence of what Hestia asserted for the exported MRH, subject to Hub’s own law.

### 16.2 MRH projection

Before export, Hestia applies a declared projection MRH.

The projection must exclude:

- local filesystem paths that have no Hub meaning;
- local operator device labels;
- local-only secret references;
- harness installation paths;
- private policy details outside the Hub interaction boundary;
- unrelated agent permissions.

The projection may include:

- Hestia sovereign LCT;
- governance generation and digest;
- exported role definitions and role LCTs;
- role authority requirements relevant to Hub interactions;
- member authority attestations relevant to exported roles;
- active role occupancy attestations;
- policy norms governing Hub-facing acts;
- revocations and expiries;
- artifact assurance summary where relevant;
- member/role act RDF links selected for publication.

### 16.3 Signed projection envelope

```rust
struct GovernanceProjection {
    source_lct: Lct,
    source_generation: u64,
    source_envelope_digest: Digest,
    projection_mrh: MrhExpression,
    projected_state: ProjectedGovernanceState,
    issued_at: Timestamp,
    expires_at: Timestamp,
    signature: Signature,
}
```

Hub verifies source identity, signature, monotonic generation, expiry, and MRH.

### 16.4 Hub storage and use

Hub stores the projection as an immutable signed mirror with receipt metadata.

If Hub policy depends on Hestia’s projected governance, Hub first imports the projection into its own authoritative policy store and memory. Hub does not make hot-path decisions by fetching a file or live remote endpoint.

Likewise, if a Hub law projection must constrain a Hestia cross-domain act, Hestia imports the signed Hub projection into its vault before it can participate in local decisions.

This preserves the vault-only rule on both sides.

### 16.5 Cross-domain composition

For a Hub-facing act:

- Hestia local effective policy applies;
- any valid imported Hub policy applicable within the act’s MRH applies;
- the cross-domain result uses the stricter blocking consequence unless an explicit inter-domain procedure defines another resolution;
- neither domain may silently loosen the other domain’s law.

### 16.6 Delivery semantics

- Local governance activation does not wait for Hub availability.
- Delivery is queued and retried.
- Hub acknowledgment records generation and digest.
- Out-of-order or replayed generations are refused.
- The operator UI shows local generation, last delivered generation, last acknowledged generation, and lag.

---

## 17. API and protocol requirements

### 17.1 Agent-facing gate request

```json
{
  "protocol": "hestia-gate-v1",
  "harness": "claude-code",
  "event_type": "PreToolUse",
  "event": { "normalized": true },
  "member_session": "opaque-authenticated-session",
  "requested_role": "role:lct",
  "occupancy_id": "uuid-or-null"
}
```

The gate ignores caller-provided authority fields and resolves identity, occupancy, MRH, and policy from authenticated state.

### 17.2 Gate verdict

```json
{
  "decision": "allow|warn|deny|escalate",
  "reason_code": "typed.code",
  "reason": "human-readable explanation",
  "generation": 42,
  "policy_digest": "sha256",
  "winning_rule": "rule-id",
  "member_lct": "lct",
  "role_lct": "lct-or-null",
  "occupancy_id": "uuid-or-null",
  "remedy": {
    "type": "policy_edit_request|appeal|retry_later|none",
    "template": {}
  }
}
```

### 17.3 Operator change set

```json
{
  "expected_generation": 42,
  "changes": [],
  "reason": "operator rationale",
  "simulation_digest": "sha256",
  "operator_lct": "lct",
  "challenge": "nonce",
  "signature": "signature-over-exact-change-set",
  "user_presence": true
}
```

### 17.4 No mutation MCP tools

MCP may expose read-only policy inspection and policy-edit request submission.

It must not expose:

- set preset;
- add or remove rule;
- alter role;
- alter authority;
- grant scope;
- approve artifact;
- commit policy amendment.

---

## 18. Failure modes

| Failure | Required behavior |
|---|---|
| Vault sealed or unreadable | Refuse all governed acts; expose operator recovery UI only |
| Governance envelope malformed | Refuse startup into agent-serving mode |
| Core digest not approved | Refuse all agent acts; recovery UI only |
| Shim digest mismatch | Refuse that call; witness integrity failure |
| Shim path symlink/special file | Refuse that call |
| Gate transport unavailable | Shim refuses; no local decision |
| Unknown member identity | Refuse before role or policy selection |
| Role authority insufficient | Refuse occupancy; member-chain evidence only |
| Role grant revoked mid-session | Invalidate occupancy; reauthorization required |
| Policy generation changes mid-act | Act completes or restarts under one generation; never mixed |
| Mirror modified | Decision unchanged; show divergence; regenerate |
| Mirror write fails | Policy remains active; critical visible failure and retry |
| Hub unavailable | Local policy remains active; queue signed projection |
| Hub projection expired | Hub refuses its use; Hestia shows lag |
| Imported Hub projection expired | Hestia refuses acts requiring it or applies local-only policy according to explicit law; never silently treats expiry as allow |
| Dual-chain append fails | Neither chain entry commits; pre-act operation refused |

---

## 19. Migration plan

### Phase 0 — freeze new authority paths

- No new file-based policy or scope inputs.
- No new harness-local policy branches.
- No new CLI mutation commands.
- Document every current decision input and mutation surface.

### Phase 1 — governance envelope and mirrors

- Expand `VaultPolicyState` into `GovernanceEnvelope`.
- Add generation, previous digest, amendments, signatures, role definitions, authority, MRH, and artifact manifest.
- Build immutable memory snapshot.
- Generate non-authoritative mirrors on launch/update.
- Add mirror-divergence dashboard.

### Phase 2 — operator-only mutation

- Replace generic policy mutations with exact change-set workflow.
- Require operator-presence signature bound to diff.
- Add generation compare-and-swap.
- Remove CLI law mutation.
- Remove any direct file import.
- Convert current instance grants and scope grants into vault policy deltas.

### Phase 3 — roles and authority

- Create role definitions and role LCT registry.
- Add authority grants and role minimum requirements.
- Authenticate member identity.
- Establish authorized occupancy boundary.
- Replace caller-declared role selection.
- Add operator role/agent/occupancy UI.

### Phase 4 — single gate and assured shims

- Move authoritative evaluation into the Hestia global gate service.
- Implement syntax-only shims for each harness.
- Add local authenticated transport and peer-process resolution.
- Add per-call shim hash verification.
- Add core build approval and recovery mode.
- Remove harness-local scope, forbidden, remedy, and decision logic.
- Remove policy-file fallback.

### Phase 5 — escalation as amendment

- Replace approval/claim bypass semantics with `PolicyEditRequest`.
- Add UI diff, blast radius, simulation, expiry, and approval.
- Require retry under new generation.
- Preserve appeal as separate adjudication path.

### Phase 6 — member and role chains

- Add chain namespaces and heads per member and role.
- Add atomic dual append.
- Add occupancy events.
- Add RDF act and occupancy links.
- Split trust/reputation derivation by member, role, and agent-in-role traversal.

### Phase 7 — Hub mirror

- Define Web4 governance projection schema in shared policy substrate.
- Implement MRH export filter.
- Sign, deliver, acknowledge, replay-protect, and expire projections.
- Add Hub storage and operator visibility.
- Add optional signed Hub policy import into Hestia vault for cross-domain decisions.

---

## 20. Acceptance criteria

### 20.1 Vault and memory authority

- Editing every generated mirror to allow a denied act changes no decision.
- Deleting every mirror changes no decision.
- The dashboard reports mirror divergence and regenerates it.
- No gate code reads `identity.json`, policy mirror files, or environment-granted scope.
- Every verdict reports the vault generation and policy digest used.

### 20.2 Operator-only law edits

- `hestia policy set`, override, add-rule, and equivalent mutators no longer edit the vault.
- No MCP tool can mutate governance.
- A policy update without a fresh operator-presence signature is refused.
- A stale expected generation is refused.
- An irreversible change without required quorum is refused.

### 20.3 Tightening and loosening

- Operator can tighten and loosen globally, per role, per agent, and per agent-role pair.
- Every loosening has operator, reason, generation, and optional expiry.
- An expired loosening stops affecting the next decision without restart.
- Effective-policy UI explains every layer and winning result.

### 20.4 Escalation

- Approving an escalation creates a new vault generation.
- No approval token allows the original act directly.
- Retrying before policy activation remains denied.
- Retrying after an applicable amendment is evaluated normally and may pass.
- Denying an escalation changes no policy.

### 20.5 Role authorization

- An agent below a role’s minimum authority cannot create an occupancy.
- An unauthorized attempt creates no role-chain act.
- Granting sufficient authority through UI permits occupancy.
- MRH mismatch refuses occupancy even if numeric level is sufficient.
- Revoking authority invalidates existing occupancy on the next act.
- Unknown or caller-invented roles never become active roles.

### 20.6 Gate and shims

- Every harness executes only a syntax shim.
- Static tests reject policy vocabulary or decision branches in shims.
- Modifying one byte of a shim causes the next call to fail closed.
- Replacing a shim with a symlink causes the next call to fail closed.
- Calling the gate from an unregistered process fails closed.
- Running an unapproved core build exposes recovery UI only.
- Killing the gate causes all shims to refuse rather than evaluate locally.

### 20.7 Dual chains and RDF

- An authorized role act atomically creates one member-chain entry and one role-chain entry.
- Both entries share one act ID and occupancy ID.
- RDF links member, role, occupancy, authority grant, and both witness hashes.
- A storage fault between the two appends leaves neither committed.
- Member and role trust can be queried independently.
- Agent-in-role evidence can traverse both chains without conflating them.

### 20.8 Hub mirror

- Hub receives a signed projection with generation, digest, MRH, and expiry.
- Fields outside the export MRH do not appear.
- Hub refuses replayed, out-of-order, expired, or invalidly signed projections.
- Hestia continues local operation while Hub is unavailable.
- UI displays delivery and acknowledgment lag.
- A Hub projection cannot mutate Hestia law.

---

## 21. Required test families

- vault-envelope validation and generation-chain tests;
- immutable snapshot and atomic-swap concurrency tests;
- mirror non-authority mutation tests;
- UI-only mutation route tests;
- operator signature and quorum tests;
- policy-layer precedence and expiry tests;
- escalation-to-amendment integration tests;
- member identity authentication tests;
- authority and MRH occupancy tests;
- occupancy invalidation tests;
- shim no-policy AST tests;
- peer-process and per-call digest tests on Windows and Unix;
- core approval/recovery tests;
- fail-closed transport tests;
- dual-chain transaction tests;
- RDF vocabulary and join tests;
- Hub MRH projection and signature tests;
- live per-harness end-to-end tests using installed shims.

Every governance test must behave consistently under:

- bare invocation;
- the repository test runner;
- pytest where applicable;
- CI;
- installed runtime smoke test.

A green on zero discovered artifacts, zero shims, zero roles, or zero mirrors must be a failure unless the test explicitly targets the empty state.

---

## 22. Open design questions

These do not block the PRD’s core direction but must be resolved before implementation completes.

1. What initial numeric authority scale and names should be published?
2. Is the lowest member role automatically granted at genesis, or explicitly granted through onboarding UI?
3. Which policy changes are classified as irreversible and require quorum?
4. Should all loosenings require an expiry by default, with permanent loosening requiring an explicit waiver?
5. What exact user-presence mechanism is available across browser, desktop, TPM, and security-key deployments?
6. Should role occupancy always expire, or may some occupancies last until authority or policy changes?
7. Which Hestia-specific RDF predicates should be proposed for Web4 ontology standardization?
8. Should member and role chains use separate SQLCipher tables in one transaction or physically distinct stores with a transaction coordinator?
9. How should Hub policy conflicts beyond strict blocking consequence be adjudicated?
10. What recovery UI and signed rescue artifact are permitted when the active gate core is not approved?
11. How are candidate shim paths discovered and approved without allowing the harness to choose its own registered path?
12. Which local governance fields are safe and useful to publish to Hub by default?

---

## 23. Release gates

The consolidated gate must not be activated fleet-wide until all P0 gates pass:

- vault envelope and immutable memory snapshot complete;
- operator-only mutation enforced;
- member identity authenticated;
- role authority boundary implemented;
- core and every active shim approved in the vault;
- per-call shim assurance operational;
- no harness-local decision logic remains;
- no file policy fallback remains;
- fail-closed installed smoke tests pass on every harness;
- rollback/recovery UI tested;
- fleet deployment manifest confirms the approved artifacts are the running artifacts.

Hub mirroring and dual-chain RDF may roll out after the local P0 path, but the chain split should precede any claim that role authority and role conduct are independently accounted.

---

## 24. Final invariant

The target system should make the following statement literally true:

> An authenticated agent may act only through an approved harness shim, verified on that call, into one approved global gate core. The core decides only from a validated in-memory snapshot loaded from the encrypted vault. The agent may act as a role only after its authority is proven sufficient at the occupancy boundary. The resulting act is witnessed separately as the member’s act and the role’s act, with an RDF link stating that the agent filled the role. A human changes outcomes by editing the law through the operator UI; no file, agent, shim, CLI, or connector can edit or substitute for that law.

That is the human in the loop without making the human the loop.
