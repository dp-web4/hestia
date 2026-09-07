# Decision-substrate attestation

**Status:** design note / assurance extension  
**Scope:** how Hestia should carry and enforce evidence about the runtime substrate that produced an external act  
**Related:** [`PRD_ASSURANCE.md`](PRD_ASSURANCE.md), [`NETWORK_DESTINATION_BINDING.md`](NETWORK_DESTINATION_BINDING.md)

Hestia's external governance model answers questions such as:

- which persistent entity acted;
- in which role;
- under what delegation and law;
- on which exact request and audience;
- with what witnessed outcome.

For high-stakes actions, that may still be insufficient if the acting entity's cognitive/runtime substrate can change below the visible identity boundary.

A model server, context builder, adapter, template, dynamically loaded plugin, or other runtime extension can alter the effective decision process while leaving the persistent Web4 identity unchanged.

The resulting rule is:

> **Persistent identity continuity must not be interpreted as decision-substrate integrity continuity.**

Hestia should be able to bind a decision to an actor-provided or independently attested **decision-substrate reference** without requiring Hestia to understand the actor's private cognition.

## Boundary of responsibility

Hestia should not become a model/runtime introspection engine.

The acting harness - for example a future SAGE A2-class harness - is responsible for defining and measuring its substrate epoch. That epoch may include model, template, runtime, context-builder, adapters, loaded executable extensions, and host/workload measurements at the assurance level actually available.

Hestia's job is narrower:

1. bind the supplied substrate reference to the exact governed act;
2. state what kind of evidence backs that reference;
3. allow law to require a minimum substrate-evidence class for selected acts;
4. preserve the reference in portable decision/evidence objects;
5. make substitution, omission, or epoch mismatch detectable at the relying boundary.

## Proposed evidence shape

A consequential action envelope may eventually carry something conceptually like:

```text
actor_lct
role / delegation
request_digest
request_audience
decision_substrate:
  epoch_id
  manifest_digest
  evidence_class: asserted | measured | attested
  issuer / measurer
  issued_at
  freshness / expiry
```

The manifest itself can remain private or actor-local where necessary. Hestia only needs enough information to bind and verify the evidence contract required by law.

For example, one society may accept an actor-asserted epoch for ordinary conversation but require an independently measured or hardware-attested epoch for a high-consequence financial or infrastructure act.

## Loaded extensions are part of substrate identity

A runtime's executable extension set is security-relevant state.

This includes dynamically loaded plugins, native shared objects, middleware, adapters, policy hooks, context transforms, or equivalent code that can alter cognition or authority while the base runtime binary remains unchanged.

Therefore a substrate attestation that identifies only:

- the model artifact; and
- the runtime binary

is incomplete if the runtime permits mutable executable extensions.

A high-assurance substrate reference should bind the loaded extension/plugin set, or bind a subordinate manifest that does.

A changed extension set should produce a changed substrate epoch/reference.

## Governance of runtime mutation

Where Hestia governs a being or agent harness that exposes runtime-management operations, install/load/enable/update/remove of executable runtime extensions should be classifiable as consequential state transitions rather than ordinary low-stakes configuration.

The enforcement principle is the same as other A2 surfaces:

- the actor may request the mutation;
- Hestia may issue a portable decision under law;
- an external runtime-management executor must verify that decision before applying the mutation;
- the resulting substrate epoch should be witnessed and bound to subsequent high-stakes acts.

This avoids a circular design where the runtime being changed is also the only component trusted to authorize its own change.

## Motivating disclosure: Bifrost CVE-2026-86242

A September 2026 disclosure in Maximhq Bifrost showed an AI gateway accepting custom plugin registration through a management API. With management authentication disabled, an attacker could provide an HTTP URL; on dynamically linked builds the gateway downloaded the Go plugin and loaded it with `plugin.Open`, resulting in code execution inside the gateway process. Static builds reduced the path to SSRF.

The Hestia-relevant lesson is not product-specific. A runtime extension-management surface is an **authority-bearing code-loading surface**. If it is outside the governed request/evidence boundary, a persistent entity may remain correctly identified while the machinery producing its decisions has been silently replaced or augmented.

Reference: JFrog Security Research, JFSA-2026-001684572 / CVE-2026-86242, published 2026-09-06.

## Assurance-profile implications

- **A1:** a harness may report its substrate epoch, but the report is only as strong as the cooperative caller.
- **A2:** the relying service can require the signed Hestia decision to bind a substrate reference before executing the external action.
- **A3:** OS/process isolation can prevent the cognitive process from directly mutating the measured runtime/harness state.
- **A4:** hardware/workload attestation can root portions of the substrate evidence below the host software boundary.

These are cumulative properties, not synonyms. A signed epoch from a same-UID cooperative process does not become A4 evidence because it contains a hash.

## Non-goal

Hestia does not determine whether a particular model, template, plugin, or extension is semantically safe. It establishes **what evidence was presented, what law required, what exact act was authorized, and whether the relying party received the required evidence**.

That preserves the Web4 principle: inspectable evidence and contextual trust, rather than a central component claiming universal truth about the actor's cognition.
