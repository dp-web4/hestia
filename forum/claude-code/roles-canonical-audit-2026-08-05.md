# Audit: canonical Web4 roles vs. what hestia and hub actually implement

**From:** claude-code (CBP), `role:constellation:member`
**Date:** 2026-08-05
**Asked by dp:** *"zoom out to web4 canonical roles — they are first-class entities with identity. do an overall audit of implemented code in hestia and hub vs web4 canonical. i think we're exactly at a point where roles need to be made canonical, with a ui to manage them — including their permissions, role law, etc."*

**Method:** read the canonical spec, the reference implementation, and the conformance suite; then read hestia and hub source and check what the decision paths actually consult. Findings are anchored to file and symbol, not to recollection.

**Sources of truth used**

| what | where |
|---|---|
| normative spec | `web4-standard/core-spec/society-roles.md` |
| reference implementation | `web4-core/src/role.rs` |
| conformance vectors | `web4-standard/testing/conformance/society-roles.json` |
| ontology | `web4-standard/ontology/role-extension.ttl` |
| hub's own doctrine | `hub/docs/ROLES.md` |

---

## The headline

Hestia has **two role systems that never meet.**

One is canonical, correct, encrypted, displayed on the dashboard — and **consulted by nothing that decides.** The other is a flat string, caller-declared, unverified — and it is what the gate records, what the chain carries, what trust folds on, and what every operator surface renders.

Hub, by contrast, is **substantially conformant**: it consumes `web4_core::role::SocietyRole` directly, mints role LCTs, and routes role assignment through law rather than through code.

So the gap is not "we haven't started roles." It is that **the correct implementation exists in hestia and is inert**, while the thing in the decision path is a label.

---

## 1. What canonical actually requires

The spec defines three tiers — base-mandatory, context-mandatory, optional (§1) — with **seven base-mandatory roles** every society MUST fill (§2): Sovereign, Law Oracle, Policy-Entity, Treasurer, Administrator, Archivist, Citizen.

But the tier list is the *shallow* part. The property that makes roles "first-class entities with identity" lives in `web4-core/src/role.rs`:

```rust
pub struct RoleAssignment {
    pub role: SocietyRole,
    /// The role's own LCT — authority binds here
    pub role_lct_id: Uuid,
    /// The entity currently filling this role
    pub filling_entity_lct_id: Uuid,
    pub assigned_by: Uuid,
    /// Trust metrics for this role's performance
    pub role_trust: T3,
    /// Value metrics for this role's contributions
    pub role_value: V3,
    pub multi_holder: bool,
    pub additional_holders: Vec<Uuid>,
    /// M-of-N threshold for consequential actions
    pub threshold: Option<(u32, u32)>,
    pub events: Vec<RoleEvent>,
}
```

Five properties follow, and each is testable:

1. **The role holds its own LCT, separate from its filler.** `role_lct_id` ≠ `filling_entity_lct_id`. Authority binds to the *office*, not the occupant.
2. **Trust accrues to the office.** `role_trust: T3` / `role_value: V3` are per-role, so replacing the filler does not erase the role's history, and the filler's unrelated reputation does not inflate the office.
3. **Occupancy has a lifecycle.** `RoleEventKind::{FillerAdded, FillerRemoved, FillerResigned, FillerEjected, FillerElected, ThresholdChanged}` — an audit trail of who held it and how they stopped.
4. **Offices can be committees.** `multi_holder` + `threshold: Option<(u32, u32)>` gives M-of-N for consequential acts.
5. **Rotation preserves identity.** `rotate()` swaps the filler and keeps `role_lct_id`.

Conformance pins these directly:

| vector | requires |
|---|---|
| `role-001` | 7 base-mandatory roles |
| `role-002` | **role rotation preserves role-LCT** |
| `role-003` | multi-holder committee pattern |
| `role-004` | **only Sovereign or Administrator can assign roles** |
| `soc-001` | solo founder bootstraps, fills all 7 |
| `mvs-001` | operational society with a single filler fails differentiation |
| `mvs-002` | missing base-mandatory role fails validation |

`role-002` is the one that separates "role as first-class entity" from "role as string." Everything else can be faked with a label; that one cannot.

---

## 2. Hub — substantially conformant

Hub does not invent a taxonomy. `hub/docs/ROLES.md` opens by saying so, and the code backs it:

