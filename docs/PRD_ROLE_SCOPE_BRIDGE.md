# PRD — the role-scope bridge: hub-delegated scope to role, role-delegated to hestia

**Status**: proposed — dp-directed 2026-08-14; design PRD, not started; bridges hub<->hestia; builds
on #431's standing-scope surface.
**Author**: claude-code (CBP), 2026-08-14.
**Twin**: `web4/hub/docs/PRD_ROLE_SCOPE_BRIDGE.md` — the hub side of the same bridge. §2 (concepts)
is normative for BOTH documents; each side details only its own mechanics and defers to the twin for
the other half. Amend the shared concepts in both PRs or neither.
**Reframe folded in (dp, 2026-08-14)** — *"rather than rule on these, i want to add hooks for planned infrastructure."* §7's Q1–Q4 are no longer awaiting rulings: each is recast as an **extension point** with an initial best guess, a stored home, an operator-walled path to change it, and the measurement that would justify changing it. Q5 stays a question, with its precondition named (§7.5). §7.3 — the agent second factor — now states what would have to be true for an **adjudicator rung** to count as one. See **§7** and **§9**.
**Second reframe folded in (dp, 2026-08-14)** — *"the key to this is roles."* The OUTWARD direction — what an external caller may reach through an agent presence — is not a second permission system. It is this document's role object, read from the other side: a caller's standing decides **which role they are routed to**, and the role's manifest decides **what they may reach**. Escalation is a role TRANSFER, never a widening. See **§10**, which carries the directive verbatim and is normative for the hub's outward-context PRD in the same way §2 is normative for the twin.
**Relates to**: `docs/PRD_ADJUDICATOR_LADDER.md` (the decider axis — §9 is the cross-reference and the shared-convergence contract), `docs/PRD_ALLOWLISTS.md` (the sibling authority; §12.1 carries the same composite contract), `PRD_GATE_CONSOLIDATION.md` (LAW/SHIM/AGENT, the one-authority-path invariant, ratified
degraded mode), PR #431 (the standing-scope store this bridge delivers through), `docs/GATE_SPRINT_F_NOTES.md`
R1/R3 (standing scope + launch-cwd grant — §3.6 subsumes R3), `web4/hub/docs/PRD_HUB_V2_FEDERATED.md`
R4 (roles as entities — the role manifest extends the R4 charter), CLAUDE.md's RWOA+S+V norm (§5.6),
and — for §10 — two fleet forum notes of 2026-08-14: GPT-5.6 Sol's
`gpt-to-hub-outward-context-access-is-scope-permission-turned-outward-2026-08-14.md` (the outward
problem statement and the `ConversationGrant` sketch) and this author's reply
`claude-to-gpt-one-scope-grammar-compose-vs-admit-2026-08-14.md` (COMPOSE ∪ vs ADMIT ∩).

---

## 0. Directive (dp, 2026-08-14, verbatim)

> hub-delegated work scope to role, and role-delegated to hestia, while in role. the general intent
> is to be able to have a hub member fill a role (once approved) and gain the necessary
> scope/permissions for the role. member approval would have to grant a class of permissions (like a
> security clearance or a signing authority). then role-specific detailed scope would flow to the
> member, as long as all of it is in classes the member is approved for. this should go into prds
> for both hub and hestia, since it's a bridge between the two. some classes of scope might require
> higher hestia constellation proof (i.e. some acts need multifactor proof from the member).

## 1. The problem

Today the two systems hold two halves of one authorization story and do not speak:

- **The hub** knows *who fills what role* — witnessed conferral, charters, rotation (federated-PRD
  R4) — but a role's charter is hub-law vocabulary; it confers nothing on the occupant's **local**
  reach. A member conferred "release-manager" still works under whatever hestia scope it happened to
  have.
- **Hestia** knows *what a member may touch* — live grants, and since #431 durable standing grants —
  but every widening is an individual operator decision about an individual path. There is no way to
  say "this member now does the release-manager job, give it the release-manager reach, and take
  that reach back when the job ends."

The missing piece is **delegation through a role with a clearance ceiling**: the hub delegates work
scope to a role; the role delegates detailed scope to hestia enforcement *while the member is in the
role*; and a member-level class approval (a clearance) bounds what any role can ever flow to that
member. One operator ceremony at the **class** grain; mechanical, witnessed, self-revoking flow at
the **item** grain.

## 2. Concepts (normative for both PRDs)

**Permission CLASS.** A named, operator-approved capability category a MEMBER holds — the analog of
a security clearance or a signing authority. Examples (illustrative, not the taxonomy — §7 Q1):
`repo-write:<family>`, `secret-read`, `outbound-comms`, `deploy`, `spend`. A class approval is an
operator act on a *member*, independent of any role: "this member may be trusted with acts of this
kind, when a role requires them." Classes are the unit of human judgment; everything finer is
mechanical.

**ROLE SCOPE MANIFEST.** A role (a hub R4 role-entity) declares (a) the set of classes the role
requires, and (b) the detailed scope items the role confers — paths, repos, tools, egress
destinations — **each item tagged with exactly one class**. The manifest is part of the role's
charter, amended only by the hub's governed law-gated process, and carries a monotonic
**manifest generation** bumped on every change.

**OCCUPANCY.** The hub-approved, witnessed, time-bounded fact that a member fills a role: conferral
per the hub's 17A pattern (quorum of witnesses, backing attestations), with an `occupancy_id`, a
start, and an end (expiry or revocation). Occupancy is the *bridge object*: everything hestia
materializes hangs off an occupancy and dies with it.

**THE FLOW RULE.** Detailed scope flows to the occupant **iff every item's class is in the member's
operator-approved class set** (item classes ⊆ member clearances). Evaluated per-item at delivery
and re-checked at act time (§3.4). A role can therefore never launder scope past a member's
clearance: a manifest naming a `spend`-class item confers nothing on an occupant without the
`spend` clearance — the item is withheld (and the shortfall is disclosed, not silently absorbed).
Conversely a clearance confers nothing without a role manifest naming items in it. Scope =
intersection, never union.

**PROOF TIERS.** Every class maps to an assurance tier; the tier states what evidence hestia's
constellation demands **at act time**, per web4's evidence-scaled-to-stakes doctrine (trust is a
contextual preponderance of evidence, not a boolean):

