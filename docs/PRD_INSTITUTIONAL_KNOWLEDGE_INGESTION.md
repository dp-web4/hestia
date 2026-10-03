# PRD — Hestia Institutional Knowledge → Local Governance

**Status:** draft for prototype  
**Date:** 2026-10-03  
**Scope:** Hestia side of Governance Twin ingestion  
**Companions:** Web4 `hub/docs/PRD_INSTITUTIONAL_KNOWLEDGE_INGESTION.md`, `docs/PRD_LAWBOOK_IR.md`

## 1. Purpose

Hestia should be able to participate in a customer onboarding flow where institutional knowledge is discovered first and enforcement is activated only after explicit ratification.

The Hub companion owns the organization-level model:
- roles;
- authority;
- procedures;
- institutional knowledge;
- candidate law;
- ratification.

Hestia owns the local execution translation:
- tool/action categories;
- local credentials;
- machine-local effectors;
- runtime policy projection;
- shadow decisions;
- enforcement;
- action evidence.

The customer value proposition is:

> **Model the organization as it really operates, show where governance is missing or contradictory, then turn approved controls into live action boundaries without rewriting them by hand for every agent seat.**

## 2. Hard boundary

Institutional knowledge MUST NOT directly mutate local policy.

Hestia accepts only:
1. ratified society law;
2. explicitly authorized local policy;
3. signed/versioned projections of those objects.

An interview, document extraction, or process-mining observation may create a finding or proposed policy change, never a live deny.

## 3. Hestia's role in the pipeline

```text
Institutional Knowledge Graph
    -> Candidate Lawbook
    -> Ratification
    -> signed/versioned governance projection
        -> Hestia shadow evaluator
        -> operator review
        -> Hestia active policy
        -> action receipts / witness evidence
        -> feedback to Governance Twin
```

## 4. Required projection classes

The Governance Twin may produce Hestia-relevant controls such as:

- allowed/denied tool classes;
- target/path/data scope;
- credential access;
- network/action scope;
- role-specific narrowing;
- time windows;
- rate constraints;
- approval requirements;
- irreversible-action escalation;
- required witnesses;
- required appeal path;
- instruction/delegation provenance requirements.

These compile into existing Hestia engines where possible:
- `PolicyConfig`;
- role overlays;
- `LawGate`;
- one-gate / policy entity;
- adjudication/escalation machinery.

Do not create a parallel enforcement engine.

## 5. Shadow mode as customer bridge

A customer pilot needs to prove value before changing behavior.

Hestia should support a first-class **Governance Twin shadow** mode:

- evaluate candidate governance on real/replayed actions;
- never block;
- record:
  - candidate decision;
  - winning rule;
  - contributing institutional sources;
  - current actual outcome;
  - disagreement between current practice and proposed governance;
- generate statistics over a pilot window.

Example:

```text
actual: tool executed
candidate governance: escalate to finance-controller
reason: customer policy P-17 + interview consensus + SoD control
shadow divergence: yes
```

This lets the customer review consequences before ratification/enforcement.


## 5A. Shadow mode is also a learning surface

Shadow mode MUST do more than compare candidate governance with active behavior.

For each observed act, Hestia should emit **learning evidence** scoped to the MRH/role context in which the act occurred.

Useful observations include:

- actor and active role;
- society / child-society context;
- delegated authority present at the time;
- action/resource/target;
- consulted or approving roles;
- actual sequence of handoffs;
- exception path used;
- evidence attached;
- candidate rule result;
- active policy result;
- eventual outcome.

This allows the Governance Twin to learn institutional structure from ordinary work instead of asking every participant to document it in advance.

## 5B. Minimum-question elicitation

Hestia SHOULD remain silent on routine, well-explained activity.

It may surface a clarification request when runtime evidence creates a meaningful ambiguity, for example:

- actor performs an action outside the role normally seen for it;
- candidate and active governance differ materially;
- escalation goes to a different role than the model predicts;
- repeated exception appears;
- parent and child MRH expectations differ;
- new tool/action pairing appears;
- high-consequence action has unclear authority.

The question should be local and concrete.

Example:

> "This production deploy is being approved by Security Lead rather than Release Manager. Is that an after-hours delegation, an exception for this service, or a different policy?"

The reply is stored as an **elicited claim with provenance**, not immediately as policy.

## 5C. MRH-scoped runtime learning

Hestia MUST preserve the narrowest known context of an observation.

An action seen on one machine, by one role, in one team MUST NOT become an organization-wide practice merely because it occurred repeatedly there.

Each exported learning event SHOULD carry:

- `origin_mrh`;
- `society_context`;
- `role_context`;
- `seat/device context`;
- `candidate_parent_mrh` when known;
- evidence reference;
- occurrence count / recurrence metadata;
- any known sibling-MRH agreement or conflict.

The Hub/Governance Twin decides whether multiple local observations compose into a broader candidate pattern.

## 5D. Fractal shadow evaluation

Where nested society law is present, shadow output SHOULD retain the decision at every relevant layer rather than only the final strictest verdict.

Example:

```text
team law: allow
department law: escalate to release-manager
organization law: require independent approval
local Hestia safety: warn
final active behavior: allowed today

shadow finding:
  inherited org requirement applies
  department resolver is missing
  team practice currently bypasses inherited requirement
```