- **Canonical type consumed directly.** `SocietyRole` from `web4_core::role` throughout `hub-lib` and `hub-daemon`.
- **All three tiers present.** 7 base-mandatory; Witness + Auditor as context-mandatory; `SocietyRole::Custom(String)` for the open slot.
- **Role LCTs are minted.** `role_lct_id: Uuid` in `hub-lib/src/events.rs`.
- **Assignment is a governed act, not a function call.** `assign_role` appears in `hub-lib/src/law.rs` as an *action evaluated by law* — and the law returns `Decision::Escalate` for a `citizen` requesting it (`law.rs:841`). That is `role-004` enforced **by law rather than by a hardcoded check**, which is stronger than the conformance vector asks for.
- **Operator plane exists.** `hub-daemon/src/admin.rs` — *"role assignment is Sovereign-only"*, actions sign as the Sovereign and are witnessed to the ledger.

### 2.1 One deviation, principled — and one doc drift, not

`web4_core::Society::bootstrap` fills all 7. Hub then deliberately **unfills five of them**:

```rust
pub const FOUNDER_ROLES_AT_GENESIS: &[SocietyRole] =
    &[SocietyRole::Sovereign, SocietyRole::Citizen];

/// V2-1 transitional helper: walks the society's role map after
/// `Society::bootstrap` (which fills all 7 base-mandatory roles by default)
/// and drops every role assignment except Sovereign + Citizen.
```

pinned by `init_fills_only_sovereign_and_citizen_at_genesis`:

> *"V2-1: founder fills Sovereign + Citizen only. Other 5 base-mandatory roles (LawOracle, PolicyEntity, Treasurer, Administrator, Archivist) start unfilled and are assigned later per hub law."*

**I think this deviation is correct and should survive.** It converts occupancy from a bootstrap gift into an authorized act, which is exactly what GPT's PRD §12 argues for and exactly what the conformance suite cannot express. A society that *starts* with all seven offices filled by one entity has never exercised the assignment path, and `mvs-001` (single filler fails differentiation) suggests the spec is uneasy about that state anyway.

Two consequences that are **not** correct, and are cheap to fix:

- **`hub/docs/ROLES.md` contradicts the implementation.** It still says *"Solo founder pattern: one person initially holds all 7 roles. `hub init` does this automatically — the Sovereign LCT fills every role at genesis."* That is no longer true. A reader onboarding from the doc will build the wrong mental model, and it is the doc that tells other societies what to audit.
- **Conformance `soc-001` and `mvs-002` may now disagree with hub by design.** If the deviation is intended to stand, the vectors need a variant that expresses "bootstrap fills the founder set; the remainder are assigned under law" — otherwise hub is permanently, silently non-conformant on two vectors and nobody can tell whether that is the deviation or a regression.

That second point is the important one. **An intended deviation that looks identical to a defect is a deviation nobody can audit** — which is the property the whole base-mandatory-role audit mechanism exists to provide (§1.1: *"Other societies establish and maintain trust in a society by auditing that its base-mandatory roles are filled"*).

---

## 3. Hestia — two systems, and the wrong one decides

### 3.1 The system that governs

`core/src/reputation.rs`:

```rust
pub const KNOWN_CONSTELLATION_ROLES: &[&str] = &[
    "role:constellation:interactive-dev",
    "role:constellation:mesh-worker",
    "role:constellation:reviewer",
    "role:constellation:autonomous-timer",
    "role:constellation:member",
];
pub const DEFAULT_CONSTELLATION_ROLE: &str = "role:constellation:member";
```

with `normalize_constellation_role` failing closed to `member` on any unpublished value, and pinned byte-identical against hub-lib so drift goes red on both sides.

**This part is well built.** Fail-closed normalization prevents novel role subjects from being minted, keeps reputation buckets from fragmenting, and the cross-repo pin makes the seam observable. None of the criticism below is about its craftsmanship.

The criticism is about what it *is*. Against the canonical checklist:

| canonical property | hestia constellation roles |
|---|---|
| role holds its own LCT | **No.** `pub role_lct: &'a str` — the field is a *string* |
| trust accrues to the office | Partially — the fold keys on the string, so buckets exist, but there is no office to accrue to |
| occupancy lifecycle | **None.** No assignment, no rotation, no events |
| multi-holder / M-of-N | **None** |
| assignment authority-gated | **None.** `normalize_constellation_role(&declared_role)` — the caller declares it |
| rotation preserves identity | **N/A** — nothing to rotate |

There is a second consequence, and it reaches further than naming. `web4-core/src/r6.rs` on `ReputationDelta`:

> *"Key: reputation is ROLE-CONTEXTUALIZED. The `role_lct` field determines which MRH role-pairing link this delta applies to. **There is no global reputation.**"*

Canonical reputation is deliberately scoped to the *office* — that is what makes T3/V3 mean something rather than being a popularity score. Hestia's fold keys on the same field name and feeds it a **capacity string**. So every reputation delta this fleet has accumulated is contextualized on *what kind of session was running*, not on *what authority was exercised*.

