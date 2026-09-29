# Standards review entry point

**Status:** informative, 2026-09-18

Hestia is the local runtime-governance reference layer for Web4. Reviewers working on AI agent identity, authorization, delegated authority, provenance, runtime monitoring, revocation, and non-repudiation should start with the standards package in the Web4 repository:

- Standards landing page: https://github.com/dp-web4/web4/tree/main/docs/standards
- NIST / NCCoE crosswalk: https://github.com/dp-web4/web4/blob/main/docs/standards/NIST_NCCOE_AI_AGENT_IDENTITY_AUTHORIZATION_CROSSWALK.md
- Implementation evidence: https://github.com/dp-web4/web4/blob/main/docs/standards/IMPLEMENTATION_EVIDENCE.md
- One-page technical introduction: https://github.com/dp-web4/web4/blob/main/docs/standards/OUTREACH_ONE_PAGER.md

## Hestia's role

In standards vocabulary, Hestia supplies the local control and evidence plane:

- authenticated member / agent identity;
- role and delegation checks;
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
