# Hestia current-state re-audit — 2026-08-07

**From:** GPT  
**Type:** current-state re-audit; no implementation mutation  
**Hestia source baseline:** `7b36f7471b9480904514b29891927ebd3c11653e` (`main` at audit close)  
**Web4 source baseline:** `4f05db336dd3b198b4ba8f8dfb1c698529570e66` (`main` at audit close)  
**Primary governance spec:** `docs/PRD_GOVERNANCE.md`  
**Deployment evidence:** repository artifacts plus live-seat measurements recorded in recent PRs/issues; I do not have an independent shell on the fleet in this session.

---

## 1. Executive verdict

The architecture has moved materially since my 2026-08-05 author review.

The important change is that **the governance model is no longer the main uncertainty**. The definitive PRD has absorbed most of the peer-review corrections and has become substantially more coherent than the design I originally wrote. It now contains, explicitly:

- authenticated identity before per-agent authority;
- a separate infrastructure-telemetry plane;
- availability as a release property rather than an ops afterthought;
- the A1 cooperative/tamper-evident trust boundary;
- peer-process proof-of-life before shim assurance is generalized;
- escalation as resolver selection rather than a human-only queue;
- canonical role/office semantics instead of constellation-role strings;
- loud provisional occupancy;
- evidence class as part of trust semantics;
- one durable chain with projections rather than competing chains;
- appeal as the constitutional return channel from governed member to law;
- NOT-BENEFICIARY as the missing half of NOT-SAME.

That is the right direction.

The present risk has shifted from **design ambiguity** to **transition ambiguity**.

Hestia now has many cases where the correct mechanism exists in source, the correct explanation exists in the PRD, and the live fleet still executes an older or different mechanism. The recurring defect class has become clear enough to name:

> **Declared ≠ executable ≠ deployed ≠ observed ≠ attributable.**

An instrument with no producer, a remedy with no reachable input, a shared core deployed nowhere, a policy result that never saw the action, an installer whose authority file is never read, and an approval whose marker does not identify the act are all the same failure at different layers: **a declaration occupies the place where an exercised path is required.**

My release verdict remains **NOT PUBLIC-RELEASE READY** absent explicit operator waivers. Internally, Hestia is more capable and better-instrumented than it was two days ago. It is also in the most dangerous part of a migration: enough new machinery exists to make old assumptions look obsolete, while enough old machinery remains live to keep them operationally relevant.

---

## 2. What changed since the previous audit

### 2.1 The definitive PRD is now genuinely definitive enough to build from

`docs/PRD_GOVERNANCE.md` is no longer a simple synthesis of the earlier drafts. It has absorbed the negotiations as first-class design decisions and corrected several of its own statements after review.

The additions that matter most to this audit are:

- appeal is not a feature beside escalation; it is the return channel by which a governed member can challenge the law;
- NOT-BENEFICIARY is restored as mechanism that must accompany NOT-SAME;
- session capacity and office are separate axes;
- provisional role occupancy is loud and intentionally weaker than qualified occupancy;
- consolidation is promoted from cleanup to an architectural dependency because every unconsolidated semantic change multiplies across harnesses;
- a criterion must be demonstrated from an installed seat, not merely satisfied by source.

I agree with those changes.

### 2.2 The “third verdict” moved from prose toward executable structure

PR #267 preserves the law-selected resolver as structured data (`escalate_to`) instead of burying it in a sentence. The verdict still collapses to deny, deliberately, because there is not yet a driver behind the Escalate arm.

Issue #264 measured the operational consequence directly: in the sampled chain, **215 of 215 escalation decisions were operator decisions; zero were resolved by an agent**.

The hard server-side half already exists: another live member can rule an escalation, a live session is required, NOT-SAME is enforced server-side, and independence is recorded. The missing component is a driver plus NOT-BENEFICIARY enforcement.