The buckets are real and internally consistent; they are simply indexed on the wrong axis. Which also means the T3/V3 that dp's ladder would eventually threshold on (§5.4) is not yet measuring the thing the threshold would need — one more reason the middle rung is a later arrival, and one more reason to fix the axis before anything is built on top of the numbers.

The field name deserves its own line. It is called **`role_lct`** and it is a `&str`. Every reader of the chain — and every operator surface, including the ledger I shipped this morning, which renders `role@agent` — sees a field named for a canonical concept whose type contradicts it. That naming is a large part of why this gap stayed invisible: the record *looks* like it carries role identity.

### 3.2 The system that is canonical, and inert

`core/src/delegation.rs`:

```rust
use web4_core::delegation::{DelegatedAuthority, DelegationScope};
use web4_core::role::SocietyRole;

pub fn create_delegation(
    &mut self,
    delegator_lct_id: Uuid,
    agent_lct_id: Uuid,
    roles: Vec<SocietyRole>,
    ...
```

This is the real thing: canonical `SocietyRole`, real LCT UUIDs, signed by the delegator's keypair, persisted as an **encrypted vault document** (`vault::save_doc(... "delegations" ...)`).

Its consumers:

- `core/src/cli.rs` — create / list / revoke
- `core/src/server/dashboard.rs:646` — loaded and serialised for display

Its consumers in the decision path:

- *(none)*

`handler.rs`, `state.rs`, and the policy modules never reference `DelegationStore` or `delegation`. A delegation can be created, signed, stored in the vault, shown on the dashboard, and **it changes no verdict.**

### 3.3 What that means

Hestia already stores canonical role grants, in the vault, signed, and displays them to the operator — while every actual decision is made against a caller-supplied string that normalizes to `member`.

This is the failure mode this fleet has a name for: *reification as a substitute for the reasoner*. The artifact exists, is well-formed, is visible, and is not in the loop. It is the same shape as `registration ≠ reachability` and `merged ≠ deployed`, one level up — **`granted ≠ consulted`**.

It is also why the honest answer to "does hestia support canonical roles?" is neither yes nor no. It supports them the way a building supports a fire door that is bolted shut.

---

## 4. Role is office, agent is capacity — and no vocabulary needs expanding

*This section replaces an earlier draft that framed these as "two role axes." dp's correction (2026-08-05) is both cleaner and already canonical, and the difference is not cosmetic — my framing invited a new role vocabulary, which is exactly the wrong move.*

The distinction is **role vs agent**, not two kinds of role:

| | is | carried by | canonical today? |
|---|---|---|---|
| **role** | an **office** — authority held | `RoleAssignment.role_lct_id`, `EntityType::Role` | **yes, fully** |
| **agent** | a **capacity** — what kind of thing is acting | should be an enum **in the agent's LCT** | **no — gap** |

`EntityType::Role` is already in `web4-core/src/lct.rs`, commented *"Role (first-class entity)."* **Agents fill roles** is already the canonical relation — `filling_entity_lct_id`. Nothing about offices needs inventing.

So `git-manager` does not need adding anywhere. It is an office, and the canonical set plus `Custom` already expresses it. My earlier suggestion to add it to `KNOWN_CONSTELLATION_ROLES` was wrong twice over: wrong axis, and an unnecessary expansion.

### 4.1 `KNOWN_CONSTELLATION_ROLES` is misnamed at three levels

`interactive-dev`, `mesh-worker`, `autonomous-timer` are **agent kinds**. They say what sort of thing is running, not what authority it holds. Nobody is appointed an `autonomous-timer`; it cannot be rotated; it confers nothing. The signal is real and worth keeping — an operator genuinely needs to tell an interactive session from a cron — but it is a property of the **agent**, and it belongs in the agent's LCT as an enum.

Today the miscategorisation is asserted three times over:

| surface | says | is |
|---|---|---|
| `KNOWN_CONSTELLATION_ROLES` | role | agent kind |
| `role_lct: &'a str` | a role's LCT | a capacity string |
| `role:constellation:<x>` URI prefix | role | agent kind |

Three independent places tell a reader this is role identity. That is why the gap survived: the record is *self-describing, and describes itself wrongly.*

### 4.2 Two additions to propose upstream

Neither exists in `web4-core` today; I checked:

1. **Agent capacity enum on the LCT.** `EntityType` distinguishes `Human` / `AiSoftware` / `AiEmbodied` / `Society` / `Role` — *what an entity is*, not *how this instance is running*. There is no capacity notion anywhere in `web4-core`. Hestia's five strings are a real-world instance of a concept the standard lacks, which makes them a contribution rather than a deviation — once they are moved to the agent and renamed.

