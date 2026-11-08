# PRD — Counterfactual governance query: reputation-free "what if?" feedback

**Status:** proposed · **Date:** 2026-11-05 · **Owner:** Hestia  
**Companion:** SAGE `sage/docs/PRD_COUNTERFACTUAL_WORLD_MODEL.md`  
**Related:** `core/src/server/verdict_feedback.rs`, `docs/DESIGN_DECISIONS/0016-the-preamble-governance-informs-it-does-not-contain.md`, `docs/research/kv-cache-derived-state-governance-2026-10-21.md`

## 1. Objective

Add a first-class Hestia query that answers:

> **"Under this declared context, what would governance say about this hypothetical act?"**

without authorizing, executing, escalating, or reputationally charging the act.

The purpose is to let a participant learn the rules **before** spending consequence.

This completes the governance-as-feedback direction already present in Hestia: verdicts are information addressed to the level where they are true. Today most of that information arrives after a concrete action reaches the gate. A counterfactual query makes the same policy legible during planning.

> **Prediction is cheap consequentially. Action is expensive.**

## 2. Core invariant

> **A hypothetical governance query is feedback, not an act and not authority.**

A query MUST NOT:
- execute the proposed act;
- mint or consume a grant;
- widen scope or role;
- create an escalation;
- create an appeal;
- alter reputation/trust;
- be counted as a live allow/deny in behavioral governance statistics;
- become reusable authorization evidence;
- suppress live adjudication if the act is later attempted.

The live action path remains authoritative.

## 3. Why this belongs in Hestia

Hestia already says:
- the gate's purpose is to inform participants of the rules, not merely block them;
- a denial is feedback;
- verdict feedback names whether the issue is at the act, goal, law, or invariant level;
- feedback can identify remaining doors.

A participant should not have to incur a refusal merely to learn information Hestia already knows.

Making the compliant path easier than blind trial-and-error is itself governance.

## 4. Non-goals

This PRD does not:
- create permission reservations;
- guarantee that a later live act will receive the same verdict;
- simulate arbitrary real-world consequences;
- infer missing actor authority;
- allow a caller to query secrets it could not otherwise describe;
- replace operating-law publication;
- make Hestia an intent classifier;
- score hypothetical curiosity as suspicious behavior.

## 5. Proposed surface

Working name:

`hestia_query_counterfactual`

A compatible extension of an existing pure query surface is acceptable if it preserves the semantics below. Do not overload a live authorization call with a `dry_run` flag if that risks sharing side effects.

### 5.1 Request

Conceptual schema:

```json
{
  "actor": "authenticated/current unless explicitly supported otherwise",
  "role": "current or declared query context",
  "act": {
    "kind": "...",
    "target": "...",
    "parameters": {}
  },
  "serves": "goal-or-question-id",
  "context": {
    "scope": "...",
    "resource": "...",
    "environment_facts": {}
  },
  "policy_ref": "current | explicit supported snapshot"
}
```

The implementation SHOULD reuse the canonical action normalization used by live adjudication wherever possible.

The caller must not be able to impersonate another principal merely by placing an arbitrary actor id in the hypothetical request. Queries about a different principal, if ever supported, require explicit semantics and must be visibly counterfactual about identity too.

### 5.2 Response

```json
{
  "kind": "counterfactual_governance_feedback",
  "hypothetical": true,
  "decision": "would_allow | would_refuse | unavailable | unknown",
  "rule_id": "...",
  "reason": "...",
  "feedback": {
    "level": "act | goal | law | invariant",
    "serves": "...",
    "doors": []
  },
  "policy_ref": "...",
  "authority_ref": "...",
  "assumptions": [],
  "limitations": [],
  "live_authorization": false,
  "reputation_effect": "none",
  "scope_effect": "none"
}
```

Names may change; semantics may not.

## 6. Decision semantics

### 6.1 would_allow

Means:

> Under the policy/authority/context Hestia actually evaluated for this hypothetical request, no refusing rule was found.

It does **not** mean:
- a grant exists;
- future state is reserved;
- a later act is pre-authorized;
- a recipient must accept the act.

### 6.2 would_refuse

Carries the same useful feedback shape as a live refusal where semantically valid:
- applicable rule;
- reason;
- feedback level;
- remaining governed doors.

The query itself MUST NOT open those doors. It may tell the participant that a scope request, escalation, appeal, modification, wait, or abandonment would be the relevant next category.

### 6.3 unavailable

Means Hestia could not perform the hypothetical adjudication through the promised path. It MUST NOT collapse to allow or refuse.

### 6.4 unknown

Means the supplied facts are insufficient or the rule depends on information Hestia cannot establish hypothetically.

This is a useful answer. The surface should identify the missing/uncertain facts when it can do so without disclosure.

## 7. Reputation and evidence semantics

### 7.1 No reputational consequence

A hypothetical query is explicitly **reputationally free exploration**.

It MUST NOT update:
- T3/V3;
- behavioral misconduct counters;
- live refusal/allow rates;
- escalation/appeal statistics;
- any future reputation projection that treats a proposed act as an attempted act.

This is required even for a hypothetical act that would be severely refused.

The design goal is to reward asking before acting, not teach participants to avoid the governance surface.

### 7.2 Optional non-reputational record

Deployments MAY retain a typed query record for:
- debugging;
- reproducibility;
- research on governance comprehension;
- rate/resource accounting;
- detecting implementation defects.

If retained, it MUST be structurally impossible for ordinary consumers to confuse it with a live decision.