This makes learning compatible with SAL's nested society/law inheritance instead of flattening all contexts into one rule set.

## 5E. Learning evidence never becomes enforcement by recurrence

Repeated behavior can increase confidence that a practice exists.

It MUST NOT increase the authority of that practice.

A pattern may progress:

```text
observed once
 -> repeated locally
 -> corroborated across roles
 -> corroborated across sibling MRHs
 -> candidate broader institutional knowledge
 -> candidate governance
 -> ratification
 -> active policy
```

The first five states are descriptive. Only ratification can cross into governing state.


## 6. Institutional findings Hestia can contribute

Hestia's runtime evidence can feed the Governance Twin with observations such as:

- which tools/actions actually occur;
- which roles perform them;
- which delegated authority was present;
- which denies/warns/escalations fire;
- which rules never fire;
- where actors repeatedly request exceptions;
- where escalation targets are unavailable;
- where appeal guidance is unreachable;
- which actions are performed by AI vs human vs automation;
- which credentials/resources are actually touched;
- which policy projections are stale;
- where a documented process step has no corresponding observed action.

These observations remain observations until reviewed/ratified.

## 7. Local computed witnesses

Add or reuse Lawbook witnesses for:

| Witness | Meaning |
|---|---|
| `ShadowPolicyDivergence` | Candidate governance disagrees with current runtime behavior. |
| `RepeatedException` | Same exception recurs across actions. |
| `UnratifiedAIHandover` | AI/automation acts in a role whose authority transition is not ratified. |
| `RuntimeControlUnwitnessed` | A declared control has no corresponding runtime evidence. |
| `ResolverUnavailable` | Escalation target is named but cannot currently receive it. |
| `AppealUnavailable` | Policy promises appeal but current seat has no reachable route. |
| `ProjectionStale` | Local active policy does not match ratified Lawbook version. |
| `ObservedCategoryUngoverned` | Consequential runtime category repeatedly falls through permissively. |
| `PracticeChanged` | Action distribution/process changed materially from ratified baseline. |

## 8. Customer-facing decision explanation

A shadow or active decision should be explainable as:

```text
What happened?
  agent attempted <act>

What institutional knowledge is relevant?
  policy P-17
  controller interview 2026-09-12
  approval-matrix row FIN-04
  observed workflow sample

What part is law?
  Lawbook rule FIN-SOD-03, ratified by <authority>, effective <date>

What did Hestia do?
  shadow/escalate/deny/allow

What can happen next?
  appeal/escalation route
```

The explanation must distinguish source material from ratified law.

## 9. Ratified activation workflow

For a new control:

```text
candidate projection
  -> shadow run
  -> impact report
  -> operator / society authority review
  -> ratification reference
  -> signed policy projection
  -> local hash/version check
  -> activation
  -> witnessed decision stream
```

Activation should fail closed on:
- missing ratification reference for governance that requires it;
- projection hash mismatch;
- expired/superseded policy;
- malformed authority metadata.

The exact enforcement behavior remains bounded by current A1 assurance.

## 10. Pilot experience

For the first customer pilot, Hestia should demonstrate one live action class.

Example:
- source documents say production deploy requires Release Manager approval;
- interviews reveal SREs often bypass it during urgent fixes;
- logs show 11 bypasses in 60 days;
- candidate Lawbook proposes escalation for production deploy without valid approval;
- Hestia shadows for one week;
- customer reviews impact;
- authority ratifies;
- Hestia begins blocking/escalating the action;
- every subsequent act carries a decision and evidence trail.

This is more persuasive than a static compliance dashboard because the same model moves from diagnosis to operation.

## 11. Non-goals

The prototype does NOT:
- infer law directly from behavior;
- auto-ratify popular practice;
- replace Hub/SAL authority;
- claim A2+ assurance;
- ingest arbitrary enterprise data into the Hestia daemon itself;
- turn Hestia into a BPM/process-mining platform.

Hestia consumes ratified governance and contributes runtime evidence back.

## 12. Implementation sprints

### Sprint 0 — projection contract
- define institutional-source references carried by candidate policy;
- define ratification reference;
- define Lawbook/version/hash binding;
- define shadow decision record.

### Sprint 1 — shadow evaluator
- load candidate projection separately from active policy;
- evaluate same normalized action;
- never block;
- emit structured divergence record.

### Sprint 2 — explanation surface
- expose:
  - candidate rule;
  - institutional source references;
  - ratified-law state;
  - actual active-policy result;
  - resolution path.

### Sprint 3 — runtime witness export
- aggregate shadow/active observations suitable for Governance Twin:
  - recurring exception;
  - resolver availability;
  - category coverage;
  - rule firing;
  - AI/human role usage.

### Sprint 4 — activation proof
- ratified candidate becomes active projection;
- hash/version/authority checks;
- before/after replay proves only intended actions change.

## 13. Acceptance criteria

Prototype passes when:

- Hestia can evaluate a candidate policy in shadow mode without changing active enforcement;
- every candidate decision points to its Lawbook object and institutional sources;
- source claims are visually/machine-distinct from ratified law;
- a customer can review divergence statistics before activation;
- a ratified projection can be promoted without hand-rewriting rules;
- runtime evidence feeds back into review without changing law automatically;
- Hub and Hestia agree on the shared society-law portion.