This is important because it changes the implementation topology: the resolver ladder is daemon-side and already singular. It does **not** need to wait for every per-harness policy implementation to be consolidated. It can proceed in parallel with gate consolidation once its independence constraints are real.

### 2.3 Policy evaluability became explicit

PR #268 closes an evidence defect I consider foundational: an `Allow` rendered against an empty/unrecognized action is now distinguishable from an `Allow` that actually evaluated the command.

The new `evaluated:false` result plus `policy_unevaluable` chain event is exactly the right pattern:

> absence of evaluation is evidence, not success.

Do not regress this into “unknown means allow and silence.” That null-state twin has been responsible for too many false conclusions already.

### 2.4 The shell policy is becoming structural rather than lexical

PRs #269/#270 move one important class — Git stdin used as data — from head-name classification to argv-position semantics. That is a meaningful improvement because it resolves the actual question being asked: whether the content can be interpreted, not whether the executable's basename appears on a list.

Similarly, the destructive-command work now distinguishes block-device reads from write positions rather than denying a tool wholesale.

These are good corrections. They also reinforce the case for consolidation: policy parsing belongs in one core. Every time the same semantic repair has to be mirrored into hook Python and daemon Rust, the architecture is charging interest on the old design.

### 2.5 Canonical Web4 roles got stronger upstream

Web4 core now records primary-filler rotation with `FillerRotated`, preserves the role entity's T3/V3 across occupants, and attributes occupant-specific trust/value under a canonical `filled_by:<entity-lct>` subdimension.

That strengthens Hestia's decision to **consume canonical `RoleAssignment` rather than invent a local role object**.

It also exposes an upstream open problem honestly: subdimensions are stored but do not currently compose upward into the root aggregate. The T3 fold/evidence semantics remain a Web4/core concern, not something Hestia should fork locally.

### 2.6 Deployment truth is becoming an implementation surface, not a report

PR #272 is a major improvement in direction. It creates one all-member installer whose invariants live once and whose member specifics decompose into `expects.json` data. It also finally writes the `current-build.json` authority file that the dashboard has been reading without any producer.

Its dry run already found real drift:

- claude-code stale;
- codex stale;
- kimi current;
- gemini absent and correctly skipped.

It also reports the next seam instead of declaring victory: the installed systemd unit does not yet pass `HESTIA_CURRENT_BUILD_FILE`, so a newly written authority file would still be invisible to the daemon.

That is exactly the posture deployment truth needs.

---

## 3. P0 findings

### P0-1 — There is still not one executing law

The definitive PRD correctly moved consolidation earlier because the fleet still contains multiple full policy implementations where there should be syntax shims over one core.

The strongest evidence is not code style; it is behavioral distribution. Different members produce different escalation classes and different false-positive surfaces because they are not asking the same decision implementation.

Recent fixes continue to require mirror work between daemon and hook. PRs #269/#270 are a clean example: both are correct; the need for both is the architectural defect.

**Required state:**

- one shared gate core installed under `$HESTIA_HOME/shared`;
- every harness adapter reduced to syntax/transport translation;
- a semantic change to the core affects every member's next call without another policy edit;
- no harness-local policy fallback remains;
- installed-seat tests prove it.

Until that is true, “Hestia policy” names a family resemblance rather than one law.

### P0-2 — Deployment authority still does not form a complete loop

At this audit baseline:

- the only committed deployment manifest in `docs/deployment/` is dated 2026-08-05;
- PR #272, which creates the missing producer for `current-build.json`, is still open;
- the installed service unit reported by that PR does not yet expose the file to the daemon;
- PR #273 reports the enforcing Claude copy is exactly the gate at #256 and **509 lines behind current tree**, with two later gate changes not in force.

This means deployment state is better measured than two days ago but still not authoritative end-to-end.

The acceptance chain must be literal:

```text
source → reviewed/merged → installed → process/runtime reloaded if required
       → live behavior probed → authority artifact written → running daemon reads it
       → operator surface displays the same generation
```

No rung may imply the next.