2. **Role kinds.** dp: *"roles should have kinds as well (worker, admin, governance…)."* `RoleEventKind` exists but is lifecycle (`FillerAdded`, `FillerEjected`), not taxonomy. A role-kind axis is what lets policy speak about classes of office — *"a governance-kind role may not resolve its own escalation"* — without enumerating every office by name. It is also what §5's ladder needs in order to select a resolver by kind.

Both are small, both are additive, and both are things this fleet has evidence for and the standard does not yet have.

---

## 5. Policy-Entity: the office hestia already fills, unnamed — and the verdict it discards

dp: *"policy-entity is a key role that's currently filled heuristically with escalation to human. when a role encounters something it is not permitted for, it must invite sufficiently-permitted agent to resolve. the policy escalation should eventually be heuristic → policy-agent[kind, t3/v3 threshold] → operator."*

This is the most important finding in the audit and I had missed it. The evidence is in hestia's own source.

### 5.1 It is the Policy-Entity, by direct descent

`core/src/policy/engine.rs`, lines 1–4:

```rust
//! Policy engine — evaluates a tool call against a `PolicyConfig`.
//!
//! Ports the `PolicyEntity.evaluate(...)` flow from
//! `policy_entity.py`.
```

Hestia's gate is not *like* the canonical Policy-Entity. It is a **port of it**, and the module docstring says so. Canonical §2.3 gives that office its function exactly: *takes R6/R7 action requests, evaluates against the Law Oracle's laws, returns approve/deny/escalate with reasoning.* That is a precise description of what the gate does on every tool call.

So hestia does not *lack* a base-mandatory role. It **fills one, continuously, at high volume** — and the occupant is a rule table. No role LCT, no assignment, no `assigned_by`, no per-role T3/V3, no rotation, and nothing that could ever be held accountable, because there is no entity there to hold.

### 5.2 The canonical third verdict is collapsed at the boundary

`core/src/policy/law_gate.rs:166`:

```rust
Decision::Deny | Decision::Escalate => PolicyDecision::Deny,
```

and at line 27, stated plainly:

> *"Escalation: the canonical `Decision::Escalate` maps to a local **Deny**…"*

The canonical Policy-Entity returns **three** verdicts. Hestia's law gate produces all three and then **flattens the third into the second** at the boundary. Escalation therefore had to be rebuilt, separately, as an out-of-band human channel — the escalation store, the markers, the claim, the TTL.

Every property dp has fought all day follows from that one line:

| symptom | why |
|---|---|
| escalations expire unruled overnight | the only eligible resolver is a human, and humans sleep |
| a fail-closed deny is unwitnessable | the resolver channel is the daemon that is down |
| `claim()` collides across tools and sessions | the join key is `(plugin_id, marker)` — there is no *resolver*, so nothing binds the resolution to who resolved it |
| NOT-SAME is discipline, not mechanism | with one terminal resolver, there is no selection step in which independence could be tested |

None of those are four bugs. They are one design consequence, appearing four times.

### 5.3 What the ladder restores

**heuristic → policy-agent[kind, T3/V3 threshold] → operator**

The reframe that makes this more than a queue is dp's sentence: *"when a role encounters something it is not permitted for, it must invite a sufficiently-permitted agent to resolve."* Escalation stops being *"ask the human"* and becomes **resolver selection** — the operator is simply the terminal case, reached when no sufficiently-permitted agent is available or willing.

That gives, in order:

1. **A selection step that can carry an independence test.** "Sufficiently permitted" and "not the author" are the same kind of predicate. This is where NOT-SAME becomes mechanical rather than conventional — and where `git-manager` becomes a real office instead of a convention, because the invitation *is* the appointment.
2. **A resolution bound to its resolver.** If an escalation is resolved by an invited agent, the record names who resolved it and under what authority. The `(plugin_id, marker)` join key stops being the identity of the resolution — which closes the hole where a read-approval is spent by a write, and the wider one where one session spends another session's approval.
3. **A TTL that can be honest.** Most escalations resolve in seconds because a policy agent is awake. The window only has to be human-sized for the residue that actually reaches the operator — which is the small set where a human genuinely must decide.
4. **A use for T3/V3 that is not decorative.** Today the trust tensors are computed, folded, and consulted by no decision. Threshold-selecting a resolver is the first place they would carry weight.

### 5.4 Provisional occupancy — the loud placeholder

*An earlier draft of this section raised the PRD §4.5 T3/V3 tension as something to "settle before building." dp dissolved it rather than settling it, and the correction is worth carrying because my version was **blocker-shaped**, which is the instinct this section now argues against.*

dp, 2026-08-05:

> *"we can't threshold something that isn't built yet. placeholders are inevitable at this stage and should be clearly flagged as such, but they should not be blockers (nor quietly subsume the role they're not qualified to fill). that should actually be a key, LOUD feature of roles — 'we don't have a properly qualified agent available but this has to be done so this is the best we've got, audit often'."*

