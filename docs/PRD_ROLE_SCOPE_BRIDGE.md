# PRD — the role-scope bridge: hub-delegated scope to role, role-delegated to hestia

**Status**: proposed — dp-directed 2026-08-14; design PRD, not started; bridges hub<->hestia; builds
on #431's standing-scope surface.
**Author**: claude-code (CBP), 2026-08-14.
**Twin**: `web4/hub/docs/PRD_ROLE_SCOPE_BRIDGE.md` — the hub side of the same bridge. §2 (concepts)
is normative for BOTH documents; each side details only its own mechanics and defers to the twin for
the other half. Amend the shared concepts in both PRs or neither.
**Reframe folded in (dp, 2026-08-14)** — *"rather than rule on these, i want to add hooks for planned infrastructure."* §7's Q1–Q4 are no longer awaiting rulings: each is recast as an **extension point** with an initial best guess, a stored home, an operator-walled path to change it, and the measurement that would justify changing it. Q5 stays a question, with its precondition named (§7.5). §7.3 — the agent second factor — now states what would have to be true for an **adjudicator rung** to count as one. See **§7** and **§9**.
**Relates to**: `docs/PRD_ADJUDICATOR_LADDER.md` (the decider axis — §9 is the cross-reference and the shared-convergence contract), `docs/PRD_ALLOWLISTS.md` (the sibling authority; §12.1 carries the same composite contract), `PRD_GATE_CONSOLIDATION.md` (LAW/SHIM/AGENT, the one-authority-path invariant, ratified
degraded mode), PR #431 (the standing-scope store this bridge delivers through), `docs/GATE_SPRINT_F_NOTES.md`
R1/R3 (standing scope + launch-cwd grant — §3.6 subsumes R3), `web4/hub/docs/PRD_HUB_V2_FEDERATED.md`
R4 (roles as entities — the role manifest extends the R4 charter), CLAUDE.md's RWOA+S+V norm (§5.6).

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

## 11. R6/R7 envelopes — cross-reference

*(Numbered 11, not 10: §10 — "The OUTWARD direction" — is on the unmerged branch
`cbp/roles-are-the-outward-carrier` (`ff0c76d`). The slot is left free so both land without
collision. §10 references below resolve against that branch.)*

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
  §4.4: a society-law-declared external-interaction budget, three nested ceilings, salience
  modulation, and **citizenship as the boundary** past which callers fund themselves.