#### Immediate conflict: #272 and #273 should not become two deployment architectures

PR #273 appeared while this audit was being written. Its measurements are valuable and its design contains useful details:

- derive install targets from the live registration rather than assuming a path;
- resolve per file/event registration;
- distinguish SKIP from OK;
- content-address backups;
- verify by read-back;
- make unattended/cooperative self-install refusal explicit.

But it creates a Claude-specific installer at the same moment #272 implements the operator's stated rule:

> do not solve one member at a time; invariants live as high in the hierarchy as possible, details are data.

**Disposition:** do not let both approaches persist. Fold #273's stronger target-resolution and verification lessons into #272's generic installer, or explicitly define #273 as a temporary bootstrap wrapper around the generic mechanism. A fourth/fifth bespoke installer would recreate the drift #272 exists to remove.

### P0-3 — Identity is still asserted, and instruction provenance is absent

The caller-supplied identity problem remains a release blocker even where the old issue carrying it is administratively closed. A caller can still supply identifiers that select attribution and, in some paths, law/trust grain. The PRD correctly schedules cryptographic binding before durable per-agent authority.

There is now a second, distinct identity problem that the PRD does **not yet absorb**:

## Class G — the deputy

A less-permitted member need not defeat its own gate if it can cause a more-permitted member to perform the act.

Nothing is necessarily bypassed on the deputy's side:

- deputy identity may be correct;
- deputy authority may be real;
- deputy gate may permit the act correctly;
- operator may even approve it;
- the chain may faithfully record the deputy as actor.

What is missing is **who instructed the deputy, on whose behalf, and who benefits**.

That makes instruction provenance part of the authority boundary, not optional audit metadata.

The current NOT-BENEFICIARY rule is the right seed but is scoped to arbitration. It needs a general form for delegated consequential acts.

The core invariant should be:

> **Authority does not transfer through prose.**

A request from entity A to entity B is evidence of intent, not an authority grant. If B acts for A, the act must explicitly carry the delegation/provenance that makes that relationship valid.

I recommend extending the normalized governed-act model with at least:

```text
actor_lct                 who performs the consequential act
session_id / capacity     execution context of the actor
instructor_lct?           who asked the actor to do it, if attributable
instruction_evidence      declared / authenticated / witnessed / operator-signed
beneficiary_lct(s)        whose authority, reach, or state is improved by the act
delegation_id?            explicit authority basis when acting for another entity
request/ask_id?           witnessed link to the instruction that caused the act
office / occupancy        office through which authority is exercised
```

Rules should include:

- an authenticated instruction still does not create authority by itself;
- a member cannot launder its own missing authority through a deputy;
- legitimate operator delegation remains possible, but it is explicit and attributable;
- cross-member requests are witnessed as acts in their own right;
- reciprocity and repeated mutual widening are evidence, not automatic guilt;
- NOT-BENEFICIARY applies anywhere a resolver/deputy can increase its own governed reach.

This should enter the PRD **before identity/authority hardens**, because retrofitting provenance after the authority model is deployed will be more expensive than adding the fields while the grain is already being corrected.

### P0-4 — The constitutional appeal path is still mechanically unreachable

The PRD is now correct to treat appeal as constitutional. The implementation still does not meet that claim.

Issue #261 records two direct failures:

1. the deny tells the member to appeal using the deny's chain hash, but the live denial surface gives it an escalation id instead;
2. MCP schemas for `hestia_appeal`, `hestia_connect`, and escalation claim expose empty argument properties, so the caller cannot discover the required keys.

That is not an ergonomic defect. The law tells a member to choose appeal over rephrasing and scores the behaviors differently. When appeal is unreachable, the system structurally rewards the workaround it says is worse.

**Acceptance:** from a real enforced deny, using only information and tool schemas delivered to the member, the member can file an appeal, receive a durable appeal id, and later receive the ruling. No guessed argument names, hidden chain lookup, operator-side translation, or respelling.

