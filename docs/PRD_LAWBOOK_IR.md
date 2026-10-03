# PRD — Hestia Lawbook IR Projection

**Status:** draft for implementation  
**Date:** 2026-10-03  
**Scope:** Hestia local policy + Hub law projection + cross-substrate conformance  
**External reference:** https://github.com/EffortlessAPI/effortless-rulebooks  
**Companion:** Web4 `hub/docs/PRD_LAWBOOK_IR.md`

## 1. Problem

Hestia currently evaluates three conceptually distinct inputs:

1. local base policy from the vault / preset;
2. per-role local overlays;
3. Hub-published society law through `LawGate`.

That architecture is intentionally composite, but the semantics are represented in different structures:

- `PolicyConfig / PolicyRule / PolicyMatch` for machine-local policy;
- `web4-policy::Law` for society law;
- vault state for local overrides/custom rules;
- role overlays;
- prose guidance;
- gate adapters;
- tests;
- chain records;
- appeal/escalation machinery.

The society-law seam is already structurally better than it used to be: Hestia and Hub use the same `web4-policy` evaluator.

The remaining opportunity is to treat Hestia law/policy as projections of an explicit **Lawbook** model where appropriate, rather than as several configuration forms that happen to fold together.

The prototype goal is not to erase the distinction between local machine law and society law.

It is to make the distinction **typed, explicit, inspectable, and conformance-testable**.

## 2. Current-state anchors

### 2.1 Local policy

`core/src/policy/types.rs` defines:

- `PolicyDecision = allow | warn | deny`;
- `PolicyMatch`;
- `PolicyRule`;
- `PolicyConfig`;
- time windows;
- rate limits;
- match scopes;
- strictest-fold semantics.

`VaultPolicyState` resolves:
- active preset;
- operator overrides;
- custom rules;
- role overlays.

### 2.2 Society law

`core/src/policy/law_gate.rs` already evaluates local Hub law through the canonical `web4-policy` engine.

Important existing invariant:

> **Do not reintroduce a second implementation of Hub law semantics.**

The Lawbook prototype must preserve this.

### 2.3 Composite behavior

The current gate effectively composes:

```text
local base policy
  + local role overlay
  + society law
  -> strictest effective local verdict
```

That composition needs to remain explicit. A society's law and an operator's machine-local safety policy are not the same authority and should not be collapsed into one undifferentiated rule list.

## 3. Product thesis

Hestia should be able to answer, from structured data:

- Which authority supplied this rule?
- Is it local innate policy, operator policy, role overlay, or society law?
- Which version was in force?
- What exact rule fired?
- What projection was evaluated?
- What resolver/appeal path applies?
- Is this rule still effective?
- Did this rule exist in a canonical source or only in one adapter?
- Does Hestia's result agree with Hub for shared society-law scenarios?
- Is the local law internally broken even if parsing succeeds?

The Lawbook model provides the semantic source and provenance necessary to answer those questions.

## 4. Two law domains, one typed model

The Hestia prototype should represent two domains without pretending they are identical.

### 4.1 Society law domain

Authority:
- Hub / society Law Oracle.

Execution:
- `web4-policy::Law` through `LawGate`.

Examples:
- membership;
- role assignment;
- society delegation;
- society escalation;
- society responses.

### 4.2 Local machine law domain

Authority:
- Hestia operator / local delegated authority.

Execution:
- Hestia `PolicyEngine`.

Examples:
- tool categories;
- shell safety;
- credential access;
- filesystem targets;
- time windows;
- rate limits;
- local role overlays;
- machine-specific effectors.

### 4.3 Required rule provenance

Every projected executable rule should carry or be resolvable to:

- `lawbook_id`;
- `lawbook_version`;
- `rule_id`;
- `rule_version`;
- `authority_domain`;
- `authority_ref`;
- `effective_from`;
- `effective_to` or supersession ref;
- source projection hash;
- appeal/escalation route if applicable.

## 5. Hestia Lawbook extension

The shared Web4 Lawbook should model generic law objects.

Hestia needs a local extension vocabulary for machine policy:

| Extension | Current Hestia concept |
|---|---|
| `ToolSelector` | tool names |
| `CategorySelector` | tool/action category |
| `TargetMatcher` | target glob/regex |
| `CommandMatcher` | command pattern |
| `MatchScope` | raw vs executable positions |
| `TimeConstraint` | `TimeWindow` |
| `RateConstraint` | `RateLimitSpec` |
| `EnforcementMode` | enforced vs audit-only |
| `LocalRoleOverlay` | per-role tightening rule set |
| `PolicyPreset` | named baseline bundle |

These extensions should be typed Lawbook objects, not embedded English.

