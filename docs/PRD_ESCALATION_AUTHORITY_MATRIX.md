# PRD — Escalation authority and participation matrix

**Status:** proposed · dp-directed 2026-09-01 · intended companion to `PRD_GOVERNANCE.md`, `PRD_ADJUDICATOR_LADDER.md`, `PRD_ALLOWLISTS.md`, and `PRD_ROLE_SCOPE_BRIDGE.md`

## 0. Directive

The current escalation/corroboration system is a useful first implementation and an empirical instrument. It is not the final constitutional model.

The target model is a **matrix over authority, availability, escalation kind, time window, and composed law**:

- preserve a short **human-live window** on every escalation;
- sort eligible resolvers by **actual availability**, after authority eligibility is established;
- some act kinds always require human approval, regardless of elapsed time;
- some acts may expire, while others may remain open indefinitely;
- expiration is part of the escalation request/law contract, and `never` is a valid value;
- outside the protected human-live window, the effective action law decides whether a sufficiently-authorized peer may approve alone;
- law may also require a peer factor *after* human approval, so human approval need not always be terminal;
- the governing rule is resolved from **society law composed fractally from the applicable floor plus role law(s)**, and may vary by context;
- every choice and transition is witnessed so the system can be changed from lived evidence rather than intuition alone.

The collective is learning. Measured behavior is therefore an input to law evolution, not an argument for freezing today's constants.

## 1. Core invariant

> An escalation is not a queue addressed to one person. It is a governed resolution process whose eligible authorities, ordering, timing, and terminal conditions are derived from the effective law for that act.

Authority and availability are separate axes:

1. **Authority determines who may decide or contribute a factor.**
2. **Availability determines whom to ask first among those already eligible.**

Availability MUST NOT grant authority. An always-online weakly-authorized peer does not outrank an offline authority; it is simply a more reachable candidate within the authority class law permits.

## 2. Effective law

For an escalated act, Hestia resolves an **effective action law** from the same compositional model used elsewhere:

```text
effective_action_law = compose(
    society_floor,
    applicable_role_laws,
    act_kind_law,
    contextual_constraints
)
```

Composition is fractal: a child role/society may specialize the parent/floor but may not silently erase mandatory floor requirements.

The effective law supplies the escalation policy. Hestia does not hardcode one global peer/human rule.

At minimum the policy can state:

```text
EscalationPolicy {
  kind
  human_live_window
  expires
  human_required
  peer_solo_after_human_window
  human_requires_peer_factor
  peer_factor_requirement
  resolver_authority_rule
  availability_ordering
  independence_rule
}
```

The concrete serialization is deliberately not fixed by this PRD. The semantics are.

## 3. Time model

### 3.1 Human-live window

Every escalation gives the human/operator a **live first-look window**, initially expected to be on the order of a couple of minutes.

This is not the escalation TTL. It is a routing/authority phase:

```text
opened -------------------------------------------------------------->
       [ human-live window ] [ post-window policy phase ... ]
```

During the human-live window:

- the operator is notified immediately;
- peers may still inspect/corroborate if law permits;
- peer evidence is recorded, but peer sole approval does not pre-empt the operator unless the effective law explicitly allows that act kind to do so;
- availability sorting is used to wake useful peer participants, not to race the human.

The default duration MUST be stored in law/configuration and remain empirically adjustable. The current measurements showing median human ruling far ahead of peer response are evidence for tuning routing, not evidence that peer participation is useless.

### 3.2 Expiration

Expiration is distinct from the human-live window.

The escalating entity may request an expiration policy, bounded by effective law. Required forms:

- finite duration / deadline;
- `never`.

The effective law may:

- accept the requested expiration;
- impose a shorter maximum for an act kind;
- require `never` for acts whose resolution should remain pending until deliberately answered;
- forbid `never` for ephemeral or unsafe acts.

The request MUST be recorded with the escalation. A silent global TTL is not constitutional policy.