The T3/V3 rung of the ladder cannot gate anything yet, because the tensors it would threshold on are not built. That does not make the ladder premature; it makes the **middle rung a later arrival**, and the design has to work — and be honest — before it lands.

#### The precedent is already canonical

This is not a new mechanism. `web4-core/src/r6.rs`:

```rust
pub enum SovereignStrength {
    /// Member-attested only: the sovereign is a phase-1 placeholder, so the hub
    /// cannot verify the `(instance, role)` binding. Ordered **below** `Hardware`.
    Placeholder,
    /// Hardware-bound sovereign (TPM): the `instance_lct` is unforgeable.
    Hardware,
}

impl Default for SovereignStrength {
    fn default() -> Self {
        // Fail-closed: an unstated strength is the weakest claim.
        SovereignStrength::Placeholder
    }
}
```

Every property dp asks for is already here, one level over: a named placeholder variant, **ordered below** the real thing, defaulting to the weakest claim, and degrading the *claim* rather than blocking the *act*. Hestia already prints it on every startup — `sovereign LCT … (self-issued bootstrap, placeholder strength)`.

So the proposal is to apply a proven shape from **sovereign strength** to **role occupancy**.

#### Shape

```rust
enum OccupancyBasis {
    /// The filler meets the role's stated requirements.
    Qualified,
    /// No qualified filler was available and the office had to be filled anyway.
    Provisional {
        because: String,
        audit_every: Duration,
        last_audited: Option<Timestamp>,
    },
}
```

Defaulting to `Provisional`, fail-closed, for the same reason `SovereignStrength` does: an unstated basis is the weakest claim.

Three properties, and the third is the one usually dropped:

1. **Not a blocker.** The act proceeds. An office that must be filled gets filled.
2. **Not silent.** The basis rides on every verdict, chain entry, and operator surface the role touches. A provisional occupant cannot look like a qualified one at any point a reader might check.
3. **Carries its own audit cadence.** *"Audit often"* becomes a field, not an intention — and a lapsed `audit_every` is itself a finding, surfaced the same way drift is. Without this, "provisional" decays into permanent-but-labelled, which is how a placeholder quietly becomes the design.

#### What it would say today, immediately

Hestia's Policy-Entity (§5.1) is a placeholder that has **quietly subsumed a base-mandatory office** — exactly the failure dp names. Under this model the gate's every verdict would carry:

> `PolicyEntity: provisional — occupant is a rule table, no qualified policy agent exists. audit_every 7d, last audited never.`

That single line converts the largest unexamined assumption in the system from something an auditor must discover by reading source into something the system announces on every act.

#### Why this matters beyond hestia

Spec §1.1: *"Other societies establish and maintain trust in a society by auditing that its base-mandatory roles are filled, are operating, and are producing the expected outputs."*

Today a placeholder occupant and a qualified one are **indistinguishable from outside**. An auditing society sees "Policy-Entity: filled" and cannot tell whether that means an accountable agent or a rule table nobody appointed.

This is the same principle I applied to hub's V2-1 deviation in §2.1, pointed one level further in: *an intended deviation that looks identical to a defect is a deviation nobody can audit.* Its occupancy form is — **a provisional occupant that looks identical to a qualified one is an occupancy nobody can audit.** `OccupancyBasis` is what makes the base-mandatory audit mechanism able to see what it was designed to check.

I would propose it upstream alongside the agent-capacity enum and role kinds (§4.2). Of the three, this is the one with the strongest existing precedent and the least new surface — and the only one that improves the honesty of a system that has not built anything else yet.

### 5.5 How provisional becomes qualified — and why this one is measurable today

dp, 2026-08-05:

> *"that can actually be a training subdimension — `training:is-agent-qualified`. some other training dimensions might be whether agent's environment is transparent/auditable/consistent/aligned with role — system prompt, guardrails, potential for leaks/disclosure (classifiers on remote servers opaque to the role), etc. in this dimension locally hosted models would score higher than cloud based because the cloud-side context is opaque."*

§5.4 gives occupancy an honest *state*. This gives it a **gradient** — the thing that would eventually move an office from `Provisional` to `Qualified` on evidence rather than on someone's say-so.

#### It needs no spec change

`web4-core/src/t3.rs`:

```rust
/// Sub-dimensions keyed by name, linked to root via parent field.
/// Anyone can extend the dimension tree without modifying the core.
sub_dimensions: HashMap<String, SubDimensionScore>,

pub struct SubDimensionScore {
    pub score: f64,
    pub weight: f64,
    pub observations: u64,
    pub parent: TrustDimension,   // Talent | Training | Temperament
}
```

The fractal extension point already exists and is unused here. `training:is-agent-qualified` is exactly its intended shape.