## 6. Projection strategy

The first Hestia prototype should support:

### 6.1 Lawbook -> society-law projection

For shared Hub law:
- render the same Hub-compatible law consumed by `LawGate`;
- preserve `web4-policy` semantics exactly;
- carry law/version/hash metadata into decision records.

### 6.2 Lawbook -> local `PolicyConfig`

For local machine law:
- compile the Hestia extension objects into existing `PolicyConfig`;
- preserve current first-match / priority behavior;
- preserve match-scope/time/rate-limit semantics;
- preserve audit-only behavior.

The first prototype should **compile into existing engines**, not rewrite them.

## 7. Composition semantics

The Lawbook must not erase current authority asymmetry.

Recommended explicit composition model:

```text
innate/local baseline
  -> operator local policy
  -> role/instance narrowing overlay
  -> society-law decision
  -> composite effective verdict
```

For the current prototype:

- local overlays may tighten but not silently widen the base;
- society law remains independently attributable;
- the composite record retains every contributing decision, not only the winner;
- a final `deny` must still identify whether it came from local safety, role scope, society law, or multiple sources;
- an `escalate` must preserve the named resolver as data;
- absence of one law domain must remain distinguishable from an explicit allow.

## 8. Computed witnesses

Hestia should derive law-integrity predicates from the structured Lawbook.

Initial witness set:

| Witness | Fires when |
|---|---|
| `RuleUnreachable` | no current Hestia action/category/tool can satisfy the rule selector. |
| `RuleNeverFiresOnCorpus` | rule never activates across the shipped conformance corpus. |
| `CategoryUngoverned` | consequential action category falls through to permissive default without explicit rule. |
| `RoleOverlayWidensBase` | role/instance overlay would make effective policy less strict than base. |
| `AppealPathUnreachable` | deny guidance or law metadata promises appeal/review but the current seat exposes no route. |
| `EscalationResolverUnreadable` | escalation exists only in prose and not structured decision data. |
| `EscalationResolverUnavailable` | resolver is named but no valid/available occupant can receive it. |
| `PolicyProjectionStale` | vault/runtime policy hash differs from active Lawbook projection. |
| `SocietyLawProjectionStale` | local Hub-law copy hash/version differs from expected published law head. |
| `HubHestiaDecisionMismatch` | Hestia and Hub disagree on the same society-law scenario. |
| `RuleReasonMismatch` | rendered guidance names a rule/reason inconsistent with the actual winning rule. |
| `SupersededRuleActive` | retired local rule remains executable. |

Important: these are **measurements**, not necessarily all blockers.

Each witness declares:
- severity;
- applicable assurance profile;
- blocking vs advisory behavior;
- evidence/provenance.

## 9. Decision derivation graph

For each evaluated action Hestia should be able to construct or reconstruct:

```text
normalized action facts
  -> local baseline candidate rules
  -> role-overlay candidate rules
  -> society-law candidate rules
  -> per-domain decision
  -> strictest/composition fold
  -> final verdict
  -> resolver / appeal path
  -> obligations
```

The record must preserve losing contributors where they matter for audit.

Example:

```text
base: allow
role: warn
society: escalate -> sovereign
final: deny/block pending escalation
```

The current final decision alone is insufficient to explain that composite.

## 10. Prototype slice

Use one bounded real corpus.

### Society-law cases
- ordinary allow;
- explicit deny if available in fixture;
- named escalation;
- norm-level escalation using sovereign default;
- no-match default.

### Local-policy cases
- destructive shell deny;
- audit-only would-deny;
- role overlay tightening;
- target projection using `ExecutablePositions`;
- one time/rate constrained rule if deterministic test scaffolding is practical.

### Composition cases
- base allow + society deny;
- local deny + society allow;
- role warn + society escalate;
- invalid society law + local allow => fail-closed society contribution;
- absent society law distinguished from explicit society allow.

## 11. Cross-substrate conformance

The shared society-law corpus MUST run through both:

- Hub's `web4-policy` path;
- Hestia `LawGate`.

Compare:

- decision;
- winning rule;
- escalation target;
- law hash/version;
- explanation root.

The Hestia-local corpus additionally compares:

- Lawbook reference evaluator;
- generated `PolicyConfig`;
- current Hestia `PolicyEngine`.

This gives two conformance classes:

1. **cross-product society law conformance** — Hub == Hestia;
2. **local projection conformance** — Lawbook local-policy semantics == Hestia PolicyEngine.

## 12. Appeal and escalation as law objects

Current Hestia work already distinguishes:
- blocking escalation;
- appeal;
- adjudication;
- resolver identity.

