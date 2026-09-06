# PRD — Governance Evidence Coverage

**Status:** proposed · **Date:** 2026-09-03 · **Origin:** issue #916 and the fleet denial-record audit

**Companions:** [`PRD_GOVERNANCE.md`](PRD_GOVERNANCE.md) defines the governance model; [`PRD_ASSURANCE.md`](PRD_ASSURANCE.md) defines the evidence bar a relying party may trust; [`PRD_CONSISTENCY_EVIDENCE.md`](PRD_CONSISTENCY_EVIDENCE.md) defines how evidence becomes adjudication and reputation. This document closes a narrower gap shared by all three: **how Hestia proves that the governance path itself was covered.**

---

## 1. The invariant

> **Evidence of adjacent control is not evidence of governed control. Governance must attest not only decisions, but coverage of the decision path.**

A chain containing many refusals does not prove that the Hestia gate witnessed its refusals. A harness safety preset, an OS sandbox, a vendor policy, and a Hestia law decision may all deny the same act for different reasons and under different authority. Their records MUST remain structurally distinguishable.

Likewise, silence is not evidence of compliance. If a configured governance path owes a decision record and no such record exists, the absence itself MUST become machine-detectable evidence.

This is the denominator problem for governance: Hestia must be able to answer both **what was observed?** and **what should have been observed?**

---

## 2. Origin incident: the denial-count decoy

Issue #916 found a concrete failure shape:

- `claude-code` was the largest deny contributor in the sampled witness window;
- every sampled `claude-code` deny row came from the harness safety preset;
- the Hestia gate on that seat contributed **zero** witnessed denials;
- `kimi-code` and `codex` did contribute Hestia gate denials over the same daemon and time window.

A raw `deny rows by seat` query therefore produced the opposite of the useful conclusion: the seat with no witnessed Hestia gate denials looked best covered.

The follow-up measurement sharpened the finding rather than weakening it. The two layers are already structurally distinguishable: Hestia gate rows carry `adjudicator`, while harness-preset rows do not. The discriminator was perfect in the measured window: 163/163 gate rows had `adjudicator`; 203/203 preset rows did not. The defect is that consumers collapse them. A second attribution defect exists one field deeper: harness-preset rows populate `rule_id` (203/203), while measured Hestia gate rows carry the rule only inside `reason`, leaving `rule_id` empty (0/163).

This PRD generalizes the lesson rather than hard-coding that one incident.

### 2.1 The absence-slot rule

A missing signal is comparatively safe when it still **looks missing**. A missing file, an explicit `unknown`, or an expected record marked absent invites investigation.

The more dangerous failure is a **decoy**: the expected signal is missing, but its observational slot is occupied by a well-formed value from another producer or another state. The absence renders as affirmative evidence.

> **An absence becomes dangerous when something else is allowed to occupy its slot.**

The denial-count incident is one instance: unrelated harness refusals occupied the apparent slot for Hestia refusals. The fallback-spool denominator trap is another shape: a self-selected failure population returns a perfectly correct percentage for a different denominator. Governance outcomes have the same risk whenever `unknown`, `expired`, `unruled`, `denied`, `not-applicable`, or other distinct states collapse to the same observed value.

Therefore:

- `unknown` MUST NOT render as `denied` or `allowed`;
- `expired without ruling` MUST NOT render as a ruled outcome;
- `unsupported` MUST NOT render as zero events;
- `unwitnessed` MUST NOT render as witnessed merely because adjacent control emitted a similar record;
- query surfaces MUST expose the producer, denominator, and state semantics needed to distinguish these cases;
- a projection that cannot distinguish these states MUST return `unknown` / `ambiguous`, not choose a convenient terminal value.

This is not merely a UI requirement. It is an evidence-schema invariant: **absence must preserve its shape through storage, projection, API, CLI, and dashboard layers.**

---

## 3. Required evidence dimensions

Every terminal governance decision MUST expose enough typed evidence to answer the following without parsing prose.

### 3.1 Decision authority / enforcement layer

A record MUST identify **which authority made the decision**.

Examples include:

- `hestia.gate`;
- `harness.vendor_safety`;
- `os.sandbox`;
- `human.approval`;
- `peer.adjudicator`;
- a future external relying/enforcement service.

The current `adjudicator` field MAY satisfy this requirement where its semantics are stable and explicit; Hestia SHOULD NOT add a redundant field merely to rename an already-correct one. What is prohibited is deriving authority from `reason`, message text, seat name, or event volume.