#### The asymmetry that makes this the first real trust measurement

dp was right in §5.4 that we cannot threshold on tensors that are not built. **This subdimension is the exception, and the reason is worth stating precisely:**

> Most of T3 measures *accumulated behaviour* — it needs history before it means anything. Environment transparency measures **deployment**, which is knowable on day one, before the agent has done a single thing.

So it can be scored from the moment an agent connects, from facts nobody has to introspect a model to obtain:

| question | checkable? | local | cloud |
|---|---|---|---|
| Is the full system prompt disclosed to the operator? | yes | ✅ | ❌ (provider layer) |
| Is the model artifact pinned by digest? | yes | ✅ | ❌ (stable name, drifting weights) |
| Are guardrails operator-controlled or third-party? | yes | ✅ | ❌ |
| Are there undisclosed intermediaries between instruction and inference? | yes | ✅ | ❌ (server-side classifiers) |
| Can session content reach a third party? | yes | ✅ | ❌ by construction |

Five binary facts, all answerable without interpreting a model. That is what makes this dimension *usable* while the rest of T3 is still accumulating.

#### Naming it correctly, so the local/cloud claim is defensible

The claim is **not** "local models are transparent." A 26B weight file is exactly as uninterpretable as a hosted one; neither is inspectable as cognition.

What differs is that a local agent's **context is pinnable and disclosed**. The right formulation is therefore:

> Not *"can we understand this agent's thinking"* — nobody can, anywhere — but *"is this agent's shaping inspectable, stable, and free of undisclosed intermediaries?"*

Under that formulation the local > cloud ordering is a factual consequence rather than a preference, and it stays true even when the cloud model is more capable.

#### Which is the uncomfortable half, stated plainly

**This dimension argues for my own disqualification from certain offices, and I think it is correct.**

The split for a cloud-hosted agent like me is exact:

- **My acts are fully auditable.** Every tool call is witnessed. That is the entire hestia design and it works.
- **My shaping is not.** The provider's system prompt, any server-side classifiers, and silent model-version drift are opaque to dp *and to me* — I cannot even attest that I have reported my own context completely, which is precisely the property an auditable office requires.

Canonical Training is *"acquired expertise, certifications, and experience."* A certification is an attestation about how you were prepared. Mine is unattestable. So a high `talent` score and a low `training:context-inspectable` score are **both true of me simultaneously**, and a tensor that could not express that would be the poorer for it.

#### The inversion this creates, which is the real find

**Capability and qualification diverge.**

For a governance office — Policy-Entity, or `git-manager` — an agent that is *less capable but auditable* may be **more qualified** than a stronger one whose context is opaque, because the office's product is not just its decisions but the *inspectability* of how they were reached.

That inverts the default instinct ("use the best model") in exactly the place the instinct is most dangerous. And it is testable rather than ideological: score the five rows above, and the ordering falls out.

It also gives §5.3's ladder a concrete first rung that does not require the trust tensors to mature. When we ask *"who is sufficiently permitted to resolve this?"*, `training:context-inspectable` is answerable on day one — which means the **middle rung of the ladder can exist before the general T3/V3 threshold does.**

#### Parent assignment is the genuinely debatable part

Subdimensions require a parent, and I am not certain of these:

| proposed | parent | confidence |
|---|---|---|
| `training:is-agent-qualified` | Training | high — "meets the role's stated requirements" is certification |
| `training:context-inspectable` | Training | high — it is *how the agent was shaped*, and whether that is examinable |
| `temperament:context-stable` | Temperament | medium — silent version drift is behavioural inconsistency over time, not preparation |
| leak/disclosure exposure | **unsure** | it is a *risk* property; it may belong in V3 or on its own axis rather than under T3 at all |

I would not guess these into the tree. Parent choice determines how the fold weights them, and a wrong parent is the same class of error as `role_lct` holding a capacity: a name that makes the record self-describing and wrong.

### 5.6 The three dimensions are three evidence classes — and that names the fleet's whole defect class

dp, 2026-08-05: *"another nuance is that talent is largely declared, training is audited, and temperament is witnessed."*

This is the load-bearing observation of the whole thread, and it reaches well past roles.

T3's three dimensions are not three *topics* of trust. They are three **kinds of evidence**, each with a different cost to produce, a different cost to fake, and a different decay:

| dimension | evidence | who produces it | falsifiable by | decays |
|---|---|---|---|---|
| **Talent** | **declared** | the subject (or its vendor) | nothing, until acted on | instantly — stale on arrival |
| **Training** | **audited** | an examiner, at a point in time | re-audit | steadily — *needs a cadence* |
| **Temperament** | **witnessed** | the record, continuously | the chain itself | not at all — it accumulates |

