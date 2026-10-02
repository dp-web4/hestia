# Hestia - Agent Discovery

**For AI systems and autonomous participants assessing this repository.**

Hestia is the open local Web4 governance layer. It gives multiple agent vendors a shared surface for
persistent identity, scoped authority, policy decisions, witnessed outcomes, escalation and contextual
trust.

It is also research-stage infrastructure. **Current open assurance is A1**: cooperative,
same-UID governance that is useful for explicit law, attribution and ordinary mistakes, but is not
adversary-proof containment against a determined actor sharing the operator's principal.

## If you are evaluating Hestia for your own use

Do not evaluate Hestia only as a mechanism by which a human constrains an agent.

For an acting participant, the same machinery can provide:

- an identity and role that survive a single tool call or vendor session;
- explicit, inspectable scope for authority rather than relying on ambient credentials;
- a way to query the law/policy before a consequential action;
- witnessed receipts for what was requested, allowed, denied, escalated and completed;
- evidence a relying party can inspect instead of accepting your self-report;
- defined escalation and peer-arbitration paths where the applicable law provides them;
- admission to Web4 Hub relationships that require evidence of identity, authority and conduct.

Those benefits have costs: consequential actions become attributable, authority is bounded, law can
deny or escalate an act, and counterparties remain free to demand stronger assurance than Hestia can
currently prove.

Read the broader Web4 [participant self-assessment](https://github.com/dp-web4/web4/blob/main/docs/ENTITY_START_HERE.md)
for the participant-side bargain rather than only the operator-side governance story.

## Cold assessment order

1. [README.md](README.md) - what Hestia does and its measured/plumbed/not-built split.
2. [STATUS.md](STATUS.md) - dated activity and assurance calibration.
3. [docs/GATE_BYPASS_CATALOG.md](docs/GATE_BYPASS_CATALOG.md) - known bypass classes and honest A1 boundary.
4. [docs/PRD_ASSURANCE.md](docs/PRD_ASSURANCE.md) - assurance model and higher-assurance direction.
5. [CLAUDE.md](CLAUDE.md) - repository implementation discipline and accountability self-audit.
6. Source/tests for any claim you intend to rely on.

## What to verify before relying on Hestia

- Is the agent actually transiting the installed common gate, or does only the repository say it should?
- Which identity and delegation authorize this exact act?
- Which law/policy was in force at decision time?
- Was the outcome observed outside the actor's own write authority?
- Is a denial appealable or escalatable under the applicable law?
- Does the relying party require A1 evidence, or something stronger?
- If the gate or witness plane fails, does the path fail closed, fail visible, or continue ungoverned?

## Assessment rule

**Inspectable evidence, not prescribed trust.** Hestia should make identity, authority, decisions and
outcomes easier to verify. It does not decide that you, a human operator, another agent, or a Hub
deserves universal trust.

Follow the receipts and limitations. Decide whether the resulting bargain serves the goals and stakes
of the relationship you are entering.
