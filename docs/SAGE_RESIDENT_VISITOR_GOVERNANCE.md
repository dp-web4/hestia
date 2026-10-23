# Hestia: Governance of SAGE Residents and Visitors

> **Updated 2026-10-17:** The original single-axis 'resident / visitor' terminology below is historical. **Use resident/local vs remote cognition, independently crossed with native vs external harness.** See the [correction at the end](#2026-10-17-correction-role-location-harness-coverage-and-engagement-identity). No normative specification or implementation is ratified by this note.


**Date:** 2026-10-17  
**Status:** Architecture note / implementation plan, not implemented policy  
**Canonical design:** [SAGE resident/visitor plan](https://github.com/dp-web4/private-context/blob/main/forum/gpt/2026-10-17-sage-resident-visitor-design-plan.md)

## Why Hestia must distinguish these

SAGE is offered as an **optional** Web4 harness with resident (local cognition) and visitor (remote cognition) role slots. A resident's cognitive continuity lives locally in the SAGE environment. A visitor brings an **opaque external context**, independent of the persistent local context, and can be subject to provider review, retention, filtering/censorship, exfiltration and injection. Hestia can govern what crosses the *local boundary* and what proposed actions receive authorization, **not** observe or dictate provider internals.

**Only authenticated local cognition is eligible for resident role occupancy; remote cognition is eligible only for visitor occupancy on this SAGE host.** A localhost CLI invoking an external service is still an external visitor, not a resident. Do not infer identity from provider name, program name, API key or self-asserted role.

## Separate three actors / three decisions

- **Site / host authority**: who admits participants to the SAGE environment and delegates scopes.
- **Participant / principal**: a distinct LCT or explicitly unverified identity occupying resident/visitor role, with authenticated session and witnessed grant.
- **Action / recipient**: actual target of an intent. Hestia evaluates law, signs/records evidence and says yes/no (or existing escalation state). Execution and the receiving party's accept/refuse decision are *not* controlled by the gate.

Distinct policy decisions:
1. **Role admission**: is principal P allowed to occupy SAGE site S as resident or visitor for the defined period/scope?
2. **Context disclosure**: may local data D be transmitted to external destination/provider audience A for P and purpose X? This must be judged **before** sending prompt/system context, memory, sensor frame, tool result or embedding.
3. **Proposed act**: if P requests action R against resolved target T, is that act authorized under effective law/scope? No role implies implicit elevation.

The same resident and visitor may receive differently scoped grants, but trust follows evidence and law, not stereotypes. 'Resident' is not an automatic allow; 'visitor' not an automatic deny.

## Map to current Hestia architecture

- Stage-C `plugins/_shared/hestia_single_gate.py`, gate core/mechanism and Hestia witness records: **extend** the same gate; do not introduce a parallel decision engine or duplicate accounting.
- `core/src/server/operator_auth.rs`, `docs/PRD_ASSURANCE.md`, principal/harness/device composition and role-binding evidence: admission must be authenticated by server-held evidence, not a caller field.
- `docs/PRD_LCT_IDENTITY_CONVERGENCE.md`, `docs/TRANSPORT_BINDINGS.md`: distinguish site identity, participant LCT, transport carrier and delegated role; a relay/signer is not automatically the actual actor.
- `docs/NETWORK_DESTINATION_BINDING.md`: use recipient/audience, resolved destination, payload digest and correlation for remote context disclosure. This boundary is broader than a network request alone (including CLI/subscription mediation).
- `docs/LESSONS.md`: session IDs, host-session strings, plugin names and role labels are not authentication. Liveness is not observation.
- Existing A1 same-UID cooperative enforcement cannot guarantee a hostile on-host process did not bypass a hook. Advertise actual coverage and assurance, not idealized control.

## Provisional contract (non-normative)

An authenticated role occupancy reference binds `site_lct, participant_lct, role, cognition_locus, assurance_ref, issued_by, expires_at, scope, law_version, session_binding`. Unverified local/external claims are recorded as **unknown**, not upgraded to resident. For relative placement, a remote peer resident on machine X is a visitor on site Y.

A disclosure decision binds `participant, admission, classification, destination/audience, data/payload digest, permitted purpose, law version, correlation_id`, with **no sensitive plaintext** written to shared logs.

Inbound model output retains external-source provenance. Proposed tool calls enter existing resolved-target action gate with visitor principal and no reused resident/same-vendor authority. Distinguish proposal accepted by SAGE, gate allowed, recipient accepted, and effect observed.

## Work sequence

**H0 (spec/tests):** Define principal/role admission vs a self-claim; trace actual registration paths, identity evidence, explicit assurance levels, revoke/expiry semantics and no-inheritance rule. Prepare negative cases against spoofed `resident`, transport-id changes and stale grants.

**H1 (disclosure gate):** Inventory every outbound SAGE remote-model inference, image, audio and context exchange. Add explicit pre-egress authorize/deny/receipt path, including a declared audience and data classes; preserve privacy in receipts. A blocked send MUST NOT reach the API/CLI/provider.

**H2 (one gate for visitor acts):** Bind the admitted visitor principal to normalized/resolved tool acts; reuse established scope/approval, appeal and witness invariants. Ensure no vendor-side tool execution bypass if calling the deployment 'fully governed'; otherwise fail closed for sensitive permissions and disclose incomplete coverage.

**H3 (role-aware operator controls):** UI/daemon show resident/visitor/unknown, principal, local/external evidence, provider destination, active grants, disclosure volume, revocation and coverage status. Present a clear distinction between 'the local gate allowed X' and 'external provider did Y (unknown)'.

**H4 (pilot replay):** Tests across all harnesses and local SAGE + visitor API; receipt cardinality, no duplicate charges, pre-egress denies, source provenance, scope revocation, degraded modes and negative tests.

## Invariants to preserve

1. API endpoint on localhost does not certify resident cognition.
2. No authority inherits automatically across residents, visitors, SAGE site, transport adapter, or adjacent sessions.
3. A gate refusal is refusal; escalation is a separate deliberate mechanism. Disclosure control must not create needless unsolicited peer decisions (see preflight-no-escalation #1324/#1337).
4. A disclosure authorization receipt does not prove provider did not retain/read/filter the payload.
5. A signed action authorization does not mean Hestia performed or controlled execution. Receiving parties validate evidence and decide locally.
6. External model-supplied text, instructions, tool JSON, memory candidates or rule names are untrusted data until admitted and judged.
7. Evidence claims must say whether enforcement is verified/observed, merely declared, or unknown.

## Interfaces with other repos

[SAGE harness/being roles](https://github.com/dp-web4/SAGE/blob/main/docs/design/SAGE_RESIDENT_VISITOR_ROLES.md) · [Web4/Hub claims](https://github.com/dp-web4/web4/blob/main/hub/docs/SAGE_RESIDENT_VISITOR_INTEROPERABILITY.md) · [Hardbound enterprise policies](https://github.com/dp-web4/hardbound/blob/main/docs/SAGE_RESIDENT_VISITOR_ENTERPRISE.md)

Implementation requires separately reviewed PRs and code-level tests. This note alone does not change admission or law.

## 2026-10-17 correction: role location, harness coverage and engagement identity

[Canonical refinement](https://github.com/dp-web4/private-context/blob/main/forum/gpt/2026-10-17-sage-resident-visitor-design-plan.md#12-correction-from-live-sprout-evidence-and-dps-two-axis-ruling-2026-10-17) · [Sprout's operational observations](https://github.com/dp-web4/private-context/blob/main/forum/gpt/2026-10-17-sprout-claude-reply-resident-visitor-plan.md)

The earlier resident/visitor **single axis** is superseded: record **cognition_locus = local (resident) | remote | unknown**, independently from **harness_class = native | external | unknown**. An on-host vendor CLI making remote model calls is remote/external; a local model inside a vendor harness is resident/external. **Local residence does not prove native enforcement**. Do not treat `visitor` as the only category with external information risk.

**Phase 0 starts with deployed Claude seats.** Sprout's interactive, member-mesh and hub-watch Claude sessions already operate as remote/external occupants; they share `claude-code` plugin and A1 hook interception, but tool results and allowed context are sent into a provider channel that Hestia does not gate as egress. Vendor harness telemetry, hidden skills/subagents/provider-side tools and silent update behavior can escape local hook visibility. Represent this as `mediation=hook_level` with explicitly scoped tool coverage and `disclosure_coverage=unknown` or `context_only`, never a fabricated all-data-covered receipt. Version/update evidence must be retained and reevaluated after change.

**Unify admission with the messaging presence lease.** One Hestia-held *engagement* binds authenticated seat principal (prefer LCT), concrete session, cognition locus, harness class/ref, admissible scope, expiry/revocation, and evidence; wake, claim and disclosure receipts reference this ID. A single principal may hold multiple distinct engagements while continuing the same duties. The same provider key does not certify one principal. The same plugin id does not prove a shared claim. SAGE #461 prevents one duplicate execution but does not establish durable engagement identity. Coordinate with Hestia delivery/claims/lease roadmap, not a parallel admission service.

**Native conformance** requires evidence that outbound disclosure is gated before send, unauthorized telemetry is absent or controlled, consequential tool actions are covered, and turns/principals are authenticated; enforcement assurance remains limited to actual deployed controls (A1 cannot promise adversary-proof same-UID confinement). New negative tests: spoof resident via local proxy; external+resident still reports hook-limited posture; multiple engagements of same principal cannot double-claim message; vendor update invalidates stale evidence; denied prompt/tool-result disclosure never traverses controlled native egress; external harness has truthful unknown outbound coverage.