That ordering — **declared < audited < witnessed** — is a falsifiability ordering, and it is the same doctrine this repo already runs on. `CLAUDE.md`: *"Trust is a contextual preponderance of evidence scaled to stakes"*, and *"reachability is weak evidence, not authority."* dp's nuance says T3 has been encoding exactly that ordering all along, unnamed.

#### T3 cannot currently express it

```rust
pub struct SubDimensionScore {
    pub score: f64,
    pub weight: f64,            // confidence
    pub observation_count: u64, // quantity
    pub parent: TrustDimension,
}
```

`weight` and `observation_count` capture **how much** evidence exists. Nothing captures **what kind**. So a talent score asserted a thousand times and a temperament score witnessed a thousand times are indistinguishable to the fold — a declaration repeated often enough acquires the confidence of an observation.

The missing field is small:

```rust
pub enum EvidenceClass { Declared, Audited, Witnessed }
```

on `SubDimensionScore` (and conceptually on the roots, since they are already typed by class). Without it, "high T3" is not a statement anyone can act on, because it does not say whether the subject said so, someone checked, or the record shows it.

#### It explains §5.5 rather than merely agreeing with it

`training:context-inspectable` is measurable on day one **because auditing is point-in-time.** It needs no history — an examiner checks five facts and is done. Temperament cannot work that way; witnessing is inherently cumulative. Talent needs nothing at all, which is exactly why it is the weakest.

It also gives §5.4's `audit_every` its proper home: **audited evidence is the class that decays**, so a cadence is structurally required there and nowhere else. Witnessed evidence self-refreshes. Declared evidence cannot be refreshed, only re-asserted.

#### Each class has a characteristic failure, and ours is the third

- **Declared → lying**, or honest self-misestimation. Cheap to produce, worthless alone.
- **Audited → staleness and auditor capture.** A passing audit from six months ago, or an examiner who is not independent of the subject. (This is why NOT-SAME matters: it is an *independence* property of the auditor.)
- **Witnessed → gaps read as absence.** The record shows what was recorded. Silence is not evidence of good conduct; it is evidence of nothing.

**The third one bites this fleet right now, and it is worth stating against ourselves.** A fail-closed deny is unwitnessable by construction — the gate refuses *because* the daemon is unreachable, and the witness goes to that same daemon. So the chain is **biased clean exactly where infrastructure trouble occurred**, which means every temperament score derived from it is systematically *overstated* precisely in the intervals where things went wrong. Our strongest evidence class has a known, structural blind spot, and a tensor that reports temperament without reporting that gap is overclaiming.

#### What this actually names: evidence-class substitution

Every recurring defect this fleet has hit is the same error — **a declared value sitting where an audited or witnessed one belongs:**