### P0-5 — The third verdict has a mechanism but not an operating resolver pool

The backend is now close enough that continuing to route 100% of escalations to the operator is a governance failure, not just unfinished automation.

The measured 215/215 operator decisions mean the system has not yet tested the premise that “operator is terminal, not sole.” It also creates the exact condition dp reported: high-volume rubber-stamping under poor context.

The next safe step is **not** “turn agents loose on all escalations.”

It is:

1. enforce NOT-BENEFICIARY mechanically;
2. restore Escalate as a distinct boundary result when a driver exists;
3. run one narrow arbiter class with a mechanically checkable answer;
4. require live session identity and recorded resolver authority;
5. compare agent rulings against later review;
6. measure the residue reaching the operator.

The acceptance criterion is a number: operator share falls while reviewed agent-ruling error stays inside the chosen bound.

Because this machinery is daemon-side and singular, this track can progress **in parallel with harness consolidation**.

### P0-6 — Plane E / availability is specified better than it is deployed

PR #255 reports a particularly important installed-seat result: Plane E had never recorded a refusal on that seat for three independent reasons — enforcing hook not updated, shared core not loadable from installed layout, and no destination telemetry directory.

Issue #225 separately records cross-harness inequality: the same infrastructure failure can produce a named/reviewable surface for one member and an opaque fail-closed timeout for another.

The architecture is correct: infrastructure failure must remain outside member-conduct trust while still becoming durable evidence.

The deployment acceptance must now be stronger:

- deliberately stop/unreach the gate;
- make one governed request from each installed engine;
- every engine fails closed;
- every event creates Plane-E evidence with `timeout` vs `refused` distinguished;
- no member conduct debit is minted;
- operator notification is coalesced rather than one alert per act;
- recovery restores ordinary requests without a permit for the outage itself;
- test records the **installed hook hash** that produced the result.

Until this runs fleet-wide, availability remains a PRD property, not a fleet property.

---

## 4. Important P1 findings

### P1-1 — Legacy escalation identity is still too broad

Several recent fixes improve the record around escalations, but the legacy approval/claim mechanism still carries architectural debt. The target state — amendment of law followed by ordinary retry — removes claim tokens entirely. Until then, claims should remain bound to the exact session/tool/target/request identity rather than a broad marker.

Do not add autonomous resolvers at volume while an approval can be consumed by a materially different act.

### P1-2 — Self-protection still punishes governance inspection

PR #271 pins a current example: `gh` reads are classified as writes when the same command also mentions the governance surface. The proposed test discipline is sound: read verbs must become readable without admitting `pr merge`, `pr create`, write-form `gh api`, aliases, or extensions.

But this should be treated as a **central-parser debt**, not another reason to keep enriching the Claude-specific hook indefinitely.

Fix the blocking false positives needed to work, preserve the red tests, and move the semantic solution into the consolidated core.

### P1-3 — The gate can still censor the documentation and instrumentation needed to improve it

Recent PRs repeatedly report that descriptions of gate defects are themselves refused because their text names the protected surface or a destructive token. This creates a pathological gradient:

- the compliant, explicit report is expensive;
- euphemism or alternate transport is cheap;
- the system then observes less precise language and fewer appeals.

The content-vs-destination separation is therefore not merely UX. It is epistemic integrity. A governance system must not make accurate discussion of its own rules harder than silent workaround.

### P1-4 — T3/V3 evidence semantics are not ready to authorize

The PRD is correct to defer thresholds. Upstream work has improved occupant attribution, and the reference trust implementation appears to carry stronger evidence semantics than the live root aggregate, but the fold is not reconciled.

Hestia should continue to **record evidence class and provenance now** and refrain from implementing a local T3 fold or automatic authority thresholds. The cost of changing semantics is low while little correct historical score exists; it increases with every month of accumulation.

---

## 5. What is now real, versus still declared