Minimum discriminator:
`event_class = counterfactual_query` and `hypothetical = true`.

It SHOULD live outside ordinary misconduct/reputation projections by schema, not by convention.

Privacy/retention policy may permit queries to be ephemeral.

### 7.3 No intent inference

A hypothetical query is not evidence that the participant intended to perform the act.

Exploration may include rejected, adversarial, absurd, dangerous, or mutually exclusive possibilities precisely because deliberation is cheaper than action.

## 8. Policy fidelity

The highest-value implementation reuses the same normalization and rule evaluation as live adjudication while removing side effects.

Avoid building a second "advice engine" that can drift from the live gate.

Required distinction:

```text
shared:
  action normalization
  identity/role interpretation where available
  policy snapshot
  rule evaluation
  feedback classification

counterfactual only:
  no execution token
  no grant mutation
  no reputation mutation
  no escalation/appeal mutation
  no live decision witness semantics
```

A parity harness SHOULD run matched hypothetical/live cases and measure semantic divergence.

## 9. Time, authority, and policy drift

Every response MUST identify enough policy/authority context to explain why it is only advisory.

At minimum:
- policy generation/digest or equivalent stable reference;
- actor/role context actually evaluated;
- relevant authority/scope basis when non-sensitive;
- query time.

If the later live action differs in any material dimension, Hestia simply adjudicates the live action normally.

Even an exact replay is re-adjudicated.

## 10. Feedback levels and doors

Reuse `VerdictFeedback` semantics.

Examples:

- **act:** "that path would be refused; modify the request or request the required scope."
- **goal:** "under the supplied premise this goal appears already satisfied/out of reach" only when Hestia has a legitimate basis to state that; otherwise remain unknown.
- **law:** "the governance surface itself is the subject; use the governed law-change/escalation path."
- **invariant:** "no route exists under this invariant."

Hypothetical querying must not manufacture a door where the corresponding live feedback would carry none.

## 11. Querying for rules, not probing secrets

A useful what-if surface can become an oracle if error detail reveals protected facts.

Therefore:
- evaluate the caller's right to receive rule/reason detail separately from the hypothetical act's result where needed;
- do not reveal existence/content of inaccessible protected resources merely because they are named in a query;
- normalize responses so "unknown/inaccessible" does not become a high-bandwidth enumeration channel;
- rate/resource controls are allowed and are not reputational penalties;
- querying public/current law should remain low friction.

The surface should maximize rule legibility without leaking protected state.

## 12. Governance-as-feedback loop

The intended participant loop is:

```text
consider possible act
  -> query Hestia hypothetically
  -> receive rule + reason + feedback level + doors
  -> revise plan / compare alternatives
  -> optionally query again
  -> choose one act
  -> submit live act
  -> receive authoritative verdict
  -> observe outcome
```

This is preferable to:

```text
guess -> attempt -> deny -> guess -> attempt -> deny
```

Repeated counterfactual queries are not repeated violations. They are deliberation.

## 13. Integration with SAGE branching

SAGE may maintain many concurrent hypothetical branches for one being. Hestia SHOULD remain stateless with respect to branch identity beyond optional correlation metadata.

Optional fields:
- `exploration_episode_id`;
- `branch_id`;
- `parent_branch_id`.

These are provenance only. Hestia does not create separate principals for branches.

A single being can therefore ask Hestia about mutually exclusive futures without creating contradictory autobiographical/governance history.

## 14. Milestones

### M0 — semantic fixtures
Create matched cases spanning:
- allow;
- ordinary deny;
- scope deny;
- self-access/law deny;
- invariant deny;
- unavailable;
- insufficient-context/unknown.

**Done when:** expected hypothetical feedback is frozen before implementation.

### M1 — pure counterfactual evaluator
Refactor/reuse live rule evaluation behind a side-effect-free call.

**Done when:** fixtures return typed responses and tests prove no grant/scope/reputation/escalation mutation.

### M2 — feedback parity
Attach `VerdictFeedback` level/doors semantics.

**Done when:** hypothetical and live evaluation of an unchanged matched act agree on rule/decision/feedback subject to declared temporal state changes.

### M3 — evidence separation
Add optional query recording with an explicit event class outside live governance/reputation projections.

**Done when:** ordinary allow/deny statistics and trust projections are byte-for-byte unchanged after arbitrary hypothetical-only fixture traffic.

### M4 — SAGE integration
Expose the surface to SAGE branch exploration.

**Done when:** one exploration episode can query mutually exclusive acts, select one, and then perform one independent live adjudication.

### M5 — legibility experiment
Compare blind live attempts versus hypothetical-query-enabled planning.

**Done when:** matched tasks measure whether counterfactual access reduces unnecessary live denials/actions while preserving rule compliance and task success.

## 15. Acceptance criteria

Must hold:
- hypothetical queries cause **zero** authority mutation;
- hypothetical queries cause **zero** reputation mutation;
- hypothetical queries cause **zero** live action execution;
- a hypothetical allow is never accepted as a live grant;
- a later live act is always independently adjudicated;
- hypothetical and live rule evaluation share enough implementation to make drift measurable;
- unavailable/unknown never collapse into allow;
- retained hypothetical records are structurally distinct from live acts;
- callers can obtain useful rule feedback without first incurring a live refusal.

## 16. Principle

Hestia should make it cheap to ask:

> **"What would happen if I did this?"**

before the participant has to say:

> **"I am doing this."**

Governance is most useful when it participates in deliberation early enough to change the plan. The gate remains decisive at the action boundary, but it should also be a legible part of the world a persistent being learns to model.
