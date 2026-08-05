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

### 5.4 A tension to settle before building it

GPT's PRD §4.5 states: *"T3/V3 … do not directly grant authority unless the operator has explicitly authored a law that does so. For the initial implementation, no automatic authority-granting rule is permitted."*

dp's ladder selects a resolver by `[kind, T3/V3 threshold]`. That **is** authority flowing from a trust score.

These reconcile only under one reading: the threshold is a **parameter of operator-authored law** — the operator writes *"escalations of class X may be resolved by a governance-kind role whose holder is above T3 = t"* — rather than a rule the system derives on its own. Under that reading the ladder is exactly PRD §4.5's sanctioned case, not an exception to it.

But it means the PRD's *"for the initial implementation, no automatic authority-granting rule is permitted"* has to be understood as a **phase constraint, not a permanent principle** — otherwise the ladder is forbidden by the same document that motivates it. Worth settling explicitly now, in the architecture review, rather than discovering the contradiction mid-build.

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