### 3.3 No inference from expiry

Expiry means **the process timed out under its configured law**. It does not mean the act was wrong, the asker was untrustworthy, or peers declined on the merits.

## 4. Authority phases

The effective law resolves one of several patterns. These are examples, not a closed enum.

### A. Human mandatory

```text
human-live -> human remains required until terminal decision or expiry
peer evidence: advisory or required additional factor
peer sole approval: never
```

Appropriate for high-stakes constitutional, authority-expanding, destructive, financial, identity, or governance-self-modifying acts as law specifies.

### B. Human first, peer fallback

```text
human-live -> if no human decision, eligible peer may become sole resolver
```

This is the primary case where the current peer-latency measurements matter. A peer arriving after 8–15 minutes is not "late" if law intentionally transfers authority after a two-minute human window and the escalation remains alive.

### C. Human + peer

```text
human approval is necessary but insufficient
human approval -> wait for required independent peer factor(s) -> terminal
```

This supports the inverse of today's common ordering. For some act kinds, the operator may decide quickly but law intentionally requires subsequent corroboration before the act becomes executable.

### D. Peer permitted immediately, human always available

For lower-stakes kinds, law may permit a qualified peer to resolve during the human-live window while still surfacing the ask to the human. This MUST be explicit per kind/context; it is not the default implied by "sort by availability."

### E. Multi-factor / quorum

Law may require m-of-n factors from classes of authorities rather than a single decider. Human and peer are factor classes, not necessarily mutually exclusive terminal actors.

## 5. Chain of authority

Resolver eligibility is computed before routing.

A resolver must satisfy the effective law's authority predicate for the **specific act and context**, including as applicable:

- role/office authority;
- scope and permission class;
- proof tier / required evidence;
- NOT-SAME and NOT-BENEFICIARY constraints;
- independence/failure-domain constraints;
- society/federation relationship;
- any law-defined T3/V3 evidence permitted for resolver selection.

The result is an authority graph/chain, not a flat peer list. A candidate may be:

- eligible to advise but not approve;
- eligible to provide one required factor;
- eligible for sole approval only after the human-live phase;
- eligible only as fallback to another role;
- permanently ineligible for the act kind.

The chain MUST be included in the resolution evidence: which authorities were considered, which were eligible, and why the selected resolver/factor was sufficient.

## 6. Sort by availability

Within an eligibility class, route to the best currently reachable candidates.

Availability is measured evidence, not self-declaration. Candidate signals may include:

- recent attributable acts from the actual member/agent;
- a live authenticated session;
- successful recent wake/response latency;
- current harness/process readiness;
- explicit temporary availability declaration only as weak evidence.

A watcher draining a mailbox is **not sufficient evidence that the member is available**. The findings that `recipient_liveness=live` can describe a poll loop while the agent itself is absent are the canonical counterexample.

The sorter should therefore produce something like:

```text
eligible(authority) -> availability evidence -> ranked invitation set
```

never:

```text
available -> therefore authoritative
```

## 7. Kind × window × authority matrix

The decision function is conceptually:

```text
resolution_policy = effective_law[
    act.kind,
    act.context,
    elapsed_phase,
    requested_expiration,
    authority_state
]
```

This is intentionally a matrix rather than a ladder with one global order.

Illustrative rows:

| kind/context | human-live | after window | terminal requirement | expiry |
|---|---|---|---|---|
| routine reversible scope exception | human first | qualified peer may approve | one sufficient resolver | finite/default |
| destructive production act | human first | human still required | human | finite |
| governance-law amendment | human first | human still required | human + independent peer | `never` permitted/likely |
| low-stakes reversible operational act | human notified | peer may resolve | peer or human | short finite |
| constitutional/floor mutation | human first | no peer sole authority | law-defined sovereign ceremony | `never` or explicit long window |

These are examples only. The actual rows live in law.

