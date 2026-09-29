# Hestia Living Lessons

**Status:** living document  
**Purpose:** retain durable engineering and governance lessons after the issues that exposed them are fixed, superseded, or closed.

This is not a second backlog and not a history of every defect. Issues and findings are provenance. The material below belongs here only when it remains useful after the specific implementation changes.

A lesson should normally survive at least one of these tests:

- it constrains future architecture or review;
- it names a recurring failure mode that can reappear in another subsystem;
- it changes how evidence should be interpreted;
- it changes how tests or instruments should be designed;
- it changes the incentives or usability of the governed path.

When an issue closes, preserve its measured corpus and falsifiers in the issue/finding. Promote only the durable rule here.

---

## 1. Evidence must precede interpretation

A system cannot infer meaning from a register that cannot represent the opposite outcome.

Examples have included `outcome.success` populations that were effectively constant, deny classes that produced no row, peer factors visible in decision snapshots without their own factor event, and announcement/event registers that counted different populations (#629, #669, #680, #683, #823).

Durable rules:

- Absence is evidence only when the recording contract makes absence meaningful.
- Name the register and denominator before quoting a rate.
- A snapshot, an activity event, a delivery notice, and an adjudication are different evidence types even when they refer to the same underlying act.
- Actor attribution is event-schema-specific. A generic field such as `plugin_id` must not be assumed to mean actor, filer, subject, owner, or beneficiary across event types.
- Consequential evidence should be committed before it affects derived state. Prefer **committed evidence -> projection** over **mutate state -> later try to describe the mutation**.
- Cached/projection data accelerates evidence access; it is not an independent source of evidence.

See also Assurance FR-4, #822, #823, and `PRD_CONSISTENCY_EVIDENCE.md`.

## 2. Detection, adjudication, and reputation are separate stages

A detector produces a review surface, not a verdict. An adjudication interprets evidence under law. Reputation is an optional contextual consequence of an adjudication.

The required sequence is:

```text
witnessed evidence
  -> candidate / consistency case
  -> adjudication
  -> law-controlled contextual R7 observation
  -> role-context standing
```

Raw regex hits, LLM confidence, candidate counts, age, disagreement counts, or behavioral frequency must not directly change standing.

Corrections are supersessions, never edits. Self-correction, correction after challenge, repeated error after correction, contextual exception, and deliberate misrepresentation are different facts and should remain different observations.

## 3. Authority, identity, availability, and correlation are different quantities

Several Hestia defects have come from one field quietly doing two jobs.

Durable rules:

- Authority comes from effective law and authenticated identity, not from availability.
- Availability can order already-eligible resolvers; it cannot make an ineligible participant authoritative.
- `session_id`, host-session labels, plugin names, and roles can correlate an authenticated principal. They are not themselves authentication.
- Liveness is not observation. Mailbox activity is not proof that a member saw a specific invitation.
- A named role is not role occupancy unless the occupancy itself is authenticated/authorized.

The intended direction is captured by #824 and the escalation authority matrix.

## 4. Lifecycle states must be semantic, not accidental

If two states have different consequences, they need different names and transitions.

For escalation and grants this means, at minimum:

- human-live window is not total escalation lifetime;
- approval is not execution;
- `bar_met` is not necessarily a terminal ruling;
- available grant is not reserved grant;
- reserved is not spent/admitted;
- admitted is not necessarily successfully completed;
- downstream rejection is not successful consumption;
- expiry is not denial;
- withdrawal is not denial;
- lapsed-unclaimed is not expiry-before-ruling;
- retrospective review is not evidence the original decision relied on.

Every transition should have one definition, one sufficiency rule, one evidence contract, and one replay rule. Old records should remain readable under an explicit legacy interpretation rather than being silently reinterpreted through new law.

#825 is the implementation carrier for this consolidation.

## 5. Govern resolved effects, not suggestive text

Lexical command matching has repeatedly failed in both directions: reads refused because governance-looking words appeared elsewhere in a compound command, and real writes permitted because an interpreter, ancestor move, mode spelling, or computed destination hid the effect from the parser (#529, #628, #655, #660, #661, #714, #744, #765).

Durable rules:

- Separate **TOOLS** authority from **FILES** authority.
- Determine executable positions, data spans, path reaches, redirects/write targets, and indeterminate reaches as typed facts.
- A string being present in command text is not evidence that it is executable or a destination.
- A protected descendant can be affected by an operation on an ancestor; protection cannot reason only from descendant path matches.
- Unknown/opaque analysis must remain explicitly unknown. Do not silently turn uncertainty into either permission or a fabricated offending token.
- A denial should say which authority axis failed and identify the normalized evidence that caused it.

#760 is the current migration carrier for the MRH path-proxy half of this lesson. `GATE_ARCHITECTURE.md` owns the broader one-common-gate direction.

## 6. The compliant path must be cheaper than the route-around

Hestia is a governance construct, not an impenetrable containment wall. Capable participants can often rephrase, decompose, change tools, or otherwise reach the same effect.

Therefore control quality cannot be judged only by how often a boundary fires. The **cost gradient** matters.

If a correct governed action requires minutes and an equivalent ungoverned/recast action requires seconds, the mechanism teaches participants to route around it. If false-positive escalations are routinely approved, operator approval becomes a low-information keystroke and the queue loses selectivity (#530, #536, #630, #631, #668).

Durable rules:

- Measure completion and latency of the compliant path.
- Measure whether decisions are selective, not merely whether they exist.
- Reduce duplicate petitions and redundant rulings before optimizing timeout constants.
- Expose the exact remedy at the point of refusal; a remedy hidden in another tool or document is not an effective path.
- Prefer mechanisms that make truthful compliance the shortest useful route.

## 7. A passing test proves only the layer it actually exercised

Multiple investigations were prolonged by controls that were technically green but did not exercise the disputed mechanism (#633 is the clearest example).

Durable rules:

- Every negative result needs a positive control for the exact layer being measured.
- A positive control in a neighboring layer does not validate the target layer.
- Deliberately separate fields/actors/paths that a bug might accidentally conflate.
- Include the known failure seam in regression tests, not merely a nearby happy path.
- When an instrument is itself part of the evidence chain, test the instrument against a falsifier before trusting its census.
- Preserve `UNKNOWN` rather than reporting a clean zero when the measurement surface is incomplete.

## 8. Deployment truth is a ladder, not a Boolean

Hestia repeatedly demonstrated that source truth and runtime truth are different facts.

Use the evidence ladder explicitly:

```text
source -> merged -> installed -> restarted -> live -> observed -> publicly released
```

Durable rules:

- `merged` does not mean `in force`.
- A hook, its shared authority, and the daemon binary form a release/deployment set when their semantics depend on one another.
- A working tree is not a deployment target.
- A process can continue executing old bytes after the file on disk changes.
- A per-wake helper may execute new disk bytes immediately while its parent watcher still runs old code; measure each execution model separately.
- Silence is not health. Periodic integrity/status signals need an explicit freshness horizon.
- Half-deployment is a first-class state and should be visible as such.
- Deployment evidence should include resident paths, hashes/build identity, and the authority that ratified them.

See #606, #654, #716, #779, #780, and the release/status work around #746.

## 9. Privacy and visibility survive derivation

An analyzer being technically able to read evidence does not widen the evidence's authorized audience.

Derived cases, explanations, embeddings, reputation observations, and federation exports must preserve source visibility and purpose constraints. A useful evidence system must not become a surveillance bypass merely because it is good at joining records.

Where full source evidence cannot travel, carry adjudicated outcome plus provenance/commitments sufficient for the relying party to decide under its own law.

## 10. Closed-loop remedies must be reachable from the failure state

A remedy is not real if the failing rule blocks the act needed to invoke the remedy.

Hestia has seen appeals blocked by the vocabulary of the appealed rule, scope requests blocked because they must name the out-of-scope path, and locked seats unable to run or even read the repair path (#617, #622, #647, #687, #715, #780, #792).

Durable rules:

- Every fail-closed state needs at least one independently reachable recovery/control path.
- The recovery path should not depend on the same predicate whose failure it is intended to repair.
- Refusal text must state whether the class is appealable/escalatable and name the actual reachable remedy.
- Governance testimony (`reason`, `rationale`, adjudication text) is evidence about an act, not the act itself; do not casually subject testimony to the same lexical execution rules.

## 11. Corrections and retractions are evidence of system health

The fleet has repeatedly improved because participants published corrections to their own prior findings. Those corrections must remain visible rather than being treated as embarrassment to clean up.

Durable rules:

- Preserve the original claim and its superseding correction.
- Record what falsifier changed the interpretation.
- A corrected model can be stronger evidence of good process than an unchallenged correct guess.
- Reputation, when applied, should be able to represent high-quality self-correction positively rather than rewarding only the absence of visible mistakes.

## 12. Backlog hygiene: evidence is not the same thing as a work queue

A mature issue tracker needs different treatment for different artifacts.

Use these categories conceptually even if GitHub labels do not yet encode them:

1. **Evidence/finding** - measured observation, corpus, falsifier, incident record.
2. **Decision/design** - a ruling or architecture choice.
3. **Implementation carrier** - the one live issue that owns remaining acceptance.
4. **PR** - a bounded candidate implementation.
5. **Historical/superseded** - valuable evidence whose coordination role moved elsewhere.

Closing an evidence issue does not delete it. When a broader carrier contains its acceptance contract, close the old coordination surface with a short supersession note and retain the original measurements as provenance.

Do not keep multiple open issues merely because each discovered the same mechanism from a different angle. Conversely, do not close a finding simply because a broad PRD mentions the topic if its concrete acceptance/falsifier has not been carried forward.

---

## Maintenance rule

This file should grow slowly.

Add a lesson when a finding changes how future work should be done. Amend a lesson when lived evidence makes it more precise. Remove or rewrite one when a later falsifier proves the generalization wrong.

The goal is not to remember every bug. It is to avoid having to rediscover the same class of mistake under a new filename.