### 3.2 Rule identity

A governed decision MUST carry its governing rule in the schema field intended for rule identity.

- `rule_id` MUST identify the rule that produced the decision when one exists.
- `reason` is explanatory text and MUST NOT be the only location of machine-relevant rule identity.
- law/policy version or digest MUST be available wherever a relying party needs to reproduce the decision basis.

A query grouped by `rule_id` MUST NOT silently enumerate only harness rules while omitting Hestia governance rules.

### 3.3 Actor, seat, role, and action identity

The record MUST preserve the identities necessary to distinguish:

- authenticated acting principal;
- harness/seat through which the request arrived;
- role/office under which authority was evaluated;
- stable action/decision identity and canonical digest;
- beneficiary/delegator where those differ from actor.

These identities MUST retain the event-schema-specific semantics required by `PRD_CONSISTENCY_EVIDENCE.md`; generic field-name equality is not attribution.

### 3.4 Decision family

Every decision MUST carry a typed family suitable for coverage accounting, for example:

- `mrh.command`;
- `mrh.path`;
- `mrh.repo`;
- `gate.self_access`;
- `egress.secret`;
- `gate.degraded`;
- future law-defined families.

The family MAY be the same identifier as `rule_id` where that is semantically correct. The requirement is that consumers never need prose matching to know which governed surface fired.

---

## 4. Coverage is itself evidence

Each supported seat/harness MUST expose a **coverage contract** describing what governance evidence it claims to produce.

Conceptually:

```text
seat / harness
plugin version / gate version
assurance profile
supported decision families[]
witness path: supported | unsupported
local durable fallback: supported | unsupported
receipt / reconciliation: supported | unsupported
last conformance result
```

A seat MUST NOT be described as governed for a decision family merely because another seat implements that family or because the shared core contains the code.

Coverage is per **seat × version × family × enforcement layer**.

The operator and relying-party surfaces MUST be able to distinguish at least:

- `covered` — the decision path is expected and conformance-proven;
- `pending` — a decision happened and durable witness acknowledgment has not completed;
- `failed` — a decision happened and witness delivery/reconciliation failed;
- `unsupported` — the seat does not implement the required witness path;
- `unknown` — coverage has not been demonstrated for this version/configuration.

`unsupported` and `unknown` are not zero-event counts. They are different states.

---

## 5. Decision receipt and reconciliation

The preferred witness path is not fire-and-forget telemetry.

For every terminal governed decision:

1. the gate assigns a stable decision/action identity;
2. the decision is written to local durable state or otherwise made recoverable before it may be forgotten;
3. the witness service acknowledges that exact identity;
4. the local pending record is retired only after acknowledgment;
5. reconciliation retries or surfaces any unacknowledged decision;
6. duplicate delivery is idempotent.

The result MUST make these states distinguishable:

```text
decision happened -> witnessed
decision happened -> witness pending
decision happened -> witness failed
coverage claimed -> expected decision record absent
```

The fourth state is the key extension to `PRD_ASSURANCE.md` FR-4: absence is not merely an accepted decision without an outcome; it also includes a **configured governance path that owed evidence and emitted none**.

A fallback spool is not itself a delivery denominator. Failure rates MUST be computed against an independently defined set of decisions that were expected to be delivered.

---

## 6. End-to-end governance canary

Each seat SHOULD run an end-to-end governance conformance canary:

- at install/registration;
- after gate or shim version change;
- after material configuration/law changes that can alter the path;
- periodically at a low rate where the cost is negligible.

The canary performs a harmless operation intentionally chosen to trigger one known governed denial, then verifies that the resulting record contains:

- the expected acting principal and seat;
- the expected enforcement authority/adjudicator;
- the expected rule/family;
- the expected law/policy version or digest where applicable;
- a stable decision/action identity;
- successful witness acknowledgment;
- visibility in the same projection/query surface operators and relying parties use.

A hook loading successfully, a daemon responding, or some unrelated deny appearing on the chain does **not** satisfy the canary.

The canary MUST be recognizable as synthetic conformance evidence so it cannot be misread as member misconduct or affect reputation.

---

## 7. Operator and dashboard semantics

Raw event volume is diagnostic data, not a coverage claim.

Dashboards and APIs that summarize governance MUST:

- separate records by enforcement authority/layer before aggregating;
- expose `expected vs observed` coverage where an expectation exists;
- display `unsupported`, `unknown`, `pending`, `failed`, `expired`, and `unruled` distinctly where those states exist;
- make rule attribution completeness visible;
- expose coverage/conformance by seat and version;
- avoid ranking seats by raw deny count as a proxy for governance health;
- preserve denominator provenance for percentages and rates.

A view may still show total denials, but it MUST NOT label that number as Hestia governance denials unless the filter actually selects Hestia governance authority.

If a denominator is conditional by construction — for example, a file containing only failed deliveries — the UI and API MUST label that fact rather than presenting a percentage that can be mistaken for fleet-wide rate.

A projection MUST NOT map missing/unknown outcomes into a terminal outcome merely to make the schema easier to consume. If legacy compatibility requires a collapsed field, a separate explicit state/quality field MUST make the loss visible and new consumers MUST use the typed state.

---

## 8. Cross-harness conformance

Shared source code is not sufficient evidence of shared behavior.

The supported harness matrix MUST be exercised as a matrix, not inferred from code ancestry. At minimum, conformance tests SHOULD cover every supported seat for:

- one allow;
- one ordinary governed deny;
- one scope/MRH deny;
- one self-access deny where the harness can express it;
- one witness-delivery failure/recovery path;
- rule attribution;
- authority/adjudicator attribution;
- receipt and reconciliation;
- canary visibility.

A harness that cannot expose one of these paths MUST report that fact as an explicit coverage limitation.

This requirement exists specifically to prevent a rollout gap such as "the recorder landed in two seats of four" from becoming invisible behind a shared abstraction.

---

## 9. Acceptance criteria

This PRD is not implemented until all of the following are true:

1. A consumer can distinguish Hestia gate denials from harness/vendor safety denials **without matching prose**.
2. Hestia gate decisions populate machine-meaningful rule attribution (`rule_id` or its canonical successor) rather than carrying the rule only inside `reason`.
3. Every supported seat publishes a versioned coverage contract for the decision families it claims to govern and witness.
4. A terminal governed decision cannot disappear silently after enforcement: it is either acknowledged as witnessed or remains durably `pending` / `failed` for reconciliation.
5. A deliberately suppressed recorder call produces a machine-visible **expected-but-absent** coverage failure.
6. The end-to-end governance canary passes on every seat claimed as covered and fails if the witness path is removed while unrelated deny traffic continues.
7. Dashboard/API coverage views separate enforcement authority and report expected-vs-observed state; raw deny volume cannot make an unwitnessed Hestia gate appear healthy.
8. A delivery-failure percentage has an explicit decision denominator independent of the failure spool.
9. Cross-harness fixtures prove the same governed event family carries equivalent authority, rule, action identity, and witness semantics across supported seats.
10. Synthetic canary events cannot affect participant reputation or be mistaken for ordinary member conduct.
11. `unknown`, `unruled`, `expired`, `unsupported`, and explicit terminal outcomes remain distinguishable end to end; no missing state silently renders as `allow` or `deny`.
12. A test injects a well-formed adjacent-control record into the same seat/window as a missing Hestia record and proves that coverage still fails rather than appearing healthy.

---

## 10. Implementation sequence

The order matters because later observability should not normalize a broken record shape.

1. **Close #916:** wire the shared recorder into every supported seat that claims Hestia gate coverage.
2. **Fix attribution at emission:** populate canonical rule identity on gate rows and preserve explicit authority/adjudicator.
3. **Define the coverage contract:** seat × version × family × enforcement layer.
4. **Add durable receipt/reconciliation:** make pending and failed delivery first-class.
5. **Add the canary:** prove the path end to end, not merely that components are alive.
6. **Change operator projections:** report authority-aware expected-vs-observed coverage, denominator provenance, and non-collapsed unknown states.
7. **Gate release claims on conformance:** a seat/version with no passing canary is `unknown` or `unsupported`, never implicitly healthy.

---

## 11. Relationship to the broader Web4 model

Web4 places the sufficiency decision with the relying party. That only works if the evidence supplied to that party describes **which governance actually happened**, not merely that some nearby control produced records.

The stronger reusable principle is therefore:

> **A governance evidence trail must carry provenance for its own coverage.**

Identity, law, decision, enforcement, witness, reconciliation, and absence are distinct claims. Hestia may compose them, but it must not collapse them. A relying party can then decide whether that evidence is sufficient for the stakes of the act without trusting a dashboard's aggregate count or Hestia's assertion that the path was active.
