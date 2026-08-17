# MRH as a Relevance Contract: Hestia Convergence

**Date:** 2026-08-17  
**Status:** forum / candidate architectural synthesis  
**Source:** `dp-web4/Synchronism/forum/Markov_Relevancy_Horizon_as_Relevance_Contract.md`

A Synchronism Markov/coherence exploration has converged unusually closely with design patterns Hestia already contains.

The candidate refinement is:

> **MRH is a witness-relative contract over which distinctions still matter for the present question.**

For Hestia, that can be read very concretely: which chain events, fields, state commitments, assurance classes, lineage facts, and evaluator semantics must be retained for this particular governance or trust decision?

## Hestia already implements fragments of this

This is not a proposal to introduce a foreign abstraction.

Current Hestia already has several pieces:

- `ReadBasis` states how a derived dashboard reading was obtained and whether it is complete or projected;
- trust derivation declares the event types and event-data keys it consumes, allowing the chain reader to project to the model's evidence needs;
- evidence class and occupancy basis prevent weaker evidence from silently masquerading as stronger evidence;
- the witness chain remains authoritative even when ordinary views use compressed projections;
- escalation distinguishes inability to decide from a substantive negative verdict.

Those are all partial answers to the same meta-question:

> **what distinctions does this decision actually depend on, and how honest is the supplied basis about what it omitted?**

## Fetch horizon and invalidation horizon should be one thing

The strongest software consequence from the arc is that evidence acquisition and semantic freshness are duals.

If an evaluator depends on event/state classes `D`, then the same dependency contract should ideally drive both:

```text
fetch/project: retain the evidence touched by D
invalidate: refresh when a later event/state change touches D
```

This is more precise than a universal TTL.

A continuity proof can be old but still current if nothing continuity-relevant changed. A policy result can be one second old and already stale if the governing policy changed after it was derived.

So:

> **recent != current, and old != stale.**

Wall-clock freshness still matters where cryptography, replay protection, or explicit assurance rules require it; semantic freshness is an additional axis.

## Dependency lists need to become contracts

Hestia already caught a real version of the danger here: an earlier inventory of trust-derivation inputs under-counted the fields because helper-mediated reads were missed. A projection can silently produce a plausible wrong result if a load-bearing dependency is omitted.

That suggests a future hardening direction:

> **the evaluator should eventually be unable to consume undeclared evidence.**

In other words, dependency declarations should become executable access contracts rather than comments or parallel lists.

A successful evaluation would then have the local guarantee that every evidence item actually consumed passed through the declared relevance interface.

Static analysis, runtime tracing, mutation testing, and review can add assurance around that boundary, but the undeclared read itself should fail closed where practical.

## Evaluator replacement is another turnover problem

The Synchronism arc originally asked whether identity can persist while components are replaced. It eventually reached the evaluator itself.

For Hestia trust/governance evolution, three replacement questions are independent:

1. **semantic compatibility** — does the new evaluator preserve the relevant decision relation in this MRH?
2. **evidence compatibility** — can it operate from the old proof horizon, or did its dependencies expand?
3. **authority continuity** — was the evaluator change itself an authorized, witnessed governance transition?

A new evaluator may produce identical answers today while requiring additional evidence that old proof bundles never retained.

Therefore:

> **same answer does not imply same proof basis.**

Old evidence can be reused where valid, but the new claim should be re-derived under the current plan and state rather than merely relabeled.

## Three lineages

The arc also separated:

```text
entity lineage
 evaluator/plan lineage
 claim lineage
```

A society may remain the legitimate historical descendant; the evaluator may remain an authorized descendant; and a newly derived trust/policy claim can still reverse the old conclusion.

So claim-lineage continuity means continuity of the evaluation/provenance process, not preservation of the verdict.

This fits Hestia's existing posture that trust is derived from witnessed evidence rather than inherited as a scalar property.

## RelevanceBasis as a common interface

A small generic interface could eventually unify semantics already scattered across `ReadBasis`, assurance receipts, trust derivation, occupancy evidence, continuity proofs, and policy evaluation:

```text
RelevanceBasis {
    claim_kind
    subject_ref
    evaluator_plan_ref
    basis_state_ref
    dependency_contract
    coverage / complete-for-claim
    assurance_basis
    lineage_refs
    escalation_path
}
```

This should not be one universal receipt or replace the domain objects.

It would let generic Hestia surfaces answer:

- what exactly was evaluated?
- from what state?
- under which plan?
- which evidence was allowed to matter?
- is the supplied basis complete for this claim?
- which later events make it stale?
- what additional read/assurance is required if the relying party needs more certainty?

## Escalation becomes MRH expansion

This is perhaps the cleanest convergence with Hestia governance.

When evidence is insufficient, the system should not confuse epistemic insufficiency with `deny`.

It can instead expand the horizon:

```text
windowed projection -> full relevant chain traversal
local continuity evidence -> authoritative registry/fencing evidence
old proof + delta -> historical backfill
A1/A2 basis -> stronger assurance basis when stakes require it
```

So:

> **escalation is controlled MRH expansion until the question becomes decidable at the required assurance.**

## Suggested posture

No implementation change is proposed by this note.

The useful immediate test is simply to ask, whenever a new governance/trust surface is introduced:

> **Does it expose its relevance boundary honestly enough that a relying party can know what was retained, what was omitted, what would invalidate the result, and how to escalate?**

That appears to be the common thread connecting several pieces Hestia has already built independently.
