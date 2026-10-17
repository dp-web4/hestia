# Standards review entry point

**Status:** informative, 2026-09-18

Hestia is the local runtime-governance reference layer for Web4. Reviewers working on AI agent identity, authorization, delegated authority, provenance, runtime monitoring, revocation, and non-repudiation should start with the standards package in the Web4 repository:

- Standards landing page: https://github.com/dp-web4/web4/tree/main/docs/standards
- NIST / NCCoE crosswalk: https://github.com/dp-web4/web4/blob/main/docs/standards/NIST_NCCOE_AI_AGENT_IDENTITY_AUTHORIZATION_CROSSWALK.md
- Implementation evidence: https://github.com/dp-web4/web4/blob/main/docs/standards/IMPLEMENTATION_EVIDENCE.md
- One-page technical introduction: https://github.com/dp-web4/web4/blob/main/docs/standards/OUTREACH_ONE_PAGER.md

## Hestia's role

In standards vocabulary, Hestia supplies the local control and evidence plane. Status of
each item against code was re-checked 2026-10-14; the first two are narrower than the
vocabulary suggests:

- member / agent identity: **asserted, not authenticated**. Hestia mints and custodies
  member LCTs, but on the tool-call path the caller supplies its own `plugin_id` over an
  unauthenticated local MCP transport (`core/src/server/handler.rs` `tool_connect`).
  Transport-established identity is
  [PRD_ASSURANCE FR-1](PRD_ASSURANCE.md), state *not started*. Stronger, key-bound proof
  exists only on specific doors: operator HTTP sessions (Ed25519 challenge), delegated scope
  arbitration (seat registry key signature) and signed mesh envelopes;
- role checks, and delegation for **scope arbitration only**: the launch role is checked
  against the vault projection's permitted roles on every call; signed, revocable
  delegation objects (`core/src/delegation.rs`) are consulted when a seat decides a scope
  request inside a delegated prefix, and are not consulted on the tool-call (PreToolUse)
  decision as of this date. Work in progress may change the second half; check the README
  status table for the current state;
- scoped authority;
- allow / deny decisions;
- human escalation;
- peer adjudication paths;
- revocation;
- witnessed action / outcome records;
- local vault and credential custody;
- evidence-derived trust;
- a place to move enforcement from A1 cooperative mediation toward A2 external enforcement.

## Assurance statement

The current open deployment is **A1**. It is cooperative and tamper-evident, not tamper-proof against a determined same-UID actor.

That boundary is documented in:

- [Honest status](../README.md#honest-status)
- [Gate bypass catalog](GATE_BYPASS_CATALOG.md)
- [Governance PRD](PRD_GOVERNANCE.md)
- [Network destination binding](NETWORK_DESTINATION_BINDING.md)

Reviewers should not infer A2+ enforcement from A1 evidence.