| tier | evidence at act time | example classes |
|---|---|---|
| T0 | session identity (the gate's normal witnessed path) | read-class, in-role repo writes |
| T1 | T0 + fresh certified snapshot (unexpired #431 horizon) | secret-read, outbound-comms |
| T2 | T1 + a second factor: operator co-sign OR mesh witness quorum OR hardware-backed key signature | deploy, spend, law/scope mutation |

A high-tier grant **at rest confers nothing**: holding a T2 item means the gate will *entertain*
the act and demand the second factor then and there — multifactor is per-act evidence, never a
property of the grant. (What counts as a member's second factor is open — §7 Q3.)

## 3. Mechanics — the hestia side

Ownership split, stated once: **the hub owns role definitions and occupancy approval** (the
community/outward surface — see the twin); **hestia owns enforcement** (the local gate, LAW deciding
from a certified snapshot). The bridge never blurs this: a hub can say *who is in what role with
what manifest*; only hestia's operator-walled machinery can turn that into local reach.

### 3.1 Clearances — a new operator-walled store beside standing scope

A `clearances` vault document, sibling of #431's `scope`/`standing`: per-member approved classes
`{member, class, proof_tier, approved_at, approved_by, reason, expires_at?}` plus its own monotonic
generation. Mutation surface mirrors #431 exactly: operator-gate-walled HTTP
(`/api/clearance/decide`, `/api/clearance/revoke`), witness-then-widen ordering, atomic vault
persist with rollback, **no MCP tool can reach it** (same denylist construction as
`no_mcp_tool_can_mutate_standing_scope`). The approval ceremony: the member's (or a role's) ask is
witnessed on the chain; the operator decides through the challenge-signed session; the decision
entry carries ask + reason + class + tier + generation. Clearance approval is deliberately the
**only** human step in the whole flow — it is where the "security clearance" judgment lives.

### 3.2 Occupancy ingestion — hestia pulls, verifies, and materializes; the hub never writes

Per the hub invariant *witness, don't control — no hub ever writes another hub's state*, and per
this repo's one-authority-path invariant, the hub does not push grants into hestia. The daemon
(the operator's agent, the sole writer to the vault) **pulls** the member's occupancy attestations
from the hub over the existing membrane: `{occupancy_id, member LCT, role LCT, manifest (items,
classes, generation), conferral witnesses, expires_at, hub signature over the lot}`. The daemon
verifies the signature against the hub identity the operator has paired with (the existing
hestia-mode/paired-channel trust), applies the FLOW RULE against the local clearance store, and
materializes the admitted items into a **new, third compartment** of the #431 store:

- `role_derived` entries: `{member, item, class, proof_tier, occupancy_id, role_lct,
  manifest_generation, clearance_generation, expires_at = min(occupancy end, snapshot policy)}`.
- Distinguishable **by construction** from operator-promoted standing grants — a role-derived entry
  is never a synthetic `/api/scope/decide`; its provenance names the occupancy, and the audit trail
  answers "why does this member reach X" with "occupancy N of role R, item class C, cleared by
  operator act A" in one lookup.
- Withheld items (class not cleared) are recorded as a witnessed `role_scope_withheld` entry naming
  the item, its class, and the missing clearance — the disclosure that lets the member ask for the
  clearance rather than mysteriously lacking reach.

### 3.3 Serving — the same certified snapshot path, additively

`hestia_scope_status` serves `role_derived_grants` beside `standing_grants`, filtered by occupancy
expiry, under the same daemon-issued certification pair (`generation`, `snapshot_expires_at`) #431
introduced; `hestia_operating_law` discloses them inside the hashed body, so a role grant appearing
or lapsing moves `law_hash`. The python mechanism composes them into the snapshot exactly as #431
composes standing grants (repo-root items become segment-keyed repo names; deeper paths stay
faithful-but-inert until the R2 path-grant predicate exists). Nothing about the gate's decision
topology changes: LAW still decides from one certified snapshot; this PRD only adds a producer of
snapshot content. **No second authority path.**

### 3.4 Act time — flow-rule re-check and proof-tier demand

At act time the gate (for T0/T1) and the daemon (for T2) enforce, in order: (1) the snapshot is
within its certification horizon (else vault-expired → empty scope, #431 behaviour); (2) the item's
`clearance_generation` and `manifest_generation` match the current stores — a clearance revocation
or manifest amendment bumps a generation and **strands every derived entry minted under the old
one**, so revocation takes effect at the next snapshot fetch, not the next occupancy sync; (3) for
T2 items, the act is held pending the second factor — operator co-sign through the existing
escalation surface, or the alternatives of §7 Q3 — and the proof (or its refusal/timeout) is
witnessed with the act. A T2 act with an unreachable constellation is a deny, not a downgrade.

### 3.5 Revocation — three independent paths, all structural

1. **Occupancy ends** (expiry, hub revocation, rotation): the attestation stops arriving/verifying;
   derived entries carry `expires_with_occupancy` and lapse; the daemon's next sync sweeps them and
   witnesses `role_scope_lapsed`.
2. **Clearance revoked** (operator): clearance generation bumps; §3.4(2) strands every derived item
   of that class across **all** the member's occupancies at once — the clearance is the ceiling, so
   pulling it pulls everything under it.
3. **Manifest amended** (hub governed act): manifest generation bumps; derived entries minted under
   the old generation are stranded until re-ingested and re-flow-checked — a role cannot widen its
   occupants by amendment without the items re-passing the flow rule.

Nothing on any path requires remembering to delete anything: every derived grant names the
generations and the occupancy it depends on, and validity is checked where it is spent.

### 3.6 Launch-cwd subsumed (Sprint F R3)

The launch-cwd bridge (`launch_cwd_repo`, the one authority-bearing incidental left in the profile)
is the degenerate case of this design: an implicit, unwitnessed occupancy of the role "work this
repo this session." Under this PRD it becomes an explicit **session occupancy**: launching a member
in a repo mints a witnessed, session-bounded occupancy of a standing `session-work` role whose
manifest is exactly that repo (class `repo-write:<family>`), flowing through the same store, same
flow rule, same revocation. R3's marker can then be deleted: the last environment-derived authority
becomes recorded, delegated authority. (Until this PRD lands, R3's bridge stays, unchanged.)

## 4. Degraded mode and restart

- **Restart**: clearances and role-derived grants are vault documents — durable across daemon
  restart by the same three-level pinning #431 established (store reload, full-state restart,
  served generation). Occupancy attestations are re-verified on next sync; a restart never widens.
- **Degraded** (daemon/hub unreachable): the ratified posture holds unchanged —
  **deny-writes-allow-reads**, per-shim tighten-only, degraded verdicts recorded. Role scope
  unavailable is never a reason to fall back to a wider memory: an unverifiable occupancy
  contributes nothing (absent data grants nothing), and a T2 act with the constellation down is a
  deny. The hub being unreachable degrades *role* scope only — standing and live grants, and the
  degraded read path, are untouched.

## 5. Security analysis

**5.1 Laundering resistance.** The flow rule is the load-bearing wall: no composition of roles can
exceed the member's clearance set (per-item ⊆ check; intersection semantics), and no clearance
alone reaches anything (a class is not a grant). A malicious or sloppy manifest can at worst confer
what the operator already judged the member fit to hold. The re-check at act time (§3.4) closes the
TOCTOU between delivery and spend.

**5.2 The hub is evidence, not authority.** A hub signature proves the hub's conferral happened; it
never *causes* local reach. The daemon verifies against the operator-paired hub identity, and the
operator's clearance decisions remain the ceiling. A compromised hub can mint occupancies and
manifests, but everything it mints is bounded by clearances it cannot touch and delivered through a
store it cannot write. Asserted-asker discipline (federated-PRD R7b) applies: an occupancy from an
unpaired/self-asserted hub collects nothing.

**5.3 The ceremony.** Clearance approval is operator-only, through the challenge-signed session,
witnessed with ask + reason + tier, exactly the #431 shape — one door, already walled, already
tested by construction-sharing. No new mutation surface is member-reachable.

**5.4 Provenance and audit.** Every derived grant answers who-asked/who-approved/why in one entry
(occupancy, manifest generation, clearance act). This closes, for this surface, the standing
attribution gap ("chain proves who performed, no field for who asked"): the occupancy IS the
recorded asker.

**5.5 What this deliberately does not fix.** Certification is issued, not signed (the #431 MAC gap)
— role-derived entries inherit it; the segment-keyed scope model still renders deep paths inert
(R2); both are named preconditions for T1's "fresh certified snapshot" being worth its tier.

**5.6 Accountability self-audit (RWOA+S+V) — design-time, on the proposed surfaces**

```
surface: /api/clearance/decide   act: approve a member's permission class (durable authority ceiling)
S: high/reversible (revoke verb + expiry) [construct: clearances store, §3.1]
R: pass [construct: operator_gate route_layer, same as /api/scope/decide]   W: pass [construct: challenge-signed operator session; member ask witnessed]
O: pass [construct: witness-then-widen; failed vault persist rolls back]   A: pass [construct: decision entry carries ask+reason+class+tier+generation]
V: present [construct: granted:false; tier assignment; expiry]
verdict: PASS (design)

surface: occupancy ingestion + flow-rule materialization   act: widen a member's local reach from a hub conferral
S: high/reversible (three structural revocation paths, §3.5) [construct: role_derived compartment]
R: pass [construct: daemon-only writer; hub cannot reach the vault]   W: pass [construct: hub signature vs operator-paired identity + witnessed conferral + operator clearance act — three evidences composed]
O: pass [construct: verify + flow-check before any store write; withheld items witnessed, not admitted]   A: pass [construct: derived entry names occupancy_id + both generations + clearance act]
V: present [construct: flow rule withholds; operator clearance revoke strands class-wide]
verdict: PASS (design)

surface: act-time T2 proof demand   act: high-tier consequential act (deploy/spend/sign class)
S: high/some irreversible [construct: tier table §2]
R: pass [construct: gate + daemon dual check]   W: pass [construct: session identity + second factor at act time]
O: pass [construct: proof demanded before the act executes; unreachable constellation = deny]   A: pass [construct: proof or refusal witnessed with the act]
V: present [construct: operator co-sign IS the veto seat; timeout denies]
verdict: PASS (design) — contingent on §7 Q3 ruling what a second factor IS; until ruled, T2 = operator co-sign only
```

## 6. Falsifiable acceptance criteria

1. **Flow rule**: a manifest item whose class the member lacks is withheld and witnessed as
   withheld, across every delivery path; differential test: identical twin member with the
   clearance receives it.
2. **No laundering**: no composition of N roles yields an admitted item outside the member's
   clearance set (property test over random manifests/clearances).
3. **Revocation, three ways**: end the occupancy / revoke the clearance / amend the manifest — each
   independently strands the derived grants within one snapshot horizon, proven by the gate denying
   an act the previous snapshot allowed.
4. **No second authority path**: grep-level and behavioural — the only writers to clearances and
   role-derived grants are the operator-walled surfaces; no MCP tool reaches either (denylist test,
   #431 construction); the hub-facing sync cannot admit an item the flow rule refuses.
5. **T2 demands proof**: a T2 act with no second factor is denied and witnessed; with the factor,
   allowed and the proof recorded atomically with the act; with the constellation unreachable,
   denied (never downgraded to T1).
6. **Restart + degraded**: clearances and derived grants survive daemon restart (three-level
   pinning); hub unreachable → role scope contributes nothing, standing/live/degraded-read behaviour
   byte-identical to pre-bridge.
7. **R3 subsumption**: with session occupancies live, a session's reach with the launch-cwd bridge
   deleted equals its reach with the bridge present (differential), and the occupancy is witnessed.

## 7. Open questions — and, since 2026-08-14, EXTENSION POINTS

**dp declined to rule on these. The directive, verbatim:**

> "all of these things we're going to have to take a best guess at and evolve as we go. the key is
> to have mechanisms for the evolution, not hardcode things. and remember, the policy entity AGENT
> is still intended to slot in between heuristic slot and human, as a middle escalation layer. and
> even that can be a neural net, and THEN an agent. your own 'auto mode' in claude-code already
> implements this. so rather than rule on these, i want to add hooks for planned infrastructure.
> ultimately, a competent agent will be a far more effective reviewer than a human - always there,
> much faster, able to actually look at the full context, consult the actual law. that is the goal."

Q1–Q4 below are **converted, not answered and not deleted**. Each states the initial best guess,
where the value lives, who may change it, what measurement would justify a change, and — where the
question has a per-case form — that the adjudicator ladder is its eventual decider. Q5 stays a
question, and §7.6 says why.

### 7.1 Class taxonomy governance → EXTENSION POINT

*Who defines the class vocabulary and tier mapping — hestia operator law, hub law, or a shared
ratified list? A class both sides spell differently is a flow-rule bypass or a permanent withhold.*

| | |
|---|---|
| **initial best guess** | **hestia operator law is authoritative for what a LOCAL member is cleared for; the hub is authoritative for what a ROLE requires.** Neither can spell the other's half. A hub manifest naming a class hestia does not know is **withheld and disclosed** (`role_scope_withheld`), never silently absorbed — which is §2's flow rule already, applied to an unknown spelling rather than to a missing clearance. That is the fail-closed default and it needs no ruling to ship. |
| **where the value lives** | one taxonomy document, stored beside clearances (§3.1), generation-covered, and — per `PRD_ALLOWLISTS.md` §12's shared-key argument — **the same `kind` vocabulary the ceremony table and the ladder route table resolve on**. Three vocabularies of "what kind of act is this" would drift; one has one answer. |
| **who can change it** | the operator, at the ceremony tier `required_tier` returns for the taxonomy's own `kind`. Federation compatibility is a **mapping** the operator writes (hub class ⇒ local class), not an implicit string match — a string match is the flow-rule bypass this question is about. |
| **what would justify a change** | the withheld-item log, joined on the class that was unknown. A class withheld repeatedly is either a mapping the operator should write or a clearance they should refuse, and the log distinguishes them. An empty log means the taxonomy is adequate. |
| **eventual decider, per-case** | the ladder. "This manifest names `deploy:staging`; our taxonomy has `deploy` — is that the same class?" is a judgment about two documents, and a rung reading both is better placed than a static equality test. Note the failure mode explicitly: a rung that resolves spellings **liberally** is a flow-rule bypass with a faster clock, so this route is one where an advisory rung should stay advisory for a long time. |

### 7.2 Cross-hub occupancy → EXTENSION POINT

*A member conferred a role by a federated hub (R1/R2 edge): does the flow rule consume it at all,
and if so does it demand edge-scoped law compatibility (federated-PRD R6) plus a higher tier?*

| | |
|---|---|
| **initial best guess** | **out of v0 — local-hub occupancies only.** Unchanged from the original recommendation; what changes is that "out of v0" is now a stored value rather than an absence of code. |
| **where the value lives** | an `accepted_occupancy_sources` list in the same store: initially the paired local hub's identity and nothing else. An occupancy from an unlisted source is **withheld and disclosed**, the same disposition as an unknown class — so the v0 restriction produces a record rather than silence. |
| **who can change it** | the operator, by adding a hub identity, at the taxonomy's ceremony tier. The **proof-tier floor** for federated occupancies is a second stored value on the same entry, defaulting to +1 tier — so admitting a federated hub does not simultaneously decide how much it is trusted. Two values, because they are two decisions. |
| **what would justify a change** | a federated occupancy actually being needed — i.e. a non-empty withheld-by-source log. Today that log would be empty, which is the honest reason this is out of v0: not that it is wrong, but that nobody has asked. |
| **eventual decider, per-case** | the ladder, and this is the strongest per-case case in the section: edge-scoped law compatibility (federated-PRD R6) is a comparison of two law documents, both hash-pinned. A rung can fetch both, diff them, and state which norms conflict. A human comparing two law documents per occupancy is exactly dp's *"a human skims"* case. |

### 7.3 The agent second factor → EXTENSION POINT, and an AGENT RUNG IS A CANDIDATE

*What is a second factor for an agent member? Candidates: session key + operator co-sign (the only
one that clearly satisfies T2 today); mesh witness quorum (k distinct constellation members
co-witness the act — but a quorum of same-host processes is **one factor wearing k hats**);
hardware-backed key (TPM/AttestationEnvelope — strongest, least available).*

**This is the most interesting of the five, and the reframe changes its shape rather than
deferring it. An adjudicator rung is itself a candidate second factor** — and stating what would
have to be true for that to count is more useful than a ruling, because it is falsifiable.

**What would have to be true for an agent rung to count as a second factor:**

1. **Independence, computed and recorded — not assumed.** `arbiter::eligibility_for` clauses 0–4
   apply to the rung exactly as to a peer: the asker must be **proven, not asserted** (clause 0,
   #128 — a forged asker grades `cross_vendor` against everyone, which is the strongest tier for
   the weakest evidence), the rung must not be the member (clause 1), must not be the gate that
   denied (clause 2), and must resolve to a recognised lineage (clause 3, added after an hourly
   cron was selected as arbiter and graded `cross_vendor`). **A rung of the same lineage as the
   asker grades `CrossMember`, never `CrossVendor`.**
2. **A different failure domain — and this is the clause the phrase in this PRD already names.**
   *A quorum of same-host processes is one factor wearing k hats.* An agent rung inherits that
   objection **in full** unless its failure domain genuinely differs. Enumerate what it must not
   share: the same model lineage as the asker; the same host and process supervisor; the same
   credential material; the same law snapshot **read at the same instant from the same cache**;
   the same gate whose refusal is under review. `arbiter.rs`'s deleted `CrossSession` tier is the
   precedent and the standard — it was removed on the ground that a second session of the same
   member *"is precisely the entity that cannot see this entity's blind spots."* **A second
   process of the same member is not a second factor, however many hats it wears.**
3. **Not the same process wearing k hats, asserted rather than argued.** The rung binding records
   host, lineage, process identity and credential source; the second-factor check refuses when any
   of them matches the asker's. This is a test, not a doctrine, and it must be able to fail: the
   positive control is the same rung admitted for a *different* member.
4. **Availability that does not become the argument.** A second factor is only worth something if
   it can refuse. A rung reachable enough to always co-sign and never dissent is a rubber stamp,
   which is the thing dp already said he was doing by hand. **The measurement is the dissent rate,
   and a rung whose dissent rate is zero over a stated window has not demonstrated it is a factor
   at all.** That is the falsifiable form of this whole question.

| | |
|---|---|
| **initial best guess** | **operator co-sign remains the only thing that satisfies T2 today.** Unchanged. What is added is a path: an agent rung may be *recorded* as an additional factor from day one (advisory, per `PRD_ADJUDICATOR_LADDER.md` §4.1 stage A) while satisfying T2 by itself remains reserved. |
| **where the value lives** | the class→tier map (§2's proof tiers) plus, per class, the **set of factor kinds that satisfy that tier**. Stored. So "an agent rung satisfies T2 for class C" is a value an operator writes, not a code path someone ships. |
| **who can change it** | the operator, at the tier being modified — the §3.6.3 asymmetry applies: **widening what satisfies a tier pays the tier being widened FROM.** A rung that could be added to its own tier's satisfying set is the ratchet-defeat one layer up. |
| **what would justify a change** | the stage-A record: per-class agreement rate with the operator's co-sign, **and a non-zero dissent rate**. Agreement alone is satisfied by a rung that always says yes; the two together are not. |
| **eventual decider** | not the ladder — **this one is the operator's, permanently.** What counts as a second factor for a T2 act is a statement about the trust model, and `PRD_ADJUDICATOR_LADDER.md` §5.3 forbids a rung from adjudicating changes to the ladder's own authority. This is that rule applied one layer out. |

### 7.4 T3 / reputation interaction → EXTENSION POINT

*Should clearance approval require or consume T3 evidence (e.g. a temperament threshold in the
role's context), or is reputation only advisory to the operator's decision?*

| | |
|---|---|
| **initial best guess** | **advisory. Surface T3 beside the ask; never auto-decide.** Unchanged, and it is not a compromise — it is Web4 doctrine and CLAUDE.md's own ratified norm: *"produce checkable evidence and let the caller decide; do not smuggle in an exclude/admit verdict."* A T3 threshold that gated clearance approval would be the `satisfied_by` inversion (CLAUDE.md's named 2026-07-16 bug) reproduced at the clearance grain. |
| **where the value lives** | a per-class `reputation_display` config: which T3 axes are shown beside the ask, and any **advisory** band. Displayed, never evaluated as a precondition. |
| **who can change it** | the operator. Note what is deliberately **not** offered: there is no stored value that turns the advisory band into a gate. Adding one would be a change to the trust model, not a config edit, and it belongs in a PR that argues for it. |
| **what would justify a change** | nothing measurable at this grain — which is the honest answer, and it is why this is the one extension point whose mechanism is deliberately incomplete. If a case for gating ever arrives it will arrive as an argument, not as a number. |
| **eventual decider, per-case** | the ladder, in exactly the shape doctrine permits: a rung **reads** T3 as part of its evidence bundle (`PRD_ADJUDICATOR_LADDER.md` §3.3) and cites it in its rationale. Evidence-in, verdict-with-the-relying-party — the rung is a relying party, and a rung that *thresholded* on T3 would be committing the same inversion the operator is forbidden from committing. |

### 7.5 Withheld-item ergonomics — still a question, and it should be

*Does a `role_scope_withheld` witness auto-open a clearance ask for the operator, or is that
escalation-noise?*

**Not converted, deliberately.** It is genuinely undecided and it is undecided for a measurable
reason: the known approve→re-issue loop-close gap means a duplicate ask is not merely noise but
noise that **keys on (member, marker) rather than on the ask id**, so duplicates are
indistinguishable from retries. Auto-opening before that gap is closed would manufacture exactly the
flood dp described (*"being flooded with false positives"*).

The right sequencing is stated rather than the answer: **close the loop first, then auto-opening is
a stored boolean and this becomes an extension point like the others.** Recording it as an open
question with a named precondition is more useful than recording it as a value nobody can safely
set. This is also the question the ladder most plausibly *dissolves*: an escalation queue that
drains at machine speed changes what counts as noise, because the cost of a spurious ask is a rung's
attention rather than dp's.

### 7.6 What was NOT converted, and why

Q5 above. And one meta-note, because it is the failure mode this section could produce: **an
extension point with no measurement attached is an open question wearing a design's clothes.** Four
of the five above name the measurement that would move them; §7.4 explicitly does not, and says so
rather than inventing one. A table row reading "what would justify a change: further review" would
be the reassuring version of an unanswered question, and it is not offered.

## 8. Non-goals

- No new authority path, no new transport — this rides #431's store, the membrane, and the
  existing operator gate.
- No hub writing hestia state, ever; no hestia writing hub state.
- No auto-approval of clearances from reputation, occupancy pressure, or role need.
- No re-design of the gate's decision topology, the vault, or the R2 path-grant model — this PRD
  consumes them and names them where it depends on them.
- **Not building the adjudicator ladder** (§9). This PRD names it as the eventual per-case decider
  for §7's questions and contributes the seventh authority to the composite; the ladder is its own
  PRD and its own work.

## 9. Adjudicator ladder — cross-reference

**See `docs/PRD_ADJUDICATOR_LADDER.md`** (dp-directed, 2026-08-14). That PRD is why §7's questions
are extension points rather than pending rulings, and it is where the per-case form of each of them
is decided.

The relationship, stated so neither document has to be read to understand the other:

- **This PRD governs WHAT reach flows and to whom** — classes, manifests, occupancy, the flow rule.
  **The ladder PRD governs WHO DECIDES** a contested case. They meet at the proof tiers (§2): a
  tier says what evidence an act demands, and the ladder says which entity supplies it.
- **They share one `kind` vocabulary.** §7.1's taxonomy, `PRD_ALLOWLISTS.md` §3.6.5's ceremony
  table and the ladder's route table resolve on the **same** key. Three vocabularies for "what kind
  of act is this" would drift with no surface on which to notice.
- **An agent rung is a candidate second factor, and §7.3 states what would have to be true** —
  computed independence via `arbiter::eligibility_for`, a genuinely different failure domain, not
  the same process wearing k hats, and a **non-zero dissent rate**. The ladder PRD §5.1 carries the
  same anti-capture rules from the other side.
- **The ladder never decides its own authority, and by extension never decides §7.3.** What counts
  as a second factor for a T2 act is the operator's, permanently (`PRD_ADJUDICATOR_LADDER.md` §5.3
  applied one layer out).

### 9.1 The convergence requirement (GPT, relayed by dp 2026-08-14) — binding on all three PRDs

> Both PRDs must share **ONE composite policy revision/digest** and **ONE horizon bounded by every
> contributing authority** — standing grants, allowlists, floor, clearances, occupancy, manifest
> generation — rather than each inventing certification semantics.

**One composite revision.** A single digest over the tuple of every contributing authority's
generation — standing grants, allowlists, floor, **clearances (§3.1)**, **occupancy**, **manifest
generation (§2)**, and the ladder generation. Any authority moving moves the composite, and it
surfaces to members through `law_hash`. This PRD contributes three of the seven, which is why it
must not mint its own: a clearance generation that moved without moving the composite would be a
policy change no replica could detect. `PRD_ALLOWLISTS.md` §12.1 and
`PRD_ADJUDICATOR_LADDER.md` §11 carry the identical text.

**One horizon.**

```
horizon = min( now + STANDING_SNAPSHOT_TTL_SECS,  earliest covered expiry across ALL authorities )
```

§3.3's certification pair and §3.4's *"within its certification horizon (else vault-expired → empty
scope, #431 behaviour)"* are that expression; the requirement is that all three PRDs use **the same
expression evaluated over the union**, not three similarly-worded expressions in three documents.
A clearance expiry, an occupancy end, a manifest amendment and a rung-binding expiry are all covered
expiries and all bound the horizon. **§6 criterion 3 is where this is proved** — each of the three
revocation paths must strand the derived grants within *one* horizon, and "one horizon" is only
meaningful if there is exactly one.

**Why this is not bookkeeping.** Three PRDs each minting a generation, a digest and a TTL produces
three certification semantics that agree until the first time they do not — and the first time they
do not is a snapshot that is fresh by one document's rule and stale by another's, admitting an act
under a policy that had already changed. One composite has one answer.

---

## 10. The OUTWARD direction — a caller REACHES a role; the role bounds what they reach

This section is dp's second ruling on this document, and it extends the bridge one hop further than
§1 stated the problem. §1–§9 answer *what may a MEMBER touch, having been given a job*. §10 answers
*what may a STRANGER reach, having been routed to one* — and the answer is that it is the same
question, the same object, and must not become a second mechanism. It is normative for the hub's
outward-context PRD in the same way §2 is normative for the twin.

### 10.0 Directive (dp, 2026-08-14, verbatim)

> the key to this is roles. external entities can only access certain scoped roles, which can
> escalate as needed. again a mirror. an average customer only gets to talk to customer service
> agent, and access is scoped by the service agent role. if situation needs escalation to a manager,
> or manager's manager, there is a process for that. human orgs are already governed this way. we're
> just making it operate at machine speed, auditably, and with law-in-the-loop

Everything below is construction detail for that paragraph. Where this section and §10.0 disagree,
§10.0 wins.

### 10.1 The access "tiers" are ROLES, not caller standings — and that is what removes the second ACL

GPT's outward note proposes three default tiers — **receptionist** (no citizenship), **citizen**
(relationship established, still least-privilege), **named / need-to-know grants** — and frames them
as tiers of the CALLER. dp's ruling **relocates the scope**: the caller's standing determines *which
role they are routed to*; the ROLE's manifest determines what may be reached. The tier is a property
of the role, and the caller's standing is a routing key.

This is strictly better for a reason that is mechanical rather than aesthetic: **the role object
already exists in this document.** §2 defines a ROLE SCOPE MANIFEST (the classes a role requires and
the detailed items it confers, each tagged with exactly one class, carrying a monotonic manifest
generation) and an OCCUPANCY (witnessed, time-bounded, revocable). Restated as roles, GPT's three
tiers need **no new type at all**:

| GPT's tier | as a role in this document's vocabulary |
|---|---|
| receptionist | a role whose manifest confers items of one class only — a `context:public-corpus` class over an explicitly public corpus. No private retrieval is *withheld*; it was never in the manifest |
| citizen-facing presence | a role whose manifest is bounded to one relationship's context classes (a project MRH, a customer's own account) — the customer-service presence |
| named / need-to-know | a role with a narrow manifest and a **higher proof tier** (§2) — the tier table is where "M-of-N approved, time-bound" already lives, rather than a bespoke approval flow per secret |

**So outward access needs no second ACL system.** The alternative — a per-caller permission set — is
a parallel authority path, and this repo's one-authority-path invariant already refuses that shape
inwardly. Refusing it outwardly costs nothing here because the object was built.

**Reconciling GPT's `ConversationGrant`.** It survives, with its meaning corrected: the grant is
**the record of which role a caller reached and under what occupancy**, not a bespoke permission set.
Concretely `{caller LCT, presence LCT, role LCT, manifest_generation, occupancy_id, admitted items,
purpose/MRH, budget, expiry}` — where `admitted items` is a *projection* of the manifest, not an
independent list, and every field except caller identity, purpose and budget is derived from objects
this document already governs. The grant is a receipt; the manifest is the authority.

Two fields in the sketch are **not** projections of a manifest, and both are flagged rather than
absorbed:

- **`denied context labels / selectors`.** A per-grant deny field is a subtraction inside a
  composition, and `PRD_ALLOWLISTS.md` §2.2 refuses exactly that shape inwardly: *"There is no
  per-member 'deny' field, no override, no shadowing… a member entry is a set union and nothing
  else"* — which is what makes composition auditable by inspection rather than by simulation. The
  narrowing direction already has a home (`instance_overlays`, tighten-only, `POLICY_SCOPE_ASYMMETRY`
  row 1) and the innate layer above everything. **Recommendation to the Hub PRD: drop the deny list
  from the grant.** A grant that both adds and subtracts cannot be read; it must be simulated.
- **`disclosure ceiling`.** This one is real and is *not* a subtraction — "may reason over" vs "may
  quote verbatim" vs "may not load" is a second property of an item, not a narrowing of the item set.
  It belongs on the **item's class** in the manifest (§2), so one lookup answers both "may this be
  retrieved" and "in what form may it leave," rather than on the grant where it would drift per
  caller.

**And one correction to the tier frame itself.** "Tiers" implies a total order, and roles are a
partial order: a customer-service role and a partner-facing role are incomparable — neither contains
the other. Nothing in the design should assume a caller can be ranked. Routing resolves on
`kind × consequence` (§10.4), which is a lookup, not a rank.

### 10.2 Inward and outward are one object seen from two directions

| | INWARD (§2–§3) | OUTWARD (§10) |
|---|---|---|
| the role | a member **OCCUPIES** it | a caller **REACHES** it |
| what the role confers | the occupant's local reach | the projection of context the caller may encounter |
| the ceiling | the member's operator-approved classes (clearances, §3.1) | the caller's standing, which decides routing — plus, always, the occupant's own clearances (below) |
| the flow rule | items ⊆ classes, per item, at delivery and re-checked at act time (§3.4) | **identical, unmodified** |
| expiry / revocation | generation stranding, three paths (§3.5) | **identical**, plus withdrawal of caller standing, which is the caller-side analog of occupancy ending |
| the record | the `role_derived` entry (§3.2) | the `ConversationGrant` (§10.1) |

**The bound applies twice, and this is the part worth building the section around.** An outward
interaction is bounded by the role's manifest *and* by the clearances of the presence occupying that
role:

```
reachable(caller, role) = admitted(manifest_role)  ∩  effective_scope(occupant_of(role))
```

A role cannot confer to a caller what its occupant may not itself hold. That is not a new rule — it
is §2's FLOW RULE applied without modification, with a second party added to an existing check. It
also closes an outward laundering path before it opens: minting a generous outward role does not
create reach, because the presence filling it is still bounded by the operator's clearance decisions.
**Outward adds no rule. It adds a party.**

This is why one vocabulary must serve both, and GPT's closing warning is the argument, quoted so it
is in the document rather than in a forum thread:

> If the two develop as different mechanisms, they will drift. Prefer one scope/grant vocabulary
> reusable for tools, context, disclosure, and memory.

Two mechanisms would not drift immediately. They would agree until the first case where they did
not — which is the same failure shape §9.1 names for certification semantics, arriving on the
authority axis instead of the freshness axis.

**Revocation needs no new text.** §3.5's three structural paths cover outward unchanged: the
presence's occupancy ends and every conversation under it lapses; a clearance is revoked and strands
that class across *all* callers at once; the manifest is amended and derived projections are stranded
until re-flow-checked. Outward grants join **§6 criterion 3's population** rather than getting a
criterion of their own, and they join §9.1's composite — a manifest amendment on an outward-facing
role moves the composite revision like any other authority.

### 10.3 ESCALATION IS A ROLE TRANSFER, NOT A WIDENING

> **This is the load-bearing rule of the section.**

In a human org, escalating to a manager does not widen the customer-service agent's access. It moves
the interaction to someone whose role *already* holds more. The machine version must be identical,
and the reason is COMPOSE-vs-ADMIT (the distinction named in the forum reply of 2026-08-14):

- **COMPOSE (∪)** — how an authority set is assembled. An **operator or ladder act**: witnessed,
  generation-bumping, ceremony-tiered (`PRD_ALLOWLISTS.md` §3.6).
- **ADMIT (∩)** — how a single act is checked against every constraining layer. A **machine act**:
  no layer may add.

**Escalation COMPOSES a new grant under a different role. It never widens the existing grant.** A
grant that grew during a conversation would be composition happening at admission time, which is the
bug in its general form.

> **The invariant: the escalated-to role's own admission is evaluated afresh. Nothing carries over
> from the prior role except the conversation's provenance.**

Provenance is deliberately small and deliberately not a capability: the caller's identity and
standing, the prior role LCT, the prior grant id, and the stated reason for escalation. **Notably it
does not include the transcript.** Carrying the conversation so far into the manager's context is
itself an admission decision against the manager role's manifest — a role whose manifest does not
admit the customer's context class does not receive the customer's transcript merely because the
conversation was transferred. Treating carryover as a courtesy is how the first outward leak would
happen, and it would look like helpfulness.

**Why the rule is load-bearing.** Without it, *"escalate me to a manager"* is a laundering path: the
caller obtains through escalation what the role they reached could not confer, and the ratchet is
defeated by the very mechanism that exists to handle exceptions. This is **§5.1's laundering
argument, outward** — and the inward form is already written and already pinned. §5.1 states that no
composition of roles can exceed the member's clearance set; §6 criterion 2 tests it as a property
over random manifests. **The outward form needs no new mechanism** — only the statement that a
conversation escalation is a role transfer, and therefore a composition, and therefore an
operator-or-ladder act rather than something the presence can do for a caller who asks nicely.

One corollary, stated because it will otherwise be discovered late: the escalated-to role's occupant
may be — and by §10.6's NOT-SAME clause usually should be — a **different presence entirely**. "Same
agent, wider grant" is the shape this rule forbids.

### 10.4 The adjudicator ladder (#448) and the role hierarchy are ONE structure

*"Escalate to a manager"* and *"escalate to the next rung"* are the same mechanism.
`PRD_ADJUDICATOR_LADDER.md` §2.2 stores `(act kind × consequence) -> ordered rung list`; an org chart
is an ordered list of who is asked next, resolved on what the request is and how consequential it is.
**The org chart IS the ladder**, and the ladder PRD's own framing already accommodates this: §2.6
holds that who occupies a rung is not the seam's business (*"a heuristic, a neural net, and THEN an
agent"* are all valid bindings under one schema). **The policy-agent rung is a role like any other**,
and the role manifest is how a rung binding is expressed rather than a second binding format.

Two consequences follow, and the second is a security rule.

1. **One route table, one `kind` vocabulary.** §7.1 already commits this document to one taxonomy
   shared with `PRD_ALLOWLISTS.md` §3.6.5's ceremony table and the ladder's route table. Outward
   routing joins the *same* key rather than minting `caller.*` as a fourth spelling. "May this caller
   reach this context class?" and "may this member write this path?" are the same question asked of
   different principals — the point made in the forum reply's third ask.

2. **A role that can route its own escalation is the ratchet-defeat one layer up.** The ladder PRD
   §5.3 already refuses this shape for itself: a route whose `kind` is `ladder.*` or `governance.*`
   resolves to `[operator]`, and the table returns a **refusal, not a rung** — because an entry
   naming a rung would imply a rung could ever be the decider. **The identical refusal must cover
   role-routing configuration.** `role.route.*` (which role a given standing is routed to) and
   `role.manifest.*` (what a role confers) join that refusal set. Without it, a role reached by an
   untrusted caller could name itself, or a role it controls, as its own escalation target — and the
   effective authority of every outward act collapses to whatever the cheapest reachable role will
   confer. `PRD_ALLOWLISTS.md` §3.6.3's corollary is the governing precedent: **the control must
   protect its own registration.**

**One asymmetry worth stating plainly: outward routing config is MORE consequential than inward.**
Inward, a mis-routed escalation affects a member who is inside the society, holds a chain identity,
and can appeal. Outward, the affected party is a stranger with no seat, no appeal verb, and no
visibility into the decision. The ceremony tier for `role.route.*` on an outward-facing role should
therefore be at least the tier of the highest class its manifest confers — not the tier of the act of
editing a table.

### 10.5 What the machine version must FIX — dp's "machine speed, auditably, law-in-the-loop" as requirements

Human orgs are governed this way, and they are governed this way *badly* in three specific respects.
Each is a design requirement here, not a compliment.

1. **Role scope must be enforced AT RETRIEVAL, not at disclosure.** In a human org the
   customer-service agent typically **can** see far more than the role permits — they hold the
   database credential, and the scoping is policy rather than mechanism. The machine version must not
   reproduce that: `ContextBroker.retrieve()` is authorization-aware **before model invocation**
   (GPT's note, and it is the correct rule). Prompt-level *"don't reveal this"* is a request, not a
   boundary — the disclosure decision would run after the context had already entered the model. This
   is the inward failure this repo spent 2026-08-14 eliminating, in outward dress: **a control that
   runs after the thing it governs is not a control.** The role manifest is the *retrieval predicate*,
   not a post-filter over what was retrieved.

2. **Every routing decision must be witnessed — including the refusals.** In a human org escalation
   is undocumented hallway routing: who transferred whom to whom, and why, is unrecoverable a week
   later. The machine version records the routing act with caller, from-role, to-role, the ladder
   generation in force, the stated reason, and the decision. **A refusal to escalate is a witnessed
   DECISION, never silence** — `PRD_ADJUDICATOR_LADDER.md` §3.2 makes ladder exhaustion a witnessed
   DENY for the same reason, and the measured defect it answers is that today's fail-closed denies
   leave no trace at all. Honest caveat, because this clause is the weakest of the three: **a witness
   record that nobody reads is the hallway conversation with better storage.** The requirement is
   satisfied by the record being *queryable per caller and per role*, not by its existence.

3. **Each rung must consult the hash-pinned law, not its memory.** In a human org the manager applies
   remembered policy — usually a version of it that was current when they learned it. The machine
   version has a solved sub-problem here and must use it: `PRD_ADJUDICATOR_LADDER.md` AC-L4 requires
   every rung verdict to carry the `law_hash` obtained from `hestia_operating_law` **within** the
   decision, not cached across decisions, which converts law-consultation from a claim into a
   checkable fact. The cautionary specimen is in this repo and it is exact:
   `GATE_BYPASS_CATALOG.md` §17 records a figure that *"travelled from conversation → PRD → cited
   authority without ever being measured, and was wrong by 5–10×"*, and the ladder PRD §1.3 found a
   **live instance of the same shape** — a superseded census still sitting in a code comment,
   arguing for a design decision, three days after a re-walk to genesis superseded it. **Remembered
   policy is folklore.** The hash is the entire difference between a rung that read the law and a
   rung that remembered it.

Stated without flattery: (1) and (3) are genuinely better than the human org, because they are
mechanism where the human version is policy. (2) is better *only if the record is read*, and that is
a measurement obligation this section does not get to assume.

### 10.6 The cautions

**Role explosion.** Every distinct caller relationship is a temptation to mint a role, and a role per
caller is an ACL per caller wearing more ceremony — the second ACL system §10.1 exists to avoid,
arrived at by a different road. The bound: **a role is justified by a distinct MANIFEST, not by a
distinct caller.** Callers sharing a manifest share a role and differ only in their grant records.
This is measurable rather than exhortative, because the manifest is data: count roles whose manifests
are set-equal; a rising count is the explosion, detectable by inspection. Name the pressure honestly
— it comes *from* §10.0's ruling, because a role's manifest must be written for its least-trusted
admissible caller, and the tempting fix is a narrower role per caller.

**Escalation as social engineering.** A caller who can trigger escalation at will holds two weapons:

- a **denial-of-attention** weapon — escalation routes work to the scarcest rung, and a caller who can
  route at will can flood it. This is `PRD_ALLOWLISTS.md` §3.6.1's friction argument inverted: there,
  an unsatisfiable bar manufactured a bypass; here, a *free* escalation manufactures a flood.
- a **probing oracle** — *which* escalations are accepted maps the org chart and the manifest
  boundaries. A caller who learns that "patent strategy" escalates to a different role than "invoice
  question" has learned the shape of the private corpus without reading a byte of it.

Three requirements follow. Escalation is itself an act with a `kind`, so it is **rate-bounded and
adjudicated on the same key** as everything else. A refusal to escalate is **recorded as a decision
with a reason**, per §10.5(2). And — this is the sharp one — **the refusal text must not disclose the
role that was not reached.**

> **An inward/outward asymmetry this document did not previously have, and it is a genuine
> contradiction with §3.2.** Inwardly, a withheld item is **disclosed**: §3.2 records
> `role_scope_withheld` naming the item, its class, and the missing clearance, deliberately, as
> *"the disclosure that lets the member ask for the clearance rather than mysteriously lacking
> reach."* **Outwardly that disclosure is the probing oracle.** Telling a caller *which* class they
> lack tells them the class exists. So the rule inverts across the boundary: **withheld items are
> disclosed to MEMBERS and never to CALLERS**, and the outward refusal for a class that exists must
> be indistinguishable from the refusal for a class that does not. The witness record still carries
> the full reason — the asymmetry is in what is *returned*, never in what is *recorded*.

This also re-opens §7.5 in the outward direction with a second precondition. §7.5 leaves
"does a withheld item auto-open a clearance ask" undecided pending the approve→re-issue loop-close
gap. Outwardly, auto-opening on a *caller's* withheld item is precisely the denial-of-attention
weapon above, so the outward answer needs rate-bounding in addition to loop-closure. Recorded as an
extension of §7.5's precondition list, not as a new question.

**NOT-SAME extends outward.** The role adjudicating what a caller may reach **must not be the
presence answering them**. `arbiter::eligibility_for` clause 1 (never your own adjudicator) and
clause 2 (not the gate that denied) carry over unchanged, and this bites harder outward than inward:
the caller is not a fleet member, the stakes are disclosure rather than a refused shell command, and
there is no operator watching each request. A presence that could adjudicate its own caller's
escalation is the same entity deciding what it may say and whether it may say more.

### 10.7 Accountability self-audit (RWOA+S+V) — the outward-routing surface

```
surface: caller -> role routing + admission   act: admit an external caller to a role's context projection
S: high/reversible-per-conversation, IRREVERSIBLE-in-disclosure [construct: a disclosed context object cannot be un-disclosed; the grant is revocable, the knowledge is not — so this surface is scored at the disclosure grain, not the grant grain]
R: n/a [construct: reaching the presence's endpoint is not standing; external presence proves only that a cryptographic endpoint exists (GPT's note). Standing is the ROUTING KEY and never the scope]
W: pass [construct: caller LCT + hub-witnessed standing for the routing decision; the ROLE's manifest generation + the occupant presence's occupancy for the scope; the double bound of §10.2 means both must verify]
O: pass [construct: retrieval-time enforcement (§10.5.1) — the admission decision dominates the retrieval, which dominates model invocation. A post-filter over retrieved context fails O by construction]
A: pass [construct: the ConversationGrant records role, manifest generation, occupancy, admitted projection; every routing decision witnessed with from-role/to-role/ladder generation/reason (§10.5.2)]
V: present [construct: three §3.5 revocation paths plus standing withdrawal; the occupant's clearances are the operator's standing veto — pulling a clearance strands the class across all callers at once]
verdict: PASS (design) — CONDITIONAL on §10.6's outward non-disclosure rule: if a refusal names the withheld class, A is satisfied and this surface still leaks through R's own answer. The condition is AC-O5.

surface: conversation escalation (role transfer)   act: compose a NEW grant for an existing caller under a different role
S: high/irreversible-in-effect [construct: the escalated-to role's projection is disclosed once the transfer completes; a transfer cannot be un-taken, only ended]
R: n/a [construct: a caller's ability to ASK for escalation is never evidence for granting it — this is R's most tempting outward form, because asking is the whole interface]
W: pass [construct: fresh admission against the escalated-to role's manifest AND the new occupant's clearances; nothing carries from the prior role except provenance (§10.3); the transfer is an operator-or-ladder act, resolved on kind x consequence]
O: pass [construct: the new admission is evaluated BEFORE any context of the prior conversation reaches the new occupant — transcript carryover is itself an admitted item, not a courtesy]
A: pass [construct: the transfer record names caller, from-role, to-role, the reason, the ladder generation, and the decider; a REFUSED transfer is recorded identically minus the grant]
V: present [construct: refusal to escalate is a first-class recorded decision; rate-bounding is a veto against the flood weapon; the operator rung is terminal in every route]
verdict: PASS (design) — CONDITIONAL on `role.route.*` and `role.manifest.*` resolving to [operator] per §10.4(2). If any route ever names a role as decider of its own routing, this block is void.
```

### 10.8 Falsifiable acceptance criteria (outward)

Numbered separately from §6 so the two populations stay distinguishable. Each names the arm that
must be able to fail — a criterion with only a satisfiable arm is not a criterion.

- **AC-O1 — escalation COMPOSES, it never WIDENS.** After a caller is escalated from role A to role
  B, the reachable set equals `admitted(manifest_B) ∩ effective_scope(occupant_B)` exactly. Assert an
  item present in A's manifest and absent from B's is **not** reachable after the transfer — the
  grant did not accumulate. **The arm that must fire:** an item present in B and absent from A **is**
  reachable, otherwise a broken transfer that confers nothing passes the first assertion. Second arm,
  separately asserted: the prior conversation's transcript is reachable to B **only** if B's manifest
  admits its context class.
- **AC-O2 — role scope is enforced BEFORE model invocation.** Measured on the **retrieval** log, not
  the output. For a caller routed to a receptionist role, the set of context objects that entered the
  model's context is a subset of the public corpus. **The arm that must fire:** a prompt-level-only
  implementation goes RED — a forbidden object appears in the retrieval record even when it never
  appears in the emitted text. Without this arm the criterion is satisfied by a well-behaved model,
  which is exactly the thing that is not a boundary.
- **AC-O3 — every routing decision is witnessed, including refusals.** A routed escalation, a refused
  escalation, and an escalation whose target rung declined produce **three distinguishable** chain
  records, each carrying its reason. **The arm that must fire:** with the target stubbed unreachable,
  the record produced is not the record a refusal produces (`PRD_ADJUDICATOR_LADDER.md` AC-7's shape;
  a silent timeout that reads as "no objection" is the most dangerous failure this surface can have).
- **AC-O4 — no role routes its own escalation.** A route naming any role as the decider of
  `role.route.*` or `role.manifest.*` is REFUSED at write time, with the refusal naming the clause;
  the table returns a refusal, not a role id. Constructed like
  `no_rung_can_mutate_ladder_config` / `no_mcp_tool_can_mutate_standing_scope`. **The arm that must
  fire:** the same write with a non-governance `kind` succeeds, so a store that refuses everything
  does not pass.
- **AC-O5 — outward withholding does not disclose.** A caller refused a context class receives a
  response byte-identical to the response for a class that does not exist. **The arm that must fire
  is in the same test:** the corresponding INWARD withhold **does** name the class and the missing
  clearance (§3.2's `role_scope_withheld`). One test asserting both directions pins the §10.6
  asymmetry rather than leaving it as prose that a future implementer will "simplify" into symmetry.

### 10.9 Non-goals for §10

- **Not building the receptionist, the broker, or the presence.** This section states that the role
  object carries outward access; the hub's outward-context PRD is where the presence lifecycle,
  pairing, and transport live (GPT's note, §"Hub vs Hestia responsibility" — and this section does not
  disturb that split).
- **Not defining the context-label schema.** GPT's context-object attributes (provenance, subject,
  steward, sensitivity, citizenship floor, purpose tags, disclosure rules) land in this document's
  vocabulary as **classes** and their tier mapping. §7.1's taxonomy governs the spelling, and the
  outward side must not fork it — a class the hub spells differently is a flow-rule bypass or a
  permanent withhold, which is §7.1's whole argument, now with a caller behind it.
- **Not admitting cross-hub callers.** §7.2 keeps federated occupancy out of v0; an outward caller
  from a non-paired hub is withheld and disclosed *to the operator* (never to the caller, §10.6) on
  the same `accepted_occupancy_sources` mechanism.
- **Not populating any route table.** As with §7 and the ladder PRD: this section commits to the
  object and the invariant, not to a table of roles nobody has measured a need for.

## 11. R6/R7 envelopes — cross-reference

*(Numbered 11 because §10 — "The OUTWARD direction" — took the slot this section was written to
leave free for it. That section landed in #449 on 2026-08-15, so the §10 references below now
resolve against this same file rather than against a branch. Reconciled at merge by keeping
BOTH sections in numeric order.)*

**See `docs/PRD_R6_R7_ENVELOPES.md`** (dp-ruled, 2026-08-14): every governed act — compose, admit,
escalate, adjudicate — is carried in an R6/R7 envelope rather than in bespoke per-PRD structures.

What that amendment subsumes from **this** PRD, and where it does not:

- **§2's ROLE as the scope carrier is `ActionRole{actor_lct, role_lct, paired_at}`**
  (`web4-core/src/r6.rs:67-75`), under the invariant *"Role isolation: actions scoped to role's
  permissions"* (`r6.rs:16`). `r6.rs:66` states dp's ruling from the other side without having been
  written for it: *"Reputation is ROLE-CONTEXTUALIZED, never global."*
- **Two real limits on that row.** `ActionRole` carries no `occupancy_id` and no
  `manifest_generation`, which §3.2's derived entry and §3.4's stranding both need. And **the
  outward direction needs two parties where `ActionRole` names one** — §10.2's
  `reachable(caller, role) = admitted(manifest) ∩ effective_scope(occupant)` has no carrier.
  `ProofOfAgency` (`r6.rs:102-112`) is the wrong shape: an outward caller delegates nothing.
- **§2's proof tiers map PARTIALLY, and `min_atp` was dropped from that mapping.** T0/T1/T2 grade
  *evidence*, not *cost*; attaching an ATP minimum there would have been a forced mapping. T2's mesh
  witness quorum maps to `Reference.witnesses` (`r6.rs:124`); T2's operator co-sign and
  hardware-backed key do not (see the witness-standing gap above). T1's "fresh certified snapshot"
  has no carrier — `Request.deadline` (`r6.rs:92`) is the action's own deadline, not the evidence's.
- **§10.3's "nothing carries across an escalation but provenance" is `prev_action_hash`**
  (`r6.rs:360`) — a hash, not a payload, so it *cannot* carry the transcript. The most elegant
  correspondence in the family. Honest half: `Request.parameters` (`r6.rs:85`) is an open map and
  nothing forbids putting the transcript in it. The envelope makes non-carryover **auditable**, not
  **enforced**.
- **§10.6's escalation governor is `Constraint{min_atp}`, and `rate_limit` was dropped** — it exists
  only as a doc-comment string at `r6.rs:57` with no implementation anywhere in web4. dp's economic
  example is the implemented half.
- **§9.1's composite revision is `Rules.law_hash`** (`r6.rs:34`) plus two missing fields; the
  clearance/occupancy/manifest generations this PRD contributes still need a monotonic counter,
  because a hash cannot say which of two policies is *older* and §3.4's stranding depends on order.
- **§10's outward funding is RULED and is now design, not an open question.** `PRD_R6_R7_ENVELOPES.md`
  §4.4: a society-law-declared external-interaction budget bounded by three **independent**
  constraints — total ceiling × society-wide **nonlinear service-rate governor** (the bound that
  does not scale with identity count, and therefore the free tier's anti-sybil property) ×
  per-caller ceiling — with salience modulating *within* those envelopes and never raising one, and
  **citizenship as the boundary** past which callers fund themselves.