## 8. Human approval is a factor, not a universal terminal state

Today much of the implementation treats an operator decision as the natural end of the process. This PRD removes that assumption.

Human approval may be:

- terminal;
- one factor in a quorum;
- a prerequisite that activates a peer-review phase;
- a veto/required factor that peers can never replace;
- absent after the live window for act kinds where law explicitly delegates fallback authority.

The chain event must therefore record **what requirement the human factor satisfied**, not merely `decided_by=operator`.

## 9. Peer participation after a ruling

A peer contribution arriving after a human ruling is not inherently wasted.

Its value depends on the policy state:

- if the human ruling was terminal, it is retrospective evidence/review;
- if law requires a subsequent peer factor, it may complete the decision;
- if law permits post-hoc challenge/review, it may open a separate appeal/law-learning path;
- if no policy consumes it, the system should stop spending wakes on that class.

This is the correct interpretation of the current measurement that most corroboration arrives after the operator. The measurement diagnoses a mismatch between present timing and present policy; it does not establish that peer review is structurally useless.

## 10. Learning loop

Every resolution records enough structured evidence to update the policy rationally:

- act kind/context;
- effective law/composite revision;
- requested and effective expiration;
- human-live duration;
- resolver candidates and authority classes;
- availability evidence at invitation time;
- invitation/wake times;
- factor arrival times;
- final factor set and terminal reason;
- whether later peer evidence would have changed/satisfied the configured rule;
- operator overrides or law amendments that followed.

Periodic analysis should answer questions such as:

- Which kinds routinely need more or less human-live time?
- Which eligible peers are actually reachable?
- Where is peer work routinely gathered but unused?
- Where do human approvals wait unnecessarily for evidence that could have arrived earlier?
- Which escalation kinds should default to `never` versus finite expiry?
- Which contexts repeatedly cause humans to amend the same policy after acting?

Changing these answers changes law/configuration, not hardcoded gate behavior.

## 11. Compatibility with current implementation

The current system is a good starting point and remains evidence-bearing:

- it already records escalation opening, decisions, corroboration/dissent, invitation state, and much of the timing needed to learn;
- the measured human/peer latency split is valuable precisely because it tells us the current policy does not line up with the social process;
- existing `single_approver` / peer-bar concepts can be migrated into explicit matrix rows rather than discarded wholesale;
- current peers should continue participating while the matrix is implemented, because their behavior is the dataset that informs the next law revision.

Do not rewrite the subsystem merely to conform to this document. Migrate by making the implicit constants and transitions explicit, measurable law inputs one at a time.

## 12. Acceptance direction

1. Every escalation carries an explicit `kind`, human-live policy, and expiration policy; `never` is representable.
2. The human-live phase and total lifetime are separately visible in the record and UI.
3. Resolver eligibility is computed from effective composed law before availability sorting.
4. Availability ranking cannot cause an otherwise-ineligible resolver to act.
5. At least one test demonstrates **human mandatory beyond the live window**.
6. At least one test demonstrates **peer sole approval becoming valid only after the human-live window**.
7. At least one test demonstrates **human approval followed by a required peer factor before execution**.
8. A `never` escalation survives ordinary TTL maintenance/restart and remains deliberately pending.
9. A finite expiry produces a terminal timeout record, never a silent disappearance.
10. The record names the effective law revision and the authority/factor rule that made the terminal state sufficient.
11. The availability sorter uses attributable member activity/session evidence and does not equate watcher mailbox polling with agent availability.
12. Policy constants can be changed through society/role law without editing gate source.

## 13. Cross-repo ownership

**Hestia owns:** resolver evaluation, phase transitions, invitation/wake behavior, availability measurement, factor accounting, persistence, UI, and witnessing.

**Hub/Web4 owns:** canonical society/role-law composition and the portable vocabulary by which an act kind/context specifies its escalation policy. Hestia consumes that effective law; it does not invent a parallel local constitution.