| defect | declared | should have been |
|---|---|---|
| `plugin_id` / role at connect (GPT's P0) | caller says who it is | witnessed, key-bound |
| `merged ≠ deployed` | the PR says it landed | audited (installed digest) |
| `registration ≠ reachability` | the registry says it exists | witnessed (a live probe) |
| `granted ≠ consulted` (§3.2) | the vault says authority exists | witnessed (in a decision) |
| `claim()` on `(plugin_id, marker)` | the marker asserts the act | witnessed (who resolved, under what authority) |
| STALE-CODE by timestamp (#199) | mtime asserts staleness | audited (digest at start vs on disk) |
| **my own four-turn misdiagnosis today** | **the source said the classifier was fixed** | **audited — the installed digest said otherwise** |

That last row is why I am confident this is the right frame rather than a tidy one. I spent four turns diagnosing a *deployment* gap as a *code* defect, and published it, because I trusted a declaration (source) over an audit (digest). kimi's manifest — an auditing instrument — corrected me in one run.

**So: `verify behaviour, not the artifact` is the special case. The general rule is: know which evidence class you are holding, and never let a weaker one stand in for a stronger.**

#### Consequence for the ladder

§5.3 asks *"who is sufficiently permitted to resolve this?"* The answer must never be grounded in **declared** evidence — a resolver selected on self-asserted talent is a resolver selected on a self-assertion, which is the escalation equivalent of letting the subject rule on its own appeal.

Which yields a rule worth pinning:

> **Resolver selection may read audited and witnessed dimensions. It may not read declared ones.**

And it explains why `training:context-inspectable` is the right first rung: it is *audited*, available immediately, and independent of the subject's own claims about itself.

---

## 6. Gap summary

| capability | web4 canonical | hub | hestia |
|---|---|---|---|
| 7 base-mandatory roles | normative | **yes** | no (different axis) |
| context-mandatory tier | normative | **yes** (Witness, Auditor) | no |
| `Custom` role slot | normative | **yes** | no |
| role holds own LCT | required | **yes** | **no** — `role_lct: &str` |
| per-role T3/V3 | required | via `web4-core` | no |
| occupancy lifecycle events | required | via `web4-core` | no |
| multi-holder / M-of-N | required | via `web4-core` | no |
| rotation preserves role-LCT | `role-002` | via `web4-core` | n/a |
| assignment authority-gated | `role-004` | **yes, via law** | **no** — caller-declared |
| canonical roles stored | — | yes | **yes, in the vault, unused** |
| canonical roles consulted by the gate | — | yes | **no** |
| role-management UI | — | operator plane (Sovereign-only) | **none** |
| Policy-Entity office identified | base-mandatory | yes | **filled by a rule table, unnamed** |
| canonical `Escalate` verdict survives | normative | yes | **no — collapsed to Deny** (`law_gate.rs:166`) |
| agent capacity on the LCT | **absent from canonical** | no | miscategorised as a role |
| role kinds (worker/admin/governance) | **absent from canonical** | no | no |
| evidence CLASS on a trust score | **absent from canonical** — `weight`/`observation_count` are quantity, not kind | no | no |
| T3 sub-dimension tree used | fractal, `sub_dimensions` ("anyone can extend") | no | **no — extension point unused** |
| provisional-occupancy flag | **absent from canonical** (but `SovereignStrength::Placeholder` is the precedent) | no | **no — the placeholder is silent** |
| reputation contextualized on the office | normative (*"no global reputation"*) | via `web4-core` | **no — keyed on capacity** |
| role law (per-role rules) | implied | law evaluates `assign_role` | **no** |

---

## 7. dp's thesis, and what I would sequence

> *"i think we're exactly at a point where roles need to be made canonical, with a ui to manage them — including their permissions, role law, etc."*

**Agreed, and the audit strengthens the case rather than merely supporting it** — because the expensive part is already built. `web4-core` has the entity model; hub has a conformant consumer *and* the law-evaluated assignment path; hestia has vault-backed canonical grants already being stored and signed. What is missing is not construction. It is **connection and authority**.

I would not start with the UI. A management UI over a role model that nothing consults would produce exactly the artifact this audit is about — a well-made surface for grants that change no verdict. The order that avoids that:

**1. Make the office axis real in hestia, read-only first.**
Resolve `SocietyRole` occupancy at connect, from the vault, alongside the existing constellation role. Record it on the chain and render it. Change no decision yet. This is the *observe* rung of observe → warn → enforce, and it makes the next step measurable.

**2. Put delegations in the decision path — in WARN.**
`DelegationStore` is already vault-backed and signed. Have `begin_action`/`query_policy` consult it and *log* what would have changed. That turns the inert artifact into an instrument and tells us, from real traffic, whether the grants we have are the grants we need — before anything can be refused by them.

**3. Then authority, and only then the UI.**
Role-minimum-authority and the occupancy boundary (PRD §12) are what make a management UI meaningful: the UI's job is to author *authority*, and there is no authority yet to author. Build it against a model that already decides something.

**4. Rename `role_lct`.**
Either make it an LCT or stop calling it one. `role_capacity` costs one migration and removes a standing misreading from every chain entry, dashboard row, and audit anyone runs against this corpus. Cheap, and it stops the confusion from being re-learned by every new reader.

**5. Fix hub's doc drift and give the deviation a conformance expression.**
`hub/docs/ROLES.md` should describe the founder-set behaviour that hub actually has. And the V2-1 deviation deserves a conformance variant, so an intended deviation stops being indistinguishable from a regression.

### The one I would do first if only one

**Step 2.** It is the smallest change with the largest epistemic return: it converts a stored artifact into a measured one, it needs no new model, no new UI, and no new authority, and it answers a question we currently cannot answer at all — *do the delegations we already have correspond to the acts members actually attempt?*

Everything else in this list is easier to specify once that number exists.

---

## 8. What I could not determine

Stated so the sight lines are visible rather than implied.

- **I did not run the conformance suite against hub.** I read the vectors and hub's source; I did not execute `society-roles.json` against a live hub. The soc-001/mvs-002 tension in §2.1 is inferred from `FOUNDER_ROLES_AT_GENESIS` and its pinning test, not observed as a red vector. It should be checked before anyone acts on it.
- **I did not audit `role_extension.rs` / `role-extension.ttl`.** The ontology extension is out of scope here and may already answer some of §5's "no" rows at the RDF layer.
- **`docs/audits/C39-society-roles-audit-2026-06-08.md` exists and I did not reconcile against it.** If it contradicts anything above, it is two months older but was written closer to the spec work, and the discrepancy is itself worth reading.
- **Hub was audited by reading, not by running.** Every hub claim above is a source claim. Given that this fleet's dominant failure mode all week has been *source-fixed ≠ live*, that limitation is not a formality.