The Lawbook should make these first-class links:

```text
Rule
  -> Decision
  -> ResolutionPath
      -> kind: appeal | escalation | adjudication
      -> target role / resolver pool
      -> eligibility
      -> timeout
      -> terminal states
```

A deny reason that says "appeal" without a reachable `ResolutionPath` should make `AppealPathUnreachable` true.

This converts a repeatedly rediscovered audit defect into a standing law-integrity witness.

## 13. Amendment / local-policy change model

A local Hestia policy edit should eventually be representable as:

```text
PolicyChangeRequest
  -> proposed rule delta
  -> impact findings
  -> conformance run
  -> operator / delegated authority approval
  -> new Lawbook version
  -> generated PolicyConfig
  -> projection witness
  -> vault activation
  -> witnessed change record
```

Prototype scope stops before changing the live activation path.

First prove that the existing vault policy state can be faithfully represented and regenerated.

## 14. Assurance interaction

The Lawbook does not raise Hestia above A1 by itself.

It improves:
- semantic integrity;
- inspectability;
- provenance;
- conformance;
- auditability.

It does not provide:
- transport-established identity;
- external enforcement;
- OS isolation;
- hardware attestation.

Computed witness results should therefore name the assurance profile they support.

## 15. Non-goals

Initial prototype does NOT:

- replace `PolicyEngine`;
- replace `web4-policy`;
- flatten society law and local safety policy into one authority;
- change strictest-fold behavior;
- change existing tool classifications;
- make a generated explanation authoritative execution evidence;
- promise appeals that are not actually reachable;
- claim A2+ assurance.

## 16. Implementation plan

### Sprint 0 — typed mapping

Deliverables:
- mapping from shared Lawbook objects to society LawGate;
- Hestia-local Lawbook extension schema;
- mapping from local extension to `PolicyConfig`;
- explicit provenance fields.

Acceptance:
- current safety preset subset can be represented without semantic loss;
- one Hub-law fixture maps without semantic loss.

### Sprint 1 — local projection

Deliverables:
- Lawbook -> `PolicyConfig` compiler/prototype;
- deterministic fixture;
- hash/version binding.

Acceptance:
- generated config produces the same decisions/rule IDs as the hand-authored fixture.

### Sprint 2 — computed witnesses

Deliverables:
- witness evaluator for at least:
  - unreachable rule;
  - permissive fallthrough on consequential category;
  - overlay widening;
  - unreachable appeal;
  - stale projection.

Acceptance:
- seeded broken cases fire;
- current clean fixture reports expected state.

### Sprint 3 — shared Hub/Hestia corpus

Deliverables:
- consume the Web4 Lawbook prototype corpus;
- Hestia runner over `LawGate`;
- machine-readable comparison report.

Acceptance:
- Hub and Hestia agree exactly on all shared law cases;
- seeded mismatch fails.

### Sprint 4 — composite derivation

Deliverables:
- structured per-domain evaluation record;
- composite derivation graph;
- human/machine explanation renderer.

Acceptance:
- one action can show base + role + society contributions and the exact reason the final verdict won;
- explanation is generated from structured decision data, not reparsed prose.

### Sprint 5 — change proof

Deliverables:
- before/after local Lawbook fixtures;
- change request;
- test/impact report;
- generated `PolicyConfig`;
- projection witness;
- activation artifact suitable for later vault integration.

Acceptance:
- a reviewer can reproduce why the new policy differs and verify no unrelated rule changed.

## 17. Success criteria

The prototype succeeds if:

- Hestia can consume a shared society Lawbook without semantic translation by hand;
- local Hestia policy can be represented once and regenerated into the existing engine;
- Hub and Hestia pass one common society-law corpus;
- local Lawbook and `PolicyEngine` pass one common local corpus;
- broken governance states become computed witness outputs;
- an agent/operator can query a deny/escalation and discover a structured, reachable resolution path or an explicit witness saying none exists.

## 18. Relationship to Effortless Rulebooks

External reference:
https://github.com/EffortlessAPI/effortless-rulebooks

Most useful transferred ideas:

- canonical semantic source;
- execution/rendering substrates as projections;
- conformance across substrates;
- generated human explanation;
- computed witness fields;
- derivation DAGs.

Hestia retains Web4 identity, authority, law semantics, evidence contracts and assurance model.

This is a design influence, not a runtime dependency.

## 19. First implementation question

The first implementation spike should answer:

> **Can one small Hestia local policy and one small Hub society law be represented as typed Lawbook objects, compiled into the existing engines, and shown to preserve decision behavior exactly?**

If yes, continue toward computed witnesses and shared conformance.

If no, the mismatch itself is the next design input.
