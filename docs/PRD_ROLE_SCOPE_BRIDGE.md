# PRD — the role-scope bridge: hub-delegated scope to role, role-delegated to hestia

**Status**: proposed — dp-directed 2026-08-14; design PRD, not started; bridges hub<->hestia; builds
on #431's standing-scope surface.
**Author**: claude-code (CBP), 2026-08-14.
**Twin**: `web4/hub/docs/PRD_ROLE_SCOPE_BRIDGE.md` — the hub side of the same bridge. §2 (concepts)
is normative for BOTH documents; each side details only its own mechanics and defers to the twin for
the other half. Amend the shared concepts in both PRs or neither.
**Relates to**: `PRD_GATE_CONSOLIDATION.md` (LAW/SHIM/AGENT, the one-authority-path invariant, ratified
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

## 7. Open questions (declared RED until ruled)

1. **Class taxonomy governance.** Who defines the class vocabulary and tier mapping — hestia
   operator law, hub law, or a shared ratified list? A class both sides spell differently is a
   flow-rule bypass or a permanent withhold; the taxonomy needs one authoritative home and a
   compatibility rule for federation (the twin's Q1 is the same question from the hub side).
2. **Cross-hub occupancy.** A member conferred a role by a *federated* hub (R1/R2 edge): does the
   flow rule consume it at all, and if so does it demand edge-scoped law compatibility
   (federated-PRD R6) plus a higher tier? Recommendation: out of v0; local-hub occupancies only.
3. **What is a second factor for an agent member?** Candidates: session key + operator co-sign
   (human in the loop — the only one that clearly satisfies T2 today); mesh witness quorum (k
   distinct constellation members co-witness the act — but a quorum of same-host processes is one
   factor wearing k hats); hardware-backed key (TPM/AttestationEnvelope — strongest, least
   available). Needs a ruling before any class maps to T2-without-operator.
4. **Reputation interaction.** Should clearance approval require/consume T3 evidence (e.g. a
   temperament threshold in the role's context), or is reputation only advisory to the operator's
   decision? Web4 doctrine says evidence-in, verdict-with-the-relying-party — recommendation:
   surface T3 beside the ask, never auto-decide.
5. **Withheld-item ergonomics.** Does a `role_scope_withheld` witness auto-open a clearance ask for
   the operator, or is that escalation-noise (the known approve→re-issue loop-close gap applies)?

## 8. Non-goals

- No new authority path, no new transport — this rides #431's store, the membrane, and the
  existing operator gate.
- No hub writing hestia state, ever; no hestia writing hub state.
- No auto-approval of clearances from reputation, occupancy pressure, or role need.
- No re-design of the gate's decision topology, the vault, or the R2 path-grant model — this PRD
  consumes them and names them where it depends on them.
