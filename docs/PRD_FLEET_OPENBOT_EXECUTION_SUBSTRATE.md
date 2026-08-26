# PRD — Fleet extension: execution-substrate lessons from OpenBot

**Status:** proposed companion to [`PRD_FLEET.md`](PRD_FLEET.md)  
**Scope:** concrete lessons to adopt, prototype, watch, or explicitly reject from CopilotKit OpenBot while preserving Hestia's authority/evidence model.  
**External baseline:** OpenBot `main` at [`88078a4`](https://github.com/CopilotKit/OpenBot/commit/88078a412c52d5e86ee009e4ed1690ecd6c30562), reviewed 2026-08-25 PT.  
**Hestia baseline:** `main` at `af89203`.  
**Companions:** [`PRD_FLEET.md`](PRD_FLEET.md), [`PRD_ASSURANCE.md`](PRD_ASSURANCE.md), [`PRD_GOVERNANCE.md`](PRD_GOVERNANCE.md), [`PRD_ROLE_SCOPE_BRIDGE.md`](PRD_ROLE_SCOPE_BRIDGE.md), [`GATE_BYPASS_CATALOG.md`](GATE_BYPASS_CATALOG.md), [`HESTIA_OPENBOT_TECHNICAL_COMPARISON.md`](HESTIA_OPENBOT_TECHNICAL_COMPARISON.md).

---

## 0. Directive

OpenBot independently converges on a large part of the execution architecture already selected in the Fleet PRD: agent actions should return through a server-controlled boundary, targets should be resolved from authoritative state rather than caller prose, policy should decide before dispatch, and the execution environment should be separable from the agent process.

The conclusion is **not** to adopt OpenBot's product model or make it a dependency. The conclusion is to stop treating execution plumbing as novel Hestia work where another project has already exposed the difficult edges.

This extension therefore applies one rule throughout:

> **Borrow execution mechanisms and failure lessons. Do not borrow authority semantics.**

Hestia remains the authority/evidence plane. OpenBot is a reference implementation, possible integration target, and adversarial test corpus for the execution substrate beneath it.

---

## 1. Non-negotiable invariants

Nothing in this document may weaken these Fleet invariants.

1. **One law path.** Every Hestia-governed action, whether carried by a native runner, AG-UI agent, browser computer, MCP connector, channel adapter or external executor, enters the same LAW evaluation path.
2. **One authority source.** Tool grants, OpenBot Bot configuration, framework permissions, container capabilities and UI affordances are capacities. They do not become Hestia authority.
3. **One evidence model.** Operational execution logs may exist, but the Hestia witness/evidence contract remains authoritative for governed conduct.
4. **Identity is not a session id.** A runtime handle, OpenBot Bot id, AG-UI thread id, browser profile or container name may correlate work but may not authenticate the principal.
5. **Instructions do not grant.** Skills, prompts, routing hints and tool narrowing may reduce what is offered to a model. They never widen what law admits.
6. **Assurance is derived, never implied by product names.** A "sandbox", "computer", "gateway" or "takeover" label does not create A2/A3. Hestia derives the profile from the actual execution topology and tool registry.
7. **Local-first remains a hard constraint.** No OpenBot-derived feature may make PostgreSQL, Kubernetes, CopilotKit Intelligence, a cloud KMS or a managed control plane mandatory for ordinary Hestia operation.
8. **Hub invariant remains:** witness, do not control. Execution work on another seat is requested/claimed through existing Web4 mechanics; no imported orchestration layer becomes a fleet-wide remote writer.

---

## 2. What OpenBot teaches that is directly relevant

### 2.1 The action boundary must see resolved state

OpenBot's browser gateway does not rely solely on the model saying "click Submit". It keeps a server-side snapshot mapping element references to page state and evaluates policy against that resolved target. See its [`gateway.ts`](https://github.com/CopilotKit/OpenBot/blob/88078a412c52d5e86ee009e4ed1690ecd6c30562/server/src/computer/gateway.ts).

This reinforces the Fleet PRD's decision to remove lexical classification from the native path. A typed tool call is necessary but still insufficient if its target is caller-described. The gateway must bind the call to the object the executor will actually touch.

### 2.2 Mechanism and effect must be separate fields

OpenBot learned that `computer_click` is not equivalent to "activate" and that a deny on one gesture can be bypassed through Enter/Space. It likewise classifies MCP tools by read/write effect rather than expecting an operator to enumerate vendor tool names.

Hestia should adopt this at the canonical-act level rather than as a browser special case.

### 2.3 Isolation is a topology, not a policy rule

OpenBot's shell commentary states the point correctly: a shell can reach whatever its container can reach; command-text filters are not containment. Several OpenBot defects came from deployment topology disagreeing with the intended boundary, including agent-computer access to PostgreSQL under Compose and the all-in-one image.

This maps directly to Hestia's A1/A2/A3 vocabulary: policy can refuse a command; only an external runtime can constrain what a compromised executor can reach.

### 2.4 Human takeover is an authority lease over effectors, not a screen mode

OpenBot issue [#246](https://github.com/CopilotKit/OpenBot/issues/246) is a useful negative requirement. Its UI/control state could say a human held the computer while Bot shell and file-write calls still mutated the same environment.

Hestia must define takeover in terms of **which mutating effectors are admitted during the lease**, not which browser socket is visible.

### 2.5 Runtime identity needs an epoch, not only a generation counter

OpenBot issues [#158](https://github.com/CopilotKit/OpenBot/issues/158) and [#236](https://github.com/CopilotKit/OpenBot/issues/236) expose a subtle class of stale-reference bugs: a snapshot generation is meaningful only within one run of the computer, and replicas/restarts can make a stale ref appear current again.

Hestia should treat executor-run identity as part of every resolved target from the start.

### 2.6 Credential custody must include audience binding

OpenBot issue [#237](https://github.com/CopilotKit/OpenBot/issues/237) demonstrates that "encrypted at rest" is not enough if a credential can later be associated with a different destination. Hestia's vault model already points toward audience-bound/brokered credentials; the execution substrate must not weaken that by treating credential ids as generic bearer references.

### 2.7 Durable work should be claimed, leased and idempotent

OpenBot's bot-to-bot/routines/Kubernetes work converges on a durable claimed-work primitive rather than in-process callbacks. That is highly relevant to Fleet's existing "claimable board, never dispatcher" decision.

The implementation substrate differs — OpenBot uses PostgreSQL — but the correctness properties are reusable.

### 2.8 Live activity and durable evidence are different products

OpenBot distinguishes a convenient Activity view from the durable audit trail. Hestia should do the same. A live screen, shell transcript or run activity pane may be ephemeral and high-volume; governance evidence is a deliberately smaller, durable, attributable record.

---

## 3. Adoption matrix

| Item | Decision | Why |
|---|---|---|
| AG-UI agent transport | **ADOPT / prototype now** | Reduces harness-specific shims and gives Fleet a framework-neutral remote-agent seam |
| Resolved target snapshots | **ADOPT** | Required to make typed acts correspond to real executor targets |
| Effect taxonomy separate from tool name | **ADOPT** | Prevents mechanism-specific policy gaps |
| Per-member execution-computer abstraction | **ADOPT** | Separates governance from browser/container implementation |
| Human takeover lease covering all writes | **ADOPT** | Necessary semantic definition of "human has control" |
| Executor session/epoch in target refs | **ADOPT** | Prevents stale refs across restart/replica/resume |
| Skills as instructions, not grants | **CONFIRM existing doctrine** | Already aligned with role-scope bridge; add conformance tests |
| Per-run tool narrowing by skill relevance | **PROTOTYPE** | Useful for model reliability/context size; never an authority boundary |
| Credential-to-audience binding | **ADOPT** | Required by vault doctrine and OpenBot failure evidence |
| Atomic credential rotation | **ADOPT where not already guaranteed** | Prevents half-rotated live state |
| Durable claimed work with leases/idempotence | **ADOPT semantics** | Needed for wake/routines/handoffs without one process becoming coordinator |
| Persistent browser profile/workspace per member | **PROTOTYPE** | Valuable for autonomous agents; implementation should remain replaceable |
| gVisor / agent-sandbox integration | **WATCH + prototype for A3** | Strong external-isolation candidates; not required for local A1/A2 work |
| Kubernetes/EKS deployment | **WATCH** | Useful enterprise/A3 evidence, wrong as a universal Hestia prerequisite |
| Stable per-agent egress/proxy identity | **PROTOTYPE later** | Useful enterprise attribution/control; not core Fleet F0/F1 blocker |
| OpenBot/CEL policy engine | **DO NOT ADOPT as authority** | Hestia law/escalation/appeal semantics are richer and already canonical |
| PostgreSQL as Hestia state dependency | **REJECT** | Violates small local-first seat requirement |
| CopilotKit Intelligence as required threads/memory | **REJECT as dependency** | Hestia identity/evidence must survive without a managed/external memory plane |
| OpenBot Bot id as member identity | **REJECT** | Runtime identifier is not an LCT principal |
| Tool narrowing as security | **REJECT explicitly** | Offered-tools set is ergonomics, not authorization |
| Shell inside an A2-bounded registry | **REJECT by default** | Shell collapses the bounded-effector argument and lowers assurance |
| All-in-one agent computer + privileged state store | **REJECT** | OpenBot's own defects demonstrate the topology failure |

---

## 4. Required architecture additions

### 4.1 `AgentTransport`: add AG-UI as a first-class transport

Fleet currently names native model backends and hooked sessions. Add a protocol-neutral remote-agent transport:

```rust
pub enum AgentTransport {
    NativeModel(ModelBackend),
    VendorHarness(VendorHarnessRef),
    RemoteAgUi(AgUiEndpointRef),
    LocalAgUi(AgUiProcessRef),
}
```

`RemoteAgUi` / `LocalAgUi` do **not** imply authority. They are message/event transports.

Requirements:

- authenticate the transport independently of AG-UI thread/session identifiers;
- normalize AG-UI tool calls/events into Hestia canonical act objects;
- preserve original transport event ids for correlation/provenance;
- reject ambiguous/unsupported tool-call dialects rather than silently rewriting consequential input;
- allow explicit compatibility normalization only as a witnessed transport adaptation with source dialect recorded;
- never let the remote endpoint choose its Hestia principal, role, occupancy or tool registry by assertion;
- tool results containing Hestia denials must return as structured results visible to the agent loop.

**Acceptance:** the same canonical act produced from an AG-UI remote agent and a Hestia native model reaches the same LAW predicate and produces semantically identical evidence.

### 4.2 `ExecutionComputer`: isolate execution mechanics behind a trait

Hestia should own the contract, not necessarily the browser implementation.

Illustrative shape:

```rust
trait ExecutionComputer {
    fn run_id(&self) -> ExecutorRunId;
    async fn snapshot(&self) -> Result<ComputerSnapshot>;
    async fn navigate(&self, target: Url) -> Result<ObservedOutcome>;
    async fn activate(&self, target: ResolvedTarget, gesture: Gesture) -> Result<ObservedOutcome>;
    async fn type_text(&self, target: ResolvedTarget, text: SecretAwareText) -> Result<ObservedOutcome>;
    async fn read_file(&self, path: RelativePath) -> Result<ObservedOutcome>;
    async fn write_file(&self, path: RelativePath, payload: OpaquePayloadRef) -> Result<ObservedOutcome>;
    async fn run_command(&self, command: CommandSpec) -> Result<ObservedOutcome>;
    async fn control(&self, lease: ControlLeaseAction) -> Result<()>;
}
```

The trait is a **capacity boundary**. Hestia law decides whether a method may be invoked.

Initial providers may be:

- `LocalProcessComputer` for today's A1-compatible development;
- `DockerComputer` for per-member persistent workspace/profile work;
- later `GvisorComputer` / Kubernetes agent-sandbox provider for A3 experiments;
- an `OpenBotComputerAdapter` if direct composition proves worthwhile.

The provider must declare measured properties used to derive assurance:

```text
process_separation
uid_separation
filesystem_boundary
network_boundary
credential_visibility
shell_available
browser_profile_persistence
runtime_attestation
```

No provider self-declares `A3`; Hestia derives it from these properties and tests.

### 4.3 Canonical effect taxonomy

Extend/confirm the canonical act schema so every act carries both mechanism and effect.

Minimum effect vocabulary:

```text
observe
navigate
activate
input
read_data
write_data
read_file
write_file
execute
communicate_outward
spend
identity_or_authority_mutation
```

A mechanism is adapter-specific (`computer_click`, `mcp__jira__transitionIssue`, `shell`, etc.). The effect is policy-level.

Requirements:

- one act may carry multiple effects where necessary; do not force a misleading single label;
- unknown remote tools fail toward the more consequential classification where safe classification is impossible;
- effect classification source is recorded (`catalogue`, `schema`, `operator-reviewed`, `unknown-conservative`);
- an adapter cannot self-label its effect without a locally approved catalogue/schema binding.

**Acceptance:** alternate gestures/mechanisms producing the same consequence exercise the same law rule.

### 4.4 Resolved-target identity is `(executor_run, snapshot_generation, target_ref)`

Define:

```rust
ResolvedTargetRef {
    executor_run: ExecutorRunId,
    generation: u64,
    target_ref: String,
    observed_digest: Digest,
}
```

Rules:

1. a ref from a different executor run is stale even if generation matches;
2. a reset/resume/replacement that can change target meaning must change `executor_run`;
3. generation monotonicity is scoped to `executor_run`, never globalized by assumption;
4. the law decision is bound to the resolved target digest, not only the reference string;
5. the executor re-checks the target binding at dispatch where practical;
6. inability to resolve a cited target is a refusal, not a neutral empty target;
7. read-only page/snapshot operations may remain outside mutation law when they truly have no external side effect, but their records must be sufficient to bind later acts.

This is an explicit import of the failure lesson in OpenBot #158/#236.

### 4.5 Human control is a lease across all mutating effectors

Define a `ControlLease` with holder, principal, computer/member, issue time, expiry and reason.

During an active human-control lease:

- `navigate`, `activate`, `input`, `write_file`, `execute`, write-MCP and outward-communication effectors are refused to autonomous sessions unless the lease explicitly names an exception;
- read-only observation may continue so the agent can explain state;
- no action is queued for automatic replay after release unless the operator explicitly re-authorizes the queued act;
- acquisition/release/expiry are witnessed governance-control events;
- the UI must derive "human has control" from the same lease the gateway enforces.

**Acceptance:** a conformance test enumerates every registered mutating effector and proves it refuses during the lease. Adding a new mutating effector without updating this test fails CI.

### 4.6 Credential references are audience-bound capabilities

A connector credential reference must bind at minimum:

```text
credential_id
owner_principal
provider/kind
audience (host/service identity)
allowed operation class
expiry/rotation state
```

Requirements:

- attaching an existing credential to a different audience is refused unless a governed rebinding act explicitly authorizes it;
- connector URLs may not carry secrets in userinfo, query or fragment where those values can reach logs/evidence;
- remote redirects are revalidated against audience rules before credentials are resent;
- rotation of the current credential is atomic with replacement state;
- a raw credential value never appears in Hestia witness payloads;
- executor containers do not receive vault-wide environment state merely because one tool requires a credential;
- for OAuth user delegation, the authenticated person/member and the upstream subject are bound rather than collapsed into a deployment credential.

This extends, rather than replaces, `PRD_ASSURANCE` FR-2.

### 4.7 Skill-aware tool narrowing is ergonomics only

OpenBot's observation that large tool sets hurt model selection is worth testing, but the exact thresholds are implementation evidence, not universal law.

Add an optional per-run narrowing stage:

```text
role skills + message/context -> candidate tools
candidate tools INTERSECT authorized registry -> offered tools
```

Rules:

- narrowing cannot add a tool;
- narrowing failure returns the full **authorized** registry, never an unauthorized superset;
- audit/witness records may note what was offered and why, but authorization is still evaluated at act time;
- benchmarks must measure success/error rates across local/frontier models before hardcoding a cutoff.

The role-scope bridge remains normative for whether a skill itself flows to an occupant.

### 4.8 Durable claimed-work primitive

Fleet's wake scheduler, unattended routines, and multi-agent handoffs need one durable work primitive.

Required semantics:

```text
WorkItem {
  key, kind, claimant?, lease_until?, attempt,
  not_before, created_by, authority_ref,
  idempotence_key, state, last_error?
}
```

Properties:

- claim, do not push-assign;
- lease expires and can be reclaimed;
- worker renews while performing long work;
- completion is idempotent and cannot be overwritten by a stale claimant;
- attempts cap into a visible terminal state rather than retry forever;
- failed/gave-up retention and successfully-finished retention are separate clocks;
- idempotence key survives process restart;
- a claimed item carries the authority/evidence reference required to launch work; the queue itself grants nothing;
- one seat's queue never becomes authority to execute on another seat.

Local implementation should prefer Hestia's existing small-state substrate (SQLite/SQLCipher or purpose-built local store) over importing PostgreSQL. Hub-distributed work remains the claim-board model already selected in Fleet.

### 4.9 Activity UX and evidence UX remain separate

Add a product-level distinction:

**Activity** may include:

- current screen/frame;
- shell stdout/stderr;
- file names/sizes;
- current tool progress;
- live control state.

**Evidence** contains only governance-relevant, durable, attributable facts.

Requirements:

- the activity surface must not be described as the audit/evidence record;
- disappearing activity after reload is acceptable only when durable evidence still answers the consequential questions;
- secret payloads/file contents must not be copied into evidence by convenience;
- a historical screenshot, if persisted, must be tied to the exact turn/run and cannot silently become a live view of the current computer.

OpenBot's historical-frame bugs are useful warnings here: "screen now" and "screen when that decision happened" are distinct objects.

---

## 5. Negative requirements imported from OpenBot failure evidence

These are not criticisms to archive; they should become tests before Hestia builds the corresponding surface.

### N1 — the agent execution environment cannot reach the governance database/state by topology

If an executor has a shell, it must not be able to reach Hestia's vault/evidence stores merely because they share a container/network/UID. A password in the same environment is not a boundary.

### N2 — takeover must block every mutating path

A new mutating tool is unsafe until the takeover conformance test classifies it.

### N3 — stale refs fail closed across restart, resume, replacement and replica changes

Run/epoch identity is mandatory; generation alone is insufficient.

### N4 — credential audience is immutable without a governed rebind

Credential id possession does not authorize changing where the secret is sent.

### N5 — configuration plumbing must be tested in the deployed topology

An environment variable documented at the host is not "configured" until the intended executor actually receives it and only it. OpenBot's egress-proxy issues show why configuration tests must inspect the rendered runtime, not just the resolver function.

### N6 — a durable work key must permit the *next legitimate occurrence*

Idempotence must prevent duplicate execution of one occurrence without wedging future occurrences of the same recurring task. Separate event identity from task identity.

### N7 — transport history has one canonical tool-call dialect at the governance boundary

AG-UI/framework message shapes may differ internally, but the boundary validates and normalizes into one canonical representation before evidence or replay. Compatibility logic must be explicit and tested against persisted history, not only live events.

### N8 — an executor reset must define what is destroyed

Browser profile, workspace, persisted screenshots, refs, sessions and credentials each need explicit reset semantics. "Reset" may not leave historical sensitive frames while claiming the logged-in state is gone.

---

## 6. External-executor integration experiment

This is the highest-value experiment because it tests Hestia's architecture against a relying party Hestia does not control.

### 6.1 Goal

Use OpenBot as an external execution gateway while Hestia remains the identity/law/evidence authority.

### 6.2 Minimal seam

Add an optional OpenBot-side policy decision provider or thin fork path:

```text
OpenBot resolves candidate action
        |
        v
canonical bridge request
        |
        v
Hestia evaluates exact act
        |
 signed decision + obligations + expiry + audience
        |
        v
OpenBot verifies decision
        |
 execute or refuse
        |
        v
outcome returned to Hestia witness path
```

The exact code location is likely OpenBot's server gateway immediately before its local policy/audit execution path. The experiment must **not** replace OpenBot's own local safeguards; Hestia becomes an additional required decision for a selected Bot/tool set.

### 6.3 Why this matters

It is a direct proof of `PRD_ASSURANCE` FR-3:

> removing the agent-side Hestia hook does not authorize the action because the relying executor independently requires a valid Hestia decision.

The demo is stronger if:

- the agent is an unmodified AG-UI endpoint;
- the Hestia principal is authenticated independently of the AG-UI Bot id;
- the decision is bound to exact resolved target + executor audience;
- the verifier can validate without calling Hestia again;
- replaying the same decision for a different target or after expiry fails;
- Hestia being unavailable fails closed for the selected consequential action and produces Plane-E infrastructure telemetry rather than fake member misconduct.

### 6.4 Integration acceptance test

One deterministic scenario:

1. member M occupies role R with permission to browse/read but not submit purchases;
2. an AG-UI agent in OpenBot navigates to a test form;
3. read actions succeed;
4. an attempted submit resolves to the real target in OpenBot;
5. Hestia denies based on role/law and returns structured reason/remedy;
6. OpenBot refuses before side effect;
7. the agent sees the structured denial and adapts/escalates;
8. Hestia evidence links principal, role, exact act, decision and outcome;
9. removing the Hestia hook from the agent changes nothing about OpenBot's refusal requirement;
10. changing the action target invalidates any previously issued decision.

This should be considered a candidate F1/F2 dogfood milestone, not a dependency for all Fleet work.

---

## 7. Phase mapping onto the Fleet PRD

This document does not create a parallel roadmap. It refines F0-F6.

### Before / during F0 — identity and session substrate

Add:

- `ExecutorRunId` semantics;
- AG-UI transport authentication model;
- external-executor audience identity;
- credential audience binding review;
- `ExecutionComputer` capability declaration shape.

**Gate:** no runtime id or AG-UI field may substitute for principal authentication.

### F1 — native loop

Add:

- canonical effect taxonomy;
- AG-UI normalization prototype;
- resolved-target binding;
- one local execution-computer provider;
- structured denial return to both native and AG-UI loops;
- external-executor proof spike if capacity allows.

**Dogfood addition:** same act from native model and AG-UI endpoint yields the same canonical decision context.

### F2 — SAGE being / bounded gateway member

Add:

- bounded registry conformance test proving no shell/raw FS has leaked in;
- assurance derivation from execution provider + registry;
- skill/tool narrowing only after authority intersection;
- optional isolated computer provider prototype for one being.

**Gate:** widening the registry changes the displayed assurance profile immediately.

### F3 — lifecycle / wake scheduler

Add:

- durable claimed-work primitive;
- human-control lease semantics;
- reset/retire semantics for execution state;
- recurring-work idempotence tests.

### F4 — provider/API/subscription backends

Add:

- credential audience binding and atomic rotation tests;
- AG-UI remote endpoints as a transport option distinct from provider backends;
- explicit separation between vendor harness sessions and Hestia-native sessions in assurance display.

### F5 — channels

Add:

- `communicate_outward` effect classification independent of connector tool name;
- user/deployment credential subject binding;
- takeover/operator hold semantics for outward communication where applicable;
- stable egress identity/proxy experiment if enterprise use justifies it.

### F6 — fleet observation

Add:

- execution provider/profile projection per seat;
- executor-run freshness where a remote view shows current activity;
- no attempt to stream/control another seat through the observation surface;
- optional Kubernetes/gVisor evidence only as provider-specific assurance input.

---

## 8. Tests to add before corresponding features ship

A reusable conformance suite should contain at least:

1. **alternate activation paths:** click/Enter/Space hit the same consequence rule;
2. **unknown MCP tool:** conservatively classified rather than assumed read;
3. **stale target after restart:** same generation, different executor run refuses;
4. **stale target across replica:** target resolution does not rely on process-local memory;
5. **human takeover:** every mutating effector refuses, reads remain available as specified;
6. **new mutating tool:** fails takeover conformance until classified;
7. **credential re-address:** existing credential cannot be sent to another host by metadata mutation;
8. **credential in URL:** query/fragment/userinfo secret forms refuse before persistence/evidence;
9. **executor isolation:** shell cannot reach vault/evidence store in the claimed profile;
10. **reset:** all state advertised as reset is actually gone; historical evidence remains correctly attributed;
11. **work reclaim:** expired lease can be reclaimed without stale worker deleting the new claim;
12. **work recurrence:** successful occurrence does not wedge the next occurrence;
13. **history dialect:** persisted AG-UI/framework variants normalize or visibly refuse without corrupting the thread;
14. **activity/evidence split:** secret content shown to an executor never appears in witness payload by default;
15. **external verifier:** signed decision fails on wrong audience, wrong act digest, expiry and replay;
16. **hook removal:** external executor still refuses without a valid Hestia decision.

These tests are more valuable than copying OpenBot implementation details because they preserve the lessons even if both codebases change.

---

## 9. What to watch upstream

OpenBot is moving fast enough that periodic targeted review is justified.

Watch specifically for:

- changes to the AG-UI boundary and tool-call persistence dialect;
- per-Bot computer provider abstraction;
- agent-sandbox/gVisor/Kubernetes isolation lessons;
- bot-to-bot and routine work-queue implementation;
- credential/audience binding fixes;
- human-control semantics after #246;
- snapshot/run identity fixes after #158/#236;
- external policy-provider or signed-decision support;
- egress attribution/proxy design;
- any move from deployment-local Bot identities toward portable cryptographic agent identity.

Do **not** chase ordinary UI churn or copy every plugin. The purpose of watching is to harvest boundary lessons relevant to Hestia's execution substrate.

---

## 10. Explicit non-adoptions

To prevent "integration" from slowly becoming architectural capture:

### 10.1 No OpenBot policy-as-law

CEL expressions may be a useful adapter syntax, but Hestia's canonical law includes escalation, appeal, role occupancy, proof tiers, provenance and evidence semantics. OpenBot policy may be an additional local boundary, never the source of Hestia authority.

### 10.2 No required CopilotKit Intelligence

Threads/memory are useful product services. Hestia principal identity, law, session authority and evidence must remain valid if that service disappears.

### 10.3 No required PostgreSQL

A local Hestia seat must retain the small no-infrastructure deployment shape. Enterprise adapters may use external databases without making them the constitutional store.

### 10.4 No Kubernetes-first assumption

A Jetson-class seat is not a degraded Kubernetes cluster. Kubernetes is one possible A3 execution provider for enterprise/server environments.

### 10.5 No shell in the bounded-member default

Fleet's A2-by-construction argument rests on the member having only gateway-dispatched bounded effectors. A generic shell is an explicit escape from that boundary and must visibly lower the profile.

### 10.6 No tool-offering heuristic as authority

A model not seeing a tool is not evidence that it cannot act through another path. The real boundary remains law + executor.

---

## 11. Decision record

The architectural decision this extension adds to Fleet is:

> **Hestia will define a replaceable execution-computer and agent-transport layer, informed by OpenBot's proven boundary patterns, while keeping identity, authority, law, evidence, consequence and recourse in Hestia/Web4. AG-UI and an external OpenBot executor are preferred early interoperability experiments.**

This turns an adjacent project from a competitor-shaped distraction into what it is more usefully treated as: a mature source of execution-substrate lessons and a potential independent relying party against which Hestia can prove its stronger claims.

---

## 12. Completion criteria for this extension

This companion PRD can be marked **implemented for Fleet v1** when all of the following are true:

- [ ] canonical acts separate effect from mechanism;
- [ ] executor targets are bound to run/epoch + generation + target digest;
- [ ] one replaceable `ExecutionComputer` provider is used by a Hestia native session;
- [ ] AG-UI input can produce the same canonical act path as a native model session;
- [ ] takeover lease conformance covers every mutating effector;
- [ ] credential references are audience-bound through the execution path;
- [ ] durable claimed work exists for lifecycle/routine/handoff consumers;
- [ ] activity and governance evidence are separate surfaces/contracts;
- [ ] bounded-member assurance visibly falls when an open effector such as shell is added;
- [ ] at least one external-executor spike proves a relying party can require a Hestia decision independently of the agent-side hook, **or** the spike is explicitly rejected with measured reasons and a replacement A2 relying-party test is named;
- [ ] the negative-requirement suite in §8 is represented by executable tests wherever the corresponding feature exists.

Until then, OpenBot remains a reference and test source, not a claimed Hestia capability.