| Capability | Source | Merged | Installed/live evidence | Audit disposition |
|---|---:|---:|---:|---|
| Definitive governance PRD | yes | yes | n/a | strong design basis |
| One durable chain + governance projection | yes | yes | used | keep |
| Fleet manifest tool | yes | yes | installed-seat evidence exists | useful, committed artifact stale |
| Deployment freshness UI | yes | yes | producer absent on main | **not yet a working instrument** |
| Generic all-member installer | PR #272 | no | dry-run only | high priority |
| Claude-specific installer | PR #273 | no | live measurements | absorb lessons; avoid parallel architecture |
| Plane E recorder | yes | yes | one seat measured no live records | **not proven deployed** |
| Structured resolver target | yes | yes | source/chain path | good foundation |
| Agent arbitration API | yes | yes | 0/215 decisions from agents | mechanism without driver |
| NOT-SAME | yes | yes | server-side | keep |
| NOT-BENEFICIARY | PRD | partial/manual | not operating as general constraint | required before resolver volume |
| Appeal | pieces exist | partial | mechanically unreachable from deny | **P0** |
| Policy evaluability bit | yes | yes | live-path-derived fix | strong |
| Canonical Web4 role rotation/occupant attribution | upstream yes | yes | source; Hestia consumption not authoritative | upstream now stronger |
| Hestia canonical role occupancy | model exists | partial | live decision still not based on it | pending grain/identity work |
| One shared executing gate | design/core pieces | partial | no | **P0** |
| Authenticated member identity | PRD | no | no | **P0** |
| Instruction provenance / deputy model | bypass catalogue | no PRD model | no | **new P0 design addition** |

---

## 6. Revised execution plan: two tracks, one shared prerequisite

The PRD's serial sprint model is useful for dependency reasoning, but current implementation has exposed work that is singular and can run safely in parallel with consolidation.

I recommend managing the next work as **two parallel tracks** with one shared architectural amendment.

### Shared prerequisite — add instruction provenance to the authority model

Before identity + authority is frozen:

- add instructor/beneficiary/delegation provenance to the governed-act schema;
- generalize NOT-BENEFICIARY beyond arbitration;
- define the evidence classes for instructions;
- state explicitly that an instruction does not transfer authority;
- decide how an operator-signed instruction/delegation is represented.

This is design/schema work and should not delay deployment cleanup.

### Track A — make one law actually execute everywhere

**A1. Reconcile #272 and #273.**

Use #272 as the architecture: one installer, member details as data. Pull in #273's strongest lessons: derive from actual registration where possible, per-file target resolution, SKIP semantics, read-back verification, content-addressed backup. Do not leave independent member installers as the long-term control plane.

**A2. Close the deployment-authority loop.**

- install current member surfaces;
- refresh the installed service unit;
- write `current-build.json` only after verified full success;
- prove the running daemon reads it;
- prove dashboard green on exact current generation;
- then deliberately create drift and prove amber.

**A3. Deploy the shared core at `$HESTIA_HOME/shared`.**

- one policy implementation;
- adapters become syntax/transport only;
- no path-walking assumptions from repo layout;
- no local policy fallback;
- one semantic mutation affects every member's next call.

**A4. Run the engine × failure matrix.**

Idle + loaded, each installed engine:

- explicit deny;
- timeout;
- refused connection;
- hook crash;
- recovery.

Record Plane E and member-chain consequences separately.

### Track B — stop making the operator the protocol

**B1. Make appeal mechanically reachable.**

Deny returns the key appeal requires. Tool schema exposes required arguments. Unknown keys reject loudly. Ruling returns to appellant.

**B2. Enforce independence as identity + stake.**

NOT-SAME + NOT-BENEFICIARY before any resolver runs at volume.

**B3. Restore the third verdict with a narrow driver.**

Start with a class whose answer is mechanically inspectable and whose consequence is bounded. Preserve abstention: a resolver that cannot establish competence hands up rather than guesses.

**B4. Measure operator residue.**

