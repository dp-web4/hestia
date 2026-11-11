# PRD - Hestia as the Personal Web4 App

**Date:** 2026-11-11  
**Status:** Proposed product direction; not implementation authorization or release claim  
**Scope owner:** Hestia (personal identity, governance and user experience)  
**Companion:** [Hub as a Community Website](https://github.com/dp-web4/web4/blob/main/hub/docs/PRD_MEMBER_WEBSITE_FIRST_USER_2026-11-11.md)  
**Existing authority:** [PRD_APP.md](PRD_APP.md), [APP_BUILD_PLAN.md](APP_BUILD_PLAN.md), [PRD.md](PRD.md). This document augments rather than silently supersedes their identity/governance decisions.

## 1. Product thesis

Web4 is a protocol substrate, not a user interface. To a person, **Hestia is an app**: install it, establish an identity, join communities, connect an agent, see what it requests, make consequential decisions, and inspect receipts. Terms such as LCT, MRH, T3/V3, R6, policy entity and witness ledger belong below the initial surface, accessible on demand rather than imposed as prerequisites.

A person must be able to use an ordinary Hub website without Hestia. Installing Hestia adds a durable personal presence, governed agents, attestable actions, local custody and richer participation. It must not be a coercive browser-login gate.

## 2. Observed baseline and problem

- The Rust daemon and local gate are exercised in daily use; A1 cooperative/tamper-evident governance is **not** adversary-proof enforcement.
- The Tauri React app has code for identity-adjacent views, vault, policy, chain, fleet, hubs, settings. The local daemon dashboard is more exercised than the downloadable app.
- The only public app artifact recorded in the August 2026 build plan is an older Android APK; current desktop signed/downloadable releases, fresh-install compatibility and mobile equivalence are not demonstrated.
- The existing [app PRD](PRD_APP.md) prioritizes three human concepts: **Me**, **Communities**, **Activity**, and *ability to make good decisions* over raw information quantity. Retain that principle.
- Today an interested nondeveloper cannot reliably complete a fresh install and meaningful governed task without operator help.

These are baseline claims from maintained project docs, not assertions of new test results.

## 3. Personas and jobs

| Person | Job | Successful visible result |
|---|---|---|
| Individual | Get a persistent identity and control who sees it | Profile, privacy controls, verifiable status |
| Community member | Join and participate in a Hub | Membership, role, requests and receipts |
| Agent owner | Connect a local AI agent and bound its authority | Plain-language permission settings and decisions |
| Community participant | Verify a contribution or introduction | Context, actors, consent, evidence and recourse |
| Operator/advanced user | Inspect proofs, law, diagnostics and assurance | Drill-down with exact witness evidence |

## 4. Non-negotiable product requirements

**H1 - Download and first-run:** Publish reproducible platform-specific packages and compatibility metadata. On a clean supported device, guide installation, safe defaults, identity creation/recovery and optional local daemon connection. Do not label a platform supported without a tested release pair. Never silently create an exposed listener or unsafe plaintext secret.

**H2 - Three-place navigation:** Make **Me / Communities / Activity** the primary navigation on desktop and mobile. Keep developer/technical details behind explicit advanced surfaces; preserve critical escalation visibility globally. User goals, not backend module names, determine IA.

**H3 - Identity and custody:** Explain and demonstrate where private keys, personal profile and history are stored, what a Hub learns, what is disclosed, and what recovery actually supports. No implied universal portability where federation or recovery is unimplemented.

**H4 - Hub connection:** Discover or enter a Hub URL; inspect its identity, charter/law, admission requirements and data-sharing implications before joining. Join or leave through a governed consent flow, display current membership and role, distinguish request/pending/admitted/refused/revoked. Do not imply a membership exists until verified.

**H5 - Governed agent permissions:** Connect supported harnesses through existing Hestia gateways. Show *who is asking, for what, on whose behalf, under which authority, and with what consequence*. Distinguish allow, deny, escalate, timed-out and action outcome; a permitted action is not proof it occurred or was correct.

**H6 - Receipts and reputation:** Show human-readable action history and contextual trust with evidence provenance, time, scope, recourse and uncertainty. No universal star score; no unexplained reputation number. Explain that self-declared skills and witnessed/verified contributions are different.

**H7 - Consent, data, security:** Minimize disclosure, require explicit confirmation for sharing a profile, performing introductions or forwarding claims, and offer revocation/exit paths consistent with protocol law. Protect the vault, least-privilege IPC, session tokens, and remote transport. A locked or offline state must be honestly visible and must not bypass law.

**H8 - Accessibility and internationalization:** Keyboard navigation, screen-reader labels, mobile layouts, recoverable errors and plain-language strings. Localized language must not silently change legal semantics.

**H9 - No lock-in claim:** A Hestia installation is not required to view a public Hub website; proprietary Hardbound assurance is separate and not a hidden dependency for the first-user path. Document AGPL obligations and commercial alternatives without making legal assurances about third-party proprietary products.

## 5. Critical journeys and acceptance tests

### Journey A - Ordinary member
1. Open a Hub's public URL in a browser without installing Hestia.
2. Understand the society and its law; view only information explicitly made public.
3. Choose richer participation and install Hestia (optional).
4. Establish identity and review intended profile disclosures.
5. Submit a join request; see pending status, then a signed/verified admission outcome.
6. See the new society in **Communities**. Verify that no hidden private attributes were published.

**Pass:** An external test participant completes the journey on a fresh supported machine without terminal commands, while evidence shows identity, consent and receipt binding. **Fail:** A browser visitor is forced to install Hestia to read public information.

### Journey B - Agent owner's governed action
1. Connect one supported agent/harness and grant narrowly scoped authority.
2. Agent attempts a benign operation, then an out-of-scope one.
3. User sees meaningful context for any required decision, without spurious repeated approvals.
4. History shows request, decision, outcome if observed, and any missing evidence.

**Pass:** Live paired app/daemon test reproduces correct attribution and refuses the out-of-scope operation. A UI-only mock is not sufficient.

### Journey C - Synthetic relationship pilot
Create a standalone synthetic society with two or more synthetic member profiles, declared interests/skills and a witnessed contribution. Hub supplies membership/introduction/consent surfaces; Hestia supplies member identity, controls and receipts. A proposed introduction must not be represented as an accepted relationship, and a self-asserted skill must not be represented as earned reputation.

**Pass:** No live platform or member data is required, and the demo is resettable and inspectable. Matching logic may be an external toy module; it is not claimed to be a Web4 feature.

## 6. Delivery slices

| Phase | Scope | Exit evidence |
|---|---|---|
| P0 - Evidence inventory | Map each journey to existing daemon/app API, UI source, tests and outstanding gaps | Maintained capability matrix with explicit shipped / source-only / missing state |
| P1 - First-run spine | Installer, compatibility check, safe identity creation, Me/Communities/Activity path | Fresh-device recording and CI-tested app/daemon pair |
| P2 - Real governance | Agent connect, scoped authorization, escalation, outcomes, evidence views | Automated and human-verified governed-action journey |
| P3 - Hub membership | Inspect/join/leave, disclosure review and membership receipts | End-to-end browser-to-app-to-Hub tests against live runtimes |
| P4 - Pilot and polish | Synthetic relationship demo, accessibility, recovery and errors | Independent nondeveloper participant completes all journeys |

### Measures, not promises
Track unaided first-run completion, time to first useful action, number of unexplained prompts, decision correctness, data-disclosure surprises, and verifiable receipts per consequential action. Establish baselines before setting target thresholds.

## 7. Boundaries and dependencies

- **Hestia owns** personal app, local key custody, identity presentation, connection to agents, policy UX and local approvals.
- **Hub owns** the society's public website, membership admission, relationship/introduction state and its own law.
- **Web4 owns** shared canonical identity, trust, witnessing, law and provenance primitives; do not duplicate them in UI.
- **COWONDER** is a potential external design partner, not a committed integration. Its independent matching/product/member data stay outside this PRD; synthetic-only exploration is acceptable without production access.
- Verify privacy controls and cross-process security at the actual API boundary. A friendly UI is not a security mechanism.
- Hardbound is optional higher-assurance proprietary technology, not necessary to demonstrate a basic community relationship.

## 8. Explicit non-goals

No forced account on a central Web4 service; no redesign of Hestia law semantics as a UI shortcut; no universal identity/reputation score; no presumption of native iOS support until shipped; no claim that federated cross-Hub discovery is complete; no commercialization or joint-IP commitment.

## 9. Open decisions

1. Which platform/release pair becomes the first fully supported reference?
2. How will browser-first members create/hold identity without forcing a specific personal app?
3. Which flows require a locally resident Hestia instance versus optional passkey/other client?
4. How are identity recovery, consent withdrawal and practical erasure communicated alongside immutable witnessed evidence?
5. Which existing dashboard functions should be ported, shared or retired to avoid two competing operator UIs?

**Release gate:** Do not describe the app as turnkey until the verified clean-install and full governed-action paths pass on downloadable builds.