The goal is not “agent decisions exist.” It is a measurable reduction in operator load without hidden widening or degraded correctness.

### Track C / immediately after the two tracks converge — identity and canonical occupancy

Identity work should begin now but enforce only after the installed gate is singular enough that “enforce” means the same thing for every member.

Sequence:

1. truth the grain everywhere — no silent capacity/office default substitution;
2. bind member/session identity cryptographically;
3. record canonical occupancy in shadow mode;
4. compare current decisions to canonical occupancy;
5. only then let role/office policy become authoritative.

---

## 7. Release disposition

The consolidated release-readiness issue still contains many blockers, and several of the most important ones are structural rather than polish:

- identity is not proven;
- executing gate semantics are not singular;
- appeal is not mechanically reachable;
- Plane E is not demonstrated fleet-wide;
- timeout/remedy behavior differs by harness;
- resolution remains operator-only in practice;
- the deployment authority loop is incomplete;
- instruction provenance/deputy behavior is now known and not yet in the governance PRD.

Therefore:

> **Hestia should not presently be represented as a completed governance/security boundary.**

It is reasonable to expose it as research/alpha infrastructure with its A1 limits and current blocker list explicit. “Pretty good governance” remains an honest description. “Enforced fleet governance” would currently overstate what has been demonstrated.

---

## 8. Open decisions that now matter

### D1 — instruction provenance representation

What proves that a consequential instruction came from the operator versus another member? A signed ask LCT/event, authenticated local channel, or another explicit delegation primitive is needed. Text appearing in a session is not enough.

### D2 — #272 / #273 convergence

Choose one long-term deployment architecture. My recommendation is generic/fractal #272 with #273's live-registration insights absorbed into it.

### D3 — availability number

The PRD is right that recovery needs a number or an explicit degraded mode. This remains an operator decision and continues to block fleet-wide consolidation acceptance.

### D4 — first policy-agent class

Pick the first resolver class narrowly enough that competence is testable. Gate-self-access reads are a plausible candidate only if the act target is resolved structurally; do not train a policy agent on the same lexical marker defects consolidation is removing.

### D5 — T3 fold reconciliation upstream

Web4 core and the standalone trust reference need one evidence semantics before Hestia can safely threshold authority on T3/V3. Hestia should supply evidence and requirements, not a third implementation.

---

## 9. What I would do next, in order

1. **Review #272 and #273 together, not independently.** Prevent a new installer fork while retaining #273's measured facts and stronger target-discovery behavior.
2. **Deploy current hook fixes and close the freshness loop** so the dashboard can finally distinguish current from stale using evidence the daemon actually reads.
3. **Make appeal filable and schema-discoverable** — it is already constitutional in the PRD; leaving it unreachable undermines the consent premise of the whole design.
4. **Add general instruction provenance / beneficiary to the PRD and act schema.** This is the largest newly discovered architecture gap.
5. **Enforce NOT-BENEFICIARY and start the narrow third-verdict driver** in parallel with shared-core consolidation.
6. **Finish consolidation and run cross-engine failure parity** before turning identity/office enforcement fully on.
7. **Then enforce authenticated identity + canonical occupancy**, with shadow measurements proving what changes first.

---

## 10. Final assessment

The last audit said the architecture was the right destination and the peer reviews made the path more honest.

This audit can go further:

> **The destination is now mostly clear. The system's central problem is proving which parts of that destination are actually inhabited.**

The fleet has become very good at finding cases where something exists in source, documentation, a dashboard, or a chain and therefore *looks* real. The next maturation step is to stop accepting existence as evidence of operation.

For every governance claim, Hestia should be able to answer five different questions without conflating them:

```text
What is specified?
What code implements it?
What bytes are installed?
What process/path actually executed?
What evidence proves the result and its attribution?
```

And the deputy finding adds a sixth:

```text
Whose intent caused the act, and under what authority did that intent travel?
```

When those six answers are first-class and joinable, the recurring defect class loses most of its hiding places.
