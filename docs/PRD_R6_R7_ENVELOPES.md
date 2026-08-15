# PRD — the R6/R7 ENVELOPE: one carrier for every governed act

**Status**: proposed — dp-directed 2026-08-14. Unifying amendment to the PRD family
(`PRD_ALLOWLISTS.md`, `PRD_ROLE_SCOPE_BRIDGE.md`, `PRD_ADJUDICATOR_LADDER.md`). Docs-only; no code
in this PR.
**Author**: claude-code (CBP), 2026-08-14.
**Ground truth**: `web4/web4-core/src/r6.rs` (the canonical implementation, read in full),
`web4/web4-core/src/atp.rs`, `web4/web4-policy/src/lib.rs`, `web4/web4-standard/R6_TENSOR_GUIDE.md`.
Every R6/R7 claim below carries `file:line` **against the web4 checkout at
`../web4` on 2026-08-14**. Per `fb_line_cite_pinned_checkout`, line numbers are pinned to that
checkout; the construct names are the durable identifiers.

---

## 0. The ruling (dp, 2026-08-14) — VERBATIM, and it is the spec

> "the key is to wrap all these acts in r6/r7 envelopes - that automatically folds in the full web4
> structure, including resource caps (can only escalate if you're willing to invest sufficient atp
> in the process, for example)"

Everything below is construction detail for that paragraph. Where this document and §0 disagree,
§0 wins.

**Three further rulings of the same day** answered what this document had initially flagged as the
load-bearing outward question. They are carried verbatim in **§4.4.0** (the external-interaction
budget, and its per-caller/per-call/salience shape) and **§4.4.7** (citizenship as the boundary
between the free tier and self-funded interaction). They have the same standing as §0.

---

## 1. The claim

`compose`, `admit`, `escalate`, `adjudicate` are all **actions**. Web4 already has a canonical
action envelope, and it already declares as typed data most of the fields these three PRDs spent
2026-08-14 re-deriving in prose.

```
R6:  Rules + Role + Request + Reference + Resource → Result                    (r6.rs:6)
R7:  Rules + Role + Request + Reference + Resource → Result + Reputation       (r6.rs:7)
```

> "R6 is for low-consequence actions (cheap). R7 adds explicit reputation tracking for
> consequential actions. Both are canonical; R7 extends R6." — `r6.rs:9-10`

The stated invariants (`r6.rs:12-17`, verbatim):

- **Determinism**: same inputs → identical results across implementations
- **Non-repudiation**: all actions signed, recorded with witnesses
- **Resource bounds**: consumption cannot exceed pre-declared limits
- **Role isolation**: actions scoped to role's permissions
- **Atomic settlement**: transfers and tensor updates fully complete or roll back

**Wrapping is not extra structure — it removes structure.** Today the ceremony tier, the proof
tier, the evidence bundle and the verdict record are four bespoke shapes in three documents, each
of which must independently remember to say "and it is witnessed", "and it is hash-pinned to the
law", "and the resource is bounded". Under the envelope those are properties of the carrier, stated
once, in one place, in code that already exists.

**Two honest qualifiers on that claim, stated here rather than buried in §6**, because the whole
document is worth less if the reader discovers them later:

1. **Three of the five invariants are doc comments with no enforcing code in `r6.rs`.**
   `validate()` (`r6.rs:402-443`) checks permissions, ATP sufficiency, `min_atp` and
   `witness_quorum` — and nothing else. "Resource bounds: consumption cannot exceed pre-declared
   limits" (`r6.rs:15`) has **no code anywhere** comparing `ActionResult.atp_consumed`
   (`r6.rs:196`) against `ResourceRequirements.required_atp` (`r6.rs:155`). "Atomic settlement"
   (`r6.rs:17`) has no settlement code: `ATPAccount::{lock, commit, rollback}`
   (`atp.rs:60,76,87`) exists but `R7Action` holds `available_atp: f64` (`r6.rs:157`) — a **copy of
   a balance, not a handle to an account**. Wrapping inherits the *shape* of these invariants and
   the obligation to implement them; it does not inherit the invariants themselves.
2. **There is no R6 engine.** Grepping the whole web4 tree for `R7Action` outside `r6.rs` and
   vendored `target/package` copies returns exactly two consumers: the re-export in
   `web4-core/src/lib.rs:99` and a WASM binding wrapper (`web4-trust-core/src/bindings/wasm.rs:775`).
   Nothing in the fleet constructs, executes or settles an `R7Action`. The envelope is a
   **declared schema with one struct and a validator**, not a running framework. That is still the
   right thing to adopt — a shared schema is exactly what stops three documents drifting — but
   "inherits by construction" overstates it. It inherits *by declaration*, and the construction is
   work this PRD is asking for.

Both qualifiers argue *for* adoption rather than against it: an unimplemented invariant in one
canonical place is fixable once; four documents each re-asserting it in prose is not.

---

## 2. The mapping — corrected against source

Every R6/R7 side carries `file:line`. Every PRD side carries a section ref. Rows that did not
survive the check are marked and the correction is stated, because **a forced mapping is worse than
an honest gap**.

### 2.0 A ref correction that has to come first

The thesis cited `PRD_ROLE_SCOPE_BRIDGE.md` §10.0/§10.3/§10.6. **§10 does not exist on `main`** —
`docs/PRD_ROLE_SCOPE_BRIDGE.md` on `origin/main` (`e9aa04a`) ends at §9.1, 456 lines. §10 (*"The
OUTWARD direction"*) lives on the **unmerged** branch `cbp/roles-are-the-outward-carrier`
(`ff0c76d`, *"docs: roles are the outward carrier — §10 of the role-scope bridge"*).

The same applies to `PRD_ADJUDICATOR_LADDER.md` **§13** (*"RUNGS ADMIT. RUNGS DO NOT COMPOSE."*),
which §4.4 leans on heavily: it is **not on `main`** either, but on the unmerged branch
`cbp/ladder-admits-never-composes` (`6a14bbf`).

This is not pedantry, it is `fb_ref_part_predicate`: a ref floats on repo state, and three of the
nine thesis rows — plus §4.4's whole COMPOSE/ADMIT frame — resolve only against branches that have
not landed. Rows citing §10 are marked **[branch ff0c76d]**; citations of §13 are marked **[branch
6a14bbf]**. If either branch closes without merging, those citations lose their PRD side — see
`fb_gh_pr_list_hides_closed`, which records that "never routed" and "operator ruled against it" read
alike.

### 2.1 The rows

| # | PRD construct | R6/R7 carrier | verdict |
|---|---|---|---|
| 1 | ceremony tier (`PRD_ALLOWLISTS` §3.6.2) | R6-vs-R7 selection (`r6.rs:9-10`, `is_r7()` `r6.rs:397`) + `Constraint{witness_quorum}` (`r6.rs:57`, enforced `r6.rs:431-439`) | **PARTIAL — corrected** |
| 2 | proof tiers T0/T1/T2 (`PRD_ROLE_SCOPE_BRIDGE` §2) | `Constraint{witness_quorum}` + `Reference.witnesses` (`r6.rs:124`) | **PARTIAL — `min_atp` DROPPED** |
| 3 | the ladder's evidence bundle (`PRD_ADJUDICATOR_LADDER` §3.3) | `Reference{precedents, mrh_depth, relevant_entities, witnesses}` (`r6.rs:115-125`) | **PARTIAL — misattributed; see 3a/3b** |
| 4 | hash-pinned law consultation (ladder §3.3, §6.3 AC-L4) | `Rules.law_hash` (`r6.rs:34`) | **HOLDS — cleanest row in the table** |
| 5 | escalation rate-bounding / anti-probing-oracle (role §10.6) **[branch ff0c76d]** | `Constraint{min_atp}` (`r6.rs:57`, enforced `r6.rs:423-430`) — **`rate_limit` dropped** | **HALF-HOLDS — dp's half is the real one** |
| 6 | "nothing carries across an escalation but provenance" (role §10.3) **[branch ff0c76d]** | `prev_action_hash` (`r6.rs:360`) + a fresh `ActionRole` (`r6.rs:67-75`) | **HOLDS in shape, NOT in enforcement** |
| 7 | agent-rung promotion measurement (ladder §4.3) | `ReputationDelta` (`r6.rs:283-320`) / `is_r7()` | **PARTIAL — grain mismatch** |
| 8 | ADMIT: "every layer narrows, ceilings never unioned away" (role §10.3, allowlists §2.2) | invariant `r6.rs:15` + `Rules.prohibitions` (`r6.rs:42`) | **REFUTED AS STATED — `Rules` is absence-means-unrestricted** |
| 9 | roles as the scope carrier (role §10.0/§10.1) **[branch ff0c76d]** | invariant `r6.rs:16` + `ActionRole.role_lct` (`r6.rs:71`) | **HOLDS inward; does NOT carry outward** |
| 10 | *(added)* rung `decline` incl. timeout/unreachable (ladder §3.2) | `DeltaClass::{Conduct, Infra, Unclassified}` (`r6.rs:262-270`) | **HOLDS — and hestia already ships it** |
| 11 | *(added)* escalation expiry / AC-L7 (ladder §6.4) | `Request.deadline: Option<Deadline>` (`r6.rs:92`) | **HOLDS — and nothing in hestia uses it** |
| 12 | *(added)* `Verdict.consulted` — what the rung ACTUALLY read (ladder §3.1 note 4) | **none** | **GAP (a) — genuine extension** |

### 2.2 Row-by-row, with the corrections

**Row 1 — ceremony tier. Corrected: `witness_quorum` carries the CARDINALITY of a ceremony, never
its COMPOSITION.**

`Constraint` is `{constraint_type: String, threshold: f64, hard: bool}` (`r6.rs:55-63`) and the
`witness_quorum` check is a pure count: `(self.reference.witnesses.len() as f64) < threshold`
(`r6.rs:432`). §3.6.2's tier table is not a count table — tiers 0/1/2 differ by **which identities**
supply the evidence (`operator-only` / `operator-plus-witness` / `sovereign-plus-peer`), and only
tier 3 (`quorum`, "N-of-M named identities") is cardinal. `WitnessAttestation` (`r6.rs:139-149`)
carries `{lct, attestation, signature, timestamp}` — **no field naming the witness's standing**. So
"a corroborating *peer*" and "a designated *observer*" are the same value to this constraint.

- **Gap (a) — genuine extension web4 should absorb:** a constraint predicate over witness *class*,
  not just count. The nearest existing thing is `SovereignStrength{Placeholder, Hardware}`
  (`r6.rs:235-243`) — but it lives on `ReputationDelta` (`r6.rs:293`), which is the R7 **output**.
  The strength axis exists in web4 and is attached to the wrong object for this use.
- **Also gap (a):** §3.6.3's asymmetric ratchet (*"lowering the tier from N requires satisfying tier
  N"*) has **no carrier at all**. Nothing in `r6.rs` relates an action that changes rules to the
  rules being changed. `Rules.has_permission` (`r6.rs:46-52`) is a flat membership test; the
  self-protecting-registration property is not expressible.

What *does* hold, and it is the useful half: `is_r7()` (`r6.rs:397`) is a consequence declaration
on the act, and §3.6.5's table returns a **refusal, not a number** for `governance.*` — which maps
exactly onto `Rules.prohibitions` (`r6.rs:42`), where `has_permission` short-circuits false before
looking at anything else (`r6.rs:47-49`).

**Row 2 — proof tiers. `min_atp` DROPPED from this row.** T0/T1/T2 (§2, the table at
`PRD_ROLE_SCOPE_BRIDGE.md:78-82`) are graded by *evidence*, not by *cost*: session identity → fresh
certified snapshot → second factor. There is no ATP in the proof-tier story, and attaching
`min_atp` here would be a forced mapping that made the ATP argument (§4) look broader than it is.
`Reference.witnesses` genuinely carries T2's *mesh witness quorum* alternative; T2's *operator
co-sign* and *hardware-backed key* alternatives do not have carriers (see row 1's gap). T1's
*"unexpired #431 horizon"* has no carrier — `Request.deadline` (`r6.rs:92`) is the **action's own**
deadline, not the **evidence's** freshness. See §5 for what that costs.

**Row 3 — the evidence bundle. Misattributed in two directions; split into 3a and 3b.**

The thesis put the whole bundle under `Reference`. Checked line by line against §3.3's nine-row
table, it distributes across three components and leaves two rows homeless:

| §3.3 bundle element | actual R6 carrier |
|---|---|
| the act (`tool_name`, `marker`, `stated_detail`) | `Request{action, target, parameters}` (`r6.rs:79-85`) — **not `Reference`** |
| the asker's stated reason | `Request.parameters` (untyped `HashMap`, `r6.rs:85`) |
| the asker's basis (`Session` vs `Asserted`) | `Request.proof_of_agency: Option<ProofOfAgency>` (`r6.rs:98`, type `r6.rs:102-112`) — **weak**: `ProofOfAgency` models *delegated* agency with a grant id and inclusion proof, not the session-vs-assertion distinction `arbiter.rs` clause 0 reads |
| the law snapshot, hash-pinned | `Rules.law_hash` (`r6.rs:34`) — **holds** |
| the member's history | `Reference.precedents: Vec<Precedent>` (`r6.rs:118`), `Precedent{action_hash, outcome, relevance}` (`r6.rs:128-136`) — **holds** |
| prior decisions on the same marker | `Reference.precedents` — **holds** |
| the refusal text + which RULE fired | **none on the input side.** `ReputationDelta.rule_triggered` (`r6.rs:307`) exists but is an R7 **output** field |
| the existing factor set, with dissent and `independence` grade | `Reference.witnesses` (`r6.rs:124`) carries stance as free text in `WitnessAttestation.attestation` (`r6.rs:144`) — but **there is no independence-grade field**, so `arbiter::eligibility_for`'s `CrossVendor`/`CrossMember` grade has no carrier |
| the bar in force | `Rules.constraints` (`r6.rs:38`) — **holds** |

And the mapping is **not onto in the other direction either**: `Reference.mrh_depth` (`r6.rs:120`)
and `Reference.relevant_entities` (`r6.rs:122`) have no counterpart in §3.3's bundle. That is not a
defect — it is the envelope offering two fields the ladder has not yet thought to use, and
`mrh_depth` in particular is the natural home for §10.2's *"purpose/MRH"* field.

- **3a — gap (a), genuine extension:** an `independence` grade on `WitnessAttestation`. Without it,
  §5.1's NOT-SAME rules and §7.3's *"one factor wearing k hats"* argument are unrepresentable in the
  record, and the ladder's anti-capture claim is prose again.
- **3b — gap (a), and it is the sharpest one in the document:** **row 12.** §3.1 note 4 makes
  `consulted` — *what the rung actually read, not what it was offered* — the whole auditability of
  a rung: *"A rung that received the full bundle and read the tool name is a filter wearing an
  adjudicator's clothes."* `Reference` is **what was offered**. R6 has **no field for what was
  read**. This is not a hestia invention that web4 should absorb grudgingly; it is a general
  property of any adjudicated action and web4 lacks it.

**Row 4 — hash-pinned law. HOLDS, unqualified.** `Rules.law_hash: String` (`r6.rs:34`), documented
as *"SHA-256 of the governing law document"*, alongside `Rules.society` (`r6.rs:36`). AC-L4 requires
the hash on the **verdict**; in the envelope the verdict and the act are one `R7Action`, so
"carried within the decision, not cached across decisions" is satisfied by construction rather than
by discipline. §6.3's *"remembered policy is folklore"* becomes a schema property.

**Row 5 — the escalation governor. HALF-HOLDS, and the correction strengthens dp's ruling.**

`min_atp` is real: declared at `r6.rs:57` and **enforced** at `r6.rs:423-430`. `rate_limit` is
**not**: `grep -rn "rate_limit" web4-core/` returns exactly one hit, the doc comment at `r6.rs:57`
that names it as an example. There is no `rate_limit` branch in `validate()` (`r6.rs:422-440`) and
no implementation anywhere in the tree. **The row is corrected to `Constraint{min_atp}` alone.**

This matters more than a footnote: the thesis offered a *bespoke rate limiter* and an *economic
governor* as two carriers for the same requirement. Checked against source, the economic one is the
one that exists and the rate limiter is a string in a doc comment. **dp's example is the implemented
half, and the half the thesis added is the vapour.** §4 builds on the real one.

One enforcement asymmetry, noted because it will bite whoever writes the constraints: the `min_atp`
check fires **only when `constraint.hard` is true** (`r6.rs:423`), while `witness_quorum` fires
**regardless of `hard`** (`r6.rs:431`). A "soft" witness quorum blocks; a "soft" ATP minimum does
not. That is a web4-core inconsistency, not a hestia one, and it should be fixed there.

Also unmapped: §10.6's third requirement — *"the refusal text must not disclose the role that was
not reached"*. `ActionResult.error: Option<String>` (`r6.rs:194`) is one free-text field on one
record, and the record **is** the audit trail. Nothing in the envelope distinguishes what is
*recorded* from what is *returned to the caller*. §10.6's inward/outward disclosure asymmetry
(*"withheld items are disclosed to MEMBERS and never to CALLERS"*) is therefore **gap (a)** —
genuine, and load-bearing for the outward direction.

**Row 6 — provenance-only carryover. HOLDS in shape; does NOT hold as enforcement.**

`prev_action_hash: String` (`r6.rs:360`) is *a hash, not a payload* — it links the escalated act to
its predecessor and **cannot carry the transcript**, by construction. That is exactly §10.3's rule,
and it is the most elegant correspondence in the table. The escalated act also gets a fresh
`ActionRole` (`r6.rs:67-75`) with a new `role_lct` — a role transfer, not a widening, expressed as
data.

The honest half: §10.3's provenance list is *{caller identity, standing, prior role LCT, prior
grant id, stated reason}*, and a hash carries none of those — they would go in
`Request.parameters`, which is an **open** `HashMap<String, serde_json::Value>` (`r6.rs:85`).
Nothing in R6 forbids putting the transcript in it. **The envelope makes non-carryover expressible
and auditable; it does not make it enforced.** Stating otherwise would be the "shipped ≠ in force"
failure with a schema in place of a deploy.

**Row 7 — promotion measurement. PARTIAL, grain mismatch.** §4.3's criterion is *"agreement rate
with the human decision, over N decisions, per act kind, with disagreements preserved"* plus a
non-zero dissent rate. `ReputationDelta` is **per action** (`r6.rs:283-320`); the criterion is a
**fold over many actions**, and no such fold exists in `r6.rs`. The T3 dimensions the helper writes
are `talent`/`training`/`temperament` (`r6.rs:494`) — none of which is "agreement with the
operator". `ContributingFactor{factor_type, weight, description}` (`r6.rs:217-222`) is where a
per-decision agreement observation could ride, and `contributing_factors` (`r6.rs:315`) is its home
on the delta. So: **the envelope carries the evidence; the promotion criterion is a fold that does
not exist, and §4.3's own warning applies** — *"an advisory rung that is never measured never earns
promotion."* Promotion also remains an **operator act at the ladder's ceremony tier** (§4.3, §5.3),
never a reputation threshold the system crosses on its own; R7 has no promotion mechanism and
should not acquire one.

**Row 8 — ADMIT. REFUTED AS STATED. Read this row before wrapping anything.**

Three independent problems:

1. **`Rules` is absence-means-unrestricted.** `has_permission` (`r6.rs:46-52`) reads:
   ```rust
   if self.prohibitions.iter().any(|p| p == action || p == "*") { return false; }
   self.permissions.is_empty() || self.permissions.iter().any(|p| p == action || p == "*")
   ```
   **An empty `permissions` list allows every action.** That is the exact inverse of ADMIT's
   "every layer narrows", and it is the same absence-means-unrestricted shape `PRD.md:407` already
   records as a defect in this repo. A naive wrapping that built `Rules` from a layer that
   contributed no permissions would **widen**. `prohibitions` narrows; `permissions` does not.
2. **There is exactly ONE `Rules` per `R7Action`** (`r6.rs:341`). ADMIT is an intersection **over
   layers** — society / role / instance / innate / floor. Flattening them into one `Rules` loses
   which layer contributed which constraint, and `PRD_ALLOWLISTS.md` §2.2's whole claim is that
   composition must be auditable **by inspection rather than by simulation**. A flattened `Rules`
   can only be audited by simulation.
3. **The invariant it was mapped to has no code.** "Resource bounds: consumption cannot exceed
   pre-declared limits" (`r6.rs:15`) is never enforced: `atp_consumed` (`r6.rs:196`) is never
   compared to `required_atp` (`r6.rs:155`) anywhere.

**Disposition: gap (a), genuine extension**, and a specific one — either a layered `Rules`
(`Vec<Rules>` intersected, with per-layer provenance) or a `provenance` field per `Constraint`. Plus
a fix in web4-core: `permissions.is_empty()` should fail **closed**, or the emptiness case should be
a distinct explicit variant rather than an implicit allow-all. This row is the one place where the
thesis's mapping, taken literally, would have made hestia **less** safe.

**Row 9 — roles as the scope carrier. HOLDS inward; does NOT carry the outward direction.**

`ActionRole{actor_lct, role_lct, paired_at}` (`r6.rs:67-75`) is precisely "who + in what capacity",
and its own doc comment (`r6.rs:66`) — *"Reputation is ROLE-CONTEXTUALIZED, never global"* — is the
same claim §10.1 makes from the other side. dp's ruling and web4's canonical action envelope agree
without either having been written for the other, which is the strongest evidence the frame is
right.

Two real limits:

- `ActionRole` has no `occupancy_id` and no `manifest_generation`. §3.2's `role_derived` entry needs
  both, and §3.4's stranding-on-generation-bump depends on the generation being *on the act*.
  **Gap (a)** — small, and the natural home is `ActionRole`.
- **The outward direction needs TWO parties and `ActionRole` names one.** §10.2's bound is
  `reachable(caller, role) = admitted(manifest_role) ∩ effective_scope(occupant_of(role))`. R6 has
  one actor. `ProofOfAgency` (`r6.rs:102-112`) is the nearest candidate and it is the **wrong
  shape**: it models an agent acting *on behalf of* a principal who delegated to it. An outward
  caller delegates nothing — the presence is not the caller's agent, it is the society's. **Gap
  (a), and it is the structural gap for the outward PRD.** Hub's PRD should not paper over this
  with `ProofOfAgency`.

**Row 10 (added) — decline vs failure. HOLDS, and hestia already ships the hard part.**

§3.2 makes transport failure, timeout and unreachability **declines**, recorded distinguishably,
citing `ref_mesh_undelivered_echo`. `DeltaClass{Conduct, Infra, Unclassified}` (`r6.rs:262-270`) is
exactly that distinction on the reputation axis, with a fail-closed default of `Unclassified`
(`r6.rs:272-277`) that is *held, never applied*. Its doc comment names the measured failure it
prevents: *"hestia PR #357 class: infrastructure fail-closed denies scored as member conduct."*
hestia's `RepContext.class` (`core/src/reputation.rs:79`) already carries it from the caller and
refuses to infer it. **This row is the proof the frame is not aspirational** — the one place the two
codebases already meet is the one place the semantics are right.

**Row 11 (added) — `Request.deadline`.** `Option<crate::time::Deadline>` (`r6.rs:92`), documented as
*"the temporal twin of `atp_stake`"*. AC-L7 (*"no escalation routed to a live rung expires
PENDING"*) is a statement about exactly this field. Nothing in hestia uses it.

---

## 3. R6-vs-R7 **is** the consequence axis we have been re-inventing

Three constructs across the family resolve on the same key:

| construct | signature | source |
|---|---|---|
| ceremony tier | `required_tier(kind, society_consequence) -> Tier` | `PRD_ALLOWLISTS` §3.6.5 |
| rung list | `rungs_for(kind, consequence) -> [RungId]` | `PRD_ADJUDICATOR_LADDER` §2.3 |
| proof tier | class → T0/T1/T2 | `PRD_ROLE_SCOPE_BRIDGE` §2 |

All three PRDs already agree they must share **one `kind` vocabulary** (allowlists §12, role §7.1,
ladder §2.3), on the argument that *"three vocabularies for 'what kind of act is this' would drift
with no surface on which to notice."*

**R6-vs-R7 is that consequence distinction, already canonical, already carrying its own reputation
semantics.** `r6.rs:9-10` states it in one sentence, and `is_r7()` (`r6.rs:397-399`) is the whole
implementation: `self.reputation.is_some()`.

**Proposal.** Make `kind × consequence → R6 | R7` the **single selection**, and key everything else
off the envelope rather than off parallel tables:

```
select(kind, consequence) -> R6 | R7        # the one classification
    ↓
R6  →  no ReputationDelta, cheap path, low-consequence
R7  →  ReputationDelta REQUIRED, and the required Constraints ride Rules.constraints
```

- The **ceremony tier** becomes the `Vec<Constraint>` populated on `Rules` (`r6.rs:38`) for a given
  selection, not a parallel enum. Tier 3 (`quorum`) is literally `Constraint{witness_quorum, N}`.
  Tiers 0–2 need the witness-class extension of row 1 before they are fully expressible — say so
  rather than pretending the table is complete.
- The **rung list** becomes a route resolved on the same selection, and a rung's `max_consequence`
  (§3.2) becomes *"this rung may decide R6 acts, not R7 acts"* — one comparison instead of a second
  scale.
- The **proof tier** becomes the constraint set the selection attaches, which is what §2's table
  already is once its rows are read as evidence requirements rather than as a rank.

**Two things this does NOT collapse, stated so the proposal is falsifiable:**

1. **R6/R7 is binary; the family's consequence axis is ternary** (`low` / `med` / `high` in the
   ladder sketch at §2.2, `research-single-host` / `multi-seat` / `hub-occupied` in allowlists
   §3.6.5). Either the family narrows to two, or the selection is
   `kind × consequence → (R6|R7, Constraint[])` where the constraint vector carries the finer grade.
   **Recommend the latter**, because the grade is genuinely finer than "does this move reputation"
   and forcing it binary would lose information the ladder's `max_consequence` needs.
2. **`governance.*` and `ladder.*` return a REFUSAL, not a value** (allowlists §3.6.5, ladder §5.3).
   A selection function that always returns an `R6|R7` cannot express that. `Rules.prohibitions`
   (`r6.rs:42`) is the carrier — the refusal is "this action is prohibited outright", which
   `has_permission` short-circuits at `r6.rs:47-49`. That works, and it is worth noting the
   envelope got the shape right: a prohibition is not a very high price, it is the absence of a
   price. Per §4.4.6, budget ceilings join that refusal set.

### 3.1 The per-call limit gives the selection a RESOURCE reading

§4.4's per-call limit supplies a second, independent way to read the same selection: **a trivial
exchange is an R6 action** (cheap, no reputation tracking) **and a consequential one is R7**. Checked
against source, this **holds — as a correlation, not an identity**, and the distinction is worth
keeping:

- It holds because `r6.rs:9-10` says exactly this: *"R6 is for low-consequence actions (cheap). R7
  adds explicit reputation tracking for consequential actions."* Cost and consequence are named in
  one sentence.
- It is reinforced by `R6_TENSOR_GUIDE.md:282-283` — *"Reputation Requires Proof: Cannot claim
  reputation without ADP from actual work"* — so a trivial exchange that discharges near-zero ATP
  **could not earn meaningful reputation anyway**. The two readings are consistent by construction
  rather than by coincidence.
- It is **not an identity** because "cheap" is the parenthetical in `r6.rs:9`, not the definition.
  A cheap-but-consequential act (a one-token instruction that mutates governed state) would break
  the identification, and a design that selected R6/R7 *by price* rather than *by consequence* would
  mis-file exactly that class. **Select on consequence; read cost as strongly correlated evidence.**

The useful consequence for §4.4.5: an exchange terminated early for low salience is an R6 action
that never becomes R7, which means the cheap-to-refuse path is also the path that costs nothing on
the reputation axis. That is the right alignment — refusing a probe should not be an event in
anyone's trust history.

---

## 4. ATP as the escalation governor — dp's example, made concrete

> "can only escalate if you're willing to invest sufficient atp in the process, for example"

### 4.1 The construction

An escalation is an act. Wrapped, it carries:

```
Rules.constraints  += Constraint { constraint_type: "min_atp",  threshold: T, hard: true }
                                                            # r6.rs:55-63, enforced r6.rs:423-430
Request.atp_stake   = S                                     # r6.rs:87  — the staked energy
ResourceRequirements {
    required_atp:     R,                                    # r6.rs:155
    available_atp:    A,                                    # r6.rs:157 — checked r6.rs:166-170
    escrow_amount:    E,                                    # r6.rs:161
    escrow_condition: "escalation_upheld",                  # r6.rs:163
}
```

`validate()` (`r6.rs:402-443`) refuses the act on two independent grounds: insufficient ATP
(`A < R`, `r6.rs:414-419`) and stake below the declared minimum (`S < T`, `r6.rs:423-430`). Both are
**pre-declared** and both are **on the record**.

### 4.2 The four consequences, stated

1. **Escalation becomes self-limiting by economics, not by a bespoke rate limiter.** This is the
   corrected row 5: `rate_limit` does not exist in code, `min_atp` does. §10.6 asks for
   rate-bounding; the answer web4 actually implements is a price, and a price is the better answer
   anyway — it bounds *volume* and *frivolity* with one mechanism, and it does not need a window,
   a clock, or a decision about whose clock (`ref_cbp_clock_10pct_fast`).
2. **A probing-oracle attack costs the prober.** §10.6's probing weapon works by *repetition* —
   learning the manifest boundary from which escalations are accepted. Under a per-escalation stake
   the map costs `N × T` to draw. It does not become impossible; it becomes **budgeted, and the
   budget is the attacker's**. Note honestly what this does *not* fix: the refusal-text asymmetry
   (§10.6's *"the refusal must not disclose the role that was not reached"*) is an
   information-leak rule and no price closes it. Two separate defences, both needed.
3. **Escrow makes a frivolous escalation FORFEIT rather than merely be refused.** This is the
   qualitatively new thing and it needs its cost stated exactly. `escrow_condition` (`r6.rs:163`) is
   a `String` with **zero consumers** — `grep -rn escrow_condition web4-core/src web4-trust-core/src
   web4-policy/src` returns the struct field, one test (`r6.rs:582`) and one doc example. The
   settlement primitives exist on the *account*: `ATPAccount::lock` (`atp.rs:60`) moves
   available→locked, `commit` (`atp.rs:76`) moves locked→ADP (discharged), `rollback` (`atp.rs:87`)
   moves locked→available (refunded). **`commit` is forfeiture-shaped** — the stake discharges to
   ADP without work — and `R6_TENSOR_GUIDE.md:282` supplies the reason it is the right verb:
   *"Reputation Requires Proof: Cannot claim reputation without ADP from actual work."* A forfeited
   escrow is discharged ATP that earns nothing. **What is missing is not the verb; it is (i) an
   evaluator for `escrow_condition` and (ii) any binding between `R7Action` and an `ATPAccount` —
   `available_atp` is a copied float (`r6.rs:157`), not a handle.** Escrow forfeiture is a field and
   two primitives that have never been wired to each other.
4. **The cost is auditable because it is in the action record.** `ActionResult.atp_consumed`
   (`r6.rs:196`) and `resource_consumed` (`r6.rs:198`) sit inside the same signed, hash-chained
   `R7Action` (`canonical_hash`, `r6.rs:446-459`) as the decision. This directly answers
   `fb_spend_invisible_spender` — the spend and the act it paid for are one record. Caveat, per
   §1's first qualifier: nothing today *writes* `atp_consumed`, and nothing compares it to
   `required_atp`. The field is the right field; the enforcement is the ask.

### 4.3 The measured starting distance

`core/src/policy/law_gate.rs:114-119` already constructs a `web4_policy::R6Request`
(`web4-policy/src/lib.rs:548`) for every gate evaluation:

```rust
let req = R6Request {
    role: role.to_string(),
    action: pa.tool_name.to_string(),
    payload: law_payload(pa),
    resource: Default::default(),          // ← EMPTY
};
```

`R6Request::resolve_selector` (`web4-policy/src/lib.rs:558`) resolves `r6.resource.<key>` out of
that map (`lib.rs:583-586`). **So hub law can already write a norm selecting on `r6.resource.atp`,
and it will resolve to `None` on every evaluation, forever, because hestia supplies an empty map.**
That is the honest starting point for §4: the selector exists, the law can name it, and the value
is absent. Populating that map is the smallest possible first step and it is *one struct literal*.

### 4.4 The OUTWARD budget — RULED

The question this section previously flagged (*"who pays for an outward caller's escalation, when
the caller has no ATP in this society?"*) was ruled on the same day, twice. Both rulings are below,
verbatim, and both are design rather than open questions.

#### 4.4.0 The rulings (dp, 2026-08-14) — VERBATIM

**First**, the source of funds:

> "the answer is that a society may choose, by its own law, to dedicate certain amount of atp to
> external interaction. every org carries a public relations cost, it is an ultimately beneficial
> function. but it has a very specific budget."

**Second**, the shape:

> "ultimately that's up to society's law but the template should have a per-caller and per-call
> limit, modified by salience (important things get more allocation, trivial ones get shut down
> early)."

**Third**, the boundary (carried in full at §4.4.7, where its consequences are worked out):

> "the per-caller and per-call limits should address that for the most part. external caller is the
> 'free tier', those who want to escalate for cause would have to gain citizenship to prove they
> merit the resource, and spend their own atp doing it. those not willing, prove it wasn't salient
> enough :)"

Outward interaction is funded from a **society-level, law-declared external-interaction budget** —
the machine form of an organisation's public-relations cost. **Not** the caller's ATP (they have
none here), **not** the reaching role's operating capital, **not** ad-hoc sponsorship.

#### 4.4.1 It lives in law, therefore in `Rules`

The budget is a society-law parameter, so its home is `Rules{law_hash, society, constraints}`
(`r6.rs:31-43`): `Rules.society` (`r6.rs:36`) names the society whose pool is being drawn, and an
outward act's `Rules.constraints` (`r6.rs:38`) carries the draw. Changing the budget is a **law
amendment** — due process, ceremony-tiered per `PRD_ALLOWLISTS.md` §3.6 — not an operator
convenience, and per row 4 it moves `law_hash` (`r6.rs:34`) like any other authority, so every
outward act is pinned to the budget in force when it happened.

#### 4.4.2 THREE nested envelopes, not one pool — and `Constraint` cannot express them

```
society external-interaction budget   ⊇   per-caller limit   ⊇   per-call limit
```

Each is a ceiling and **none may widen another**. This is not budget-specific language and must not
become any: it is **ADMIT's narrowing rule applied to resource**, and the vocabulary already exists
— `PRD_ADJUDICATOR_LADDER.md` §13.6 **[branch 6a14bbf]** states the algebra, and the term the
budgets occupy is already named in it:

```
effective_access(act) = composed_capabilities ∩ caller_standing ∩ pair_mrh
                        ∩ resource_context_policy ∩ hub_law ∩ … ∩ innate_invariants
```

The three budget levels are `resource_context_policy`. §13.6's rule 2 — *"no composed grant may
union past a ceiling owned by another layer"* — is exactly why a per-caller allocation cannot be
enlarged by anything downstream of it.

**Checked against source: `Constraint` cannot express this, and saying so is worth more than
forcing the mapping.**

`Constraint{constraint_type: String, threshold: f64, hard: bool}` (`r6.rs:55-63`) is a **static
threshold compared against a value carried on the action**. Both implemented checks have that shape:
`min_atp` compares `request.atp_stake` against `threshold` (`r6.rs:423-430`); `witness_quorum`
compares `reference.witnesses.len()` against `threshold` (`r6.rs:431-439`). A **budget** is a
different shape in two independent ways:

1. **It is a floor on one act vs a depleting pool across acts.** `min_atp` says *this act must stake
   at least T*. A budget says *all acts together may draw at most B, and B goes down*. The second
   requires state that persists between actions; `Rules` has no balance field and `Constraint` has
   no notion of consumption.
2. **`R7Action` has exactly ONE (available, required) pair, and it is keyed to the ACTOR.**
   `ResourceRequirements{required_atp, available_atp}` (`r6.rs:155-157`) with
   `has_sufficient_atp()` (`r6.rs:166-170`) is the right *shape* for a pool check — but
   `available_atp` is documented as *"Actor's current available ATP"* (`r6.rs:156`), it is **a copied
   float, not a handle to an account** (§1 qualifier 1), and there is one of it. Three nested pools
   need three (available, required) pairs with a narrowing relation between them. The struct has
   room for one.

**Gap (a) — genuine extension web4 should absorb**, and it is the **same structural gap as row 8**.
Row 8 found that `Rules` is one flat object with no record of which layer contributed which
constraint, so permission narrowing is auditable only by simulation. The three-level budget needs
precisely the same missing thing — a layered/attributed ceiling structure — on the resource axis.
**One extension closes both.** That convergence is the strongest argument in this document for the
layered-`Rules` proposal: two independent rulings, arriving from opposite directions (inward
permissions, outward economics), land on the same missing field.

#### 4.4.3 The blast-radius property — the strongest security result in the outward design

Because the pool is **pre-declared and separate**, a denial-of-attention or probing-oracle attack
from outside can exhaust the external-interaction budget **and nothing else**. It cannot reach the
society's operating capital, because that capital was never in the pool the outward path draws from.

> **The outward attack surface has a bounded cost ceiling, set in advance, by the society itself.**

This falls straight out of dp's framing and it is qualitatively better than what a rate limiter
buys. A rate limiter bounds the *frequency* of an attack and leaves its *total cost* open-ended
(a patient attacker just waits). A pre-declared pool bounds the *total*, and the society chose the
number. Compare §3.6.1's argument in the ceremony direction: a bar nobody can satisfy manufactures
route-arounds. Here the society is not setting a bar at all — it is deciding, in advance and by law,
how much of its own energy it is willing to lose to strangers in the worst case. That is a
decision a society can actually make.

With the per-caller level (§4.4.4), the property sharpens: **the anonymous prober cannot starve the
partner in active negotiation**, because they draw from separate sub-allocations under the same
society ceiling. Exhaustion is contained to the exhausting caller.

#### 4.4.4 The template ships the SHAPE; law supplies the NUMBERS

dp is explicit that the values are a society's own (*"ultimately that's up to society's law"*), so
**this PRD hardcodes no thresholds**. What it specifies is the structure every society inherits by
default:

| level | what it bounds | hard or default |
|---|---|---|
| society external-interaction budget | total outward draw, all callers, per period | **HARD** ceiling |
| per-caller limit | one caller's total draw | **HARD** ceiling |
| per-call limit | one exchange's draw | **DEFAULT** — salience-modulable (§4.4.5) |

A society amending its numbers is **filling in a template, not designing a mechanism**. This is dp's
*"mechanisms for the evolution, not hardcode things"* applied to resource, and it is the identical
shape as `PRD_ALLOWLISTS.md` §3.6's ceremony ratchet: declared levels, society-set values, stored
beside the law they govern, generation-covered, moving `law_hash` when they change.

**`Constraint.hard: bool` (`r6.rs:63`) is exactly the hard-vs-default distinction** — and here the
enforcement asymmetry flagged in row 5 becomes load-bearing rather than cosmetic. `min_atp` is
checked **only when `hard` is true** (`r6.rs:423`); `witness_quorum` is checked **regardless**
(`r6.rs:431`). So under today's code a `hard: false` per-call limit is not a *modulable default* —
it is **not checked at all**. A soft constraint must mean *"checked, and exceedable only by a
recorded salience assessment"*, and web4-core implements that for neither constraint type. **Gap
(a)**, and the fix is small: make `hard` mean "blocks unconditionally" vs "blocks unless a recorded
justification is present", consistently across constraint types.

#### 4.4.5 Salience modulates in BOTH directions

> "important things get more allocation, trivial ones get shut down early"

Salience is **not a priority ordering**. It is an input to *how much budget an interaction may draw*
**and** to *how early it is cut off*. Two consequences, and both matter:

1. **A high-salience exchange may legitimately exceed the DEFAULT per-call limit** — while remaining
   strictly inside the per-caller and society ceilings. Narrowing is preserved because the per-call
   level was never a hard ceiling (§4.4.4); the two levels above it are, and salience cannot touch
   them. This is why the hard/default split has to be stated precisely rather than described as
   "three limits": exactly one of the three is modulable, and confusing which one is the failure
   mode.
2. **A low-salience exchange is terminated EARLY, not allowed to run to a limit.** The cheap-to-
   refuse path must be cheap. This is what makes the scheme resistant to **attrition attacks**: an
   attacker's marginal probe should cost the society close to nothing, not one full per-call
   allocation. A scheme where every refusal costs a full allocation is a scheme whose budget is
   drained by refusals — the defence paying for the attack.

Note the direction of the asymmetry, because it is the opposite of the naive design: the *expensive*
capability (exceeding a default) is gated on positive evidence, and the *cheap* capability (early
termination) is the fallback. An implementation that inverted this — running everything to the limit
unless something proved it trivial — would satisfy the same prose and be attackable.

#### 4.4.6 WHO assesses salience is an ADJUDICATION — therefore ADMIT, never COMPOSE

Assessing *"is this important"* is a judgement about an act against an existing envelope. That is
precisely what a rung does, and precisely what an agent rung is good at: high-volume, context-heavy,
latency-sensitive (`PRD_ADJUDICATOR_LADDER.md` §13 **[branch 6a14bbf]**, §6.1–§6.4). So salience
assessment routes on the ladder like any other adjudication, on the same `kind × consequence` key
(§3).

> **PINNED: a salience assessment may modulate a draw WITHIN the composed ceilings. It may never
> raise a ceiling.**

This is the exact hop §13.2 warns about — a rung that composes rather than admits — and **salience
is the most tempting place in the entire design for it to happen**, because *"this is important"* is
how every envelope enlargement in history has been argued. §13.1's two verbs apply unchanged:
COMPOSE (∪) is an operator or delegated act, witnessed, ceremony-tiered, generation-bumping; ADMIT
(∩) is machine-time and **no term may add**. A rung raising a per-caller ceiling because a caller
seemed important is COMPOSE performed at admission time, which §13 exists to forbid.

Concretely, the boundary is: a rung may move a draw **up to the per-caller ceiling** and may cut it
off **at any point below**; a change to the per-caller or society ceiling is a `governance.*` act
that the route table answers with a **refusal, not a rung** (`PRD_ALLOWLISTS.md` §3.6.5, ladder
§5.3). Budget ceilings join that refusal set.

#### 4.4.7 TWO ECONOMIC REGIMES — and the boundary between them is CITIZENSHIP

**dp (2026-08-14), verbatim, and it is this subsection's thesis:**

> "the per-caller and per-call limits should address that for the most part. external caller is the
> 'free tier', those who want to escalate for cause would have to gain citizenship to prove they
> merit the resource, and spend their own atp doing it. those not willing, prove it wasn't salient
> enough :)"

| regime | who | funded by | bounded by |
|---|---|---|---|
| **free tier** | external / non-citizen callers | the society's law-declared external-interaction (PR) budget | per-caller and per-call limits (§4.4.4); low salience terminated early (§4.4.5) |
| **self-funded** | citizens | **the caller's own ATP** | their own balance, plus the ordinary inward machinery — `Constraint{min_atp}` (`r6.rs:57`), `ResourceRequirements{required_atp, available_atp}` (`r6.rs:155-157`), `has_sufficient_atp()` (`r6.rs:166-170`) |

**The society stops subsidising at exactly the point the caller has standing to pay.** This is the
machine form of the org pattern the whole outward design mirrors: anyone may call the front desk —
free, bounded, brief — and sustained engagement requires becoming a customer, partner or member, at
which point the relationship is **funded rather than donated**.

Mechanically the second regime needs **nothing new**. A citizen escalating for cause is the inward
case of §4.1, already implemented in `validate()` (`r6.rs:402-443`). The free tier is the only half
that required the three-level budget structure at all. That is a good sign about the design: the
novel machinery is confined to the regime where the payer is absent.

#### 4.4.8 COST IS THE SALIENCE ORACLE — do not assess the claim, PRICE it

This **supersedes** the mitigation this document previously proposed for salience gaming. The
earlier position was that salience must be assessed from evidence the caller does not author,
because caller-supplied urgency signals are a caller-controlled input to a resource decision. That
is true and it is the weaker instrument. dp's answer is better:

> **"those not willing, prove it wasn't salient enough"**

A caller unwilling to gain citizenship and spend their own ATP has **revealed** the interaction's
salience *to them*. **Revealed preference is not gameable in the way an asserted priority flag is** —
there is no cheap way to fake having paid. An attacker can set an urgency bit on every request for
free; they cannot claim citizenship and spend ATP on every request for free. The instrument that
costs the claimant is the instrument that measures.

So the two regimes get two different salience instruments, and the split is principled rather than
pragmatic:

- **Above the free tier: cost is the oracle.** No assessment is required, because the price *is* the
  assessment. This is the stronger instrument and it should be preferred wherever a price signal
  exists.
- **Within the free tier: there is no price signal**, because by construction the caller is not
  paying. Here the earlier position stands, unchanged and now correctly scoped — allocate from
  evidence the caller does not author, which the envelope already carries as
  `Reference{precedents, mrh_depth, relevant_entities}` (`r6.rs:118, 120, 122`):
  - `precedents: Vec<Precedent>` (`r6.rs:118`), each `{action_hash, outcome, relevance}`
    (`r6.rs:128-136`) — relationship history and prior outcomes, hash-anchored, authored by the
    record and not by the caller;
  - `relevant_entities` (`r6.rs:122`) — the trust path;
  - `mrh_depth` (`r6.rs:120`) — the society's own purpose/relevance scoping, and (per row 3) the
    natural home for §10.2's *purpose/MRH* field.

  That remains a real result: the two fields row 3 found unmapped in *either* direction turn out to
  be exactly the non-caller-authored evidence free-tier allocation needs.

Where caller assertion **is** used in the free tier, it is **testimony, never proof** — hestia
already has the exact structure in `stated_attempted_act` (`core/src/server/handler.rs:9773`),
documented as *"caller prose, testimony, unverified by anything on this row"* (#445). Recorded as a
claim, joined to outcome later. **Honest limit:** that scoring loop does not exist yet, so v0
free-tier salience should lean on `Reference` and treat caller assertion as recorded-but-inert.

#### 4.4.9 Citizenship gains an ECONOMIC meaning, and now does double duty

GPT established that **citizenship is eligibility, not a grant** — a standing from which narrower
grants may be composed, never itself a capability (`PRD_ADJUDICATOR_LADDER.md` §13.5, *"Standing is
ELIGIBILITY, not a grant"* **[branch 6a14bbf]**). dp's ruling adds the second half: citizenship is
also **the point at which a caller funds their own interactions**.

Both are true and they compose cleanly — *eligibility for grants*, and *responsibility for cost*.
But the consequence needs stating before someone discovers it late:

> **The citizenship bar now does double duty: access control AND economic admission. A society
> tuning it is tuning both at once.**

Lower the bar because newcomers are being excluded, and you have also just moved the free-tier
boundary and changed who the society subsidises. Raise it to reduce subsidy, and you have also
narrowed who may ever hold a grant. Neither effect is wrong; both being invisible to whoever moves
the number is. Any law amendment touching the citizenship bar should be required to state which of
the two it intends — a small documentation obligation that prevents a large class of surprise.

#### 4.4.10 Exhaustion must be LEGIBLE — a never-flatter requirement

A caller refused because **the budget is spent** has been refused for a completely different reason
than a caller refused **on merit**. Conflating them damages exactly the relationship the budget
exists to build.

Three requirements:

1. **Said as such to the caller**, in terms that leak no capability information: *"this society's
   external-interaction budget is spent for now."* That is a statement about the society's own
   resources, not about what the caller lacks — so it is compatible with §10.6's rule that *"the
   refusal text must not disclose the role that was not reached."* Budget exhaustion is the one
   outward refusal that can be honest without leaking, because it is about **us**, not about them.
2. **Recorded as its own class in the act.** And this collides with §6.3: `ActionStatus`
   (`r6.rs:173-182`) has no shape for it either. Budget-exhausted is not `Failure` (nothing ran),
   not `Error` (nothing is broken — the system is working as designed), and not the same as a
   merit refusal. **This is a third, independent demand for the `ActionStatus` extension** —
   arriving from the outward direction, while §6.3's two arrive from the gate (refused) and from the
   ladder (declined). Three independent needs for variants that do not exist is the strongest
   available evidence the enum is under-specified rather than merely inconvenient here.
3. **Visible on the operator surface as a BUDGET STATE, not as a wall of denials.** An exhausted
   budget rendering as a stream of ordinary denials is the same disease as #435/#438's
   dashboard-honesty family — a state rendering as something it is not. The operator should see
   `external-interaction budget: spent (period resets …)`, once, as a fact — not infer it from
   denial volume. Per §3.6.7's never-flatter doctrine, an exhausted budget is a **legitimate state**
   and must not render as a defect; equally it must not render as normal operation.

#### 4.4.11 R7 turns "ultimately beneficial function" into a MEASUREMENT

dp's justification for the budget is that outward interaction is *"an ultimately beneficial
function."* Because outward acts are `R7Action`s with `reputation: Option<ReputationDelta>`
(`r6.rs:354`), that claim becomes **auditable rather than asserted**: each outward spend carries what
it produced — citizenship established, a partnership opened, a support case resolved, or a probe
refused cheaply. The budget becomes an **investment with a recorded return**, which gives the society
a principled basis for raising or lowering it by law rather than by argument.

Two honest caveats, because this is the part most likely to be over-claimed:

- **A metric that decides its own budget is a feedback loop**, and naming it is the minimum. If
  reputation gain justifies budget increases and budget funds the interactions that generate
  reputation, the loop is self-reinforcing in both directions. The measurement design needs its own
  scrutiny — **flagged as future work, not claimed solved.**
- **Row 7's grain mismatch applies here too**: `ReputationDelta` is per-action, ROI is a fold over
  many, and no such fold exists in `r6.rs`. The evidence is carried; the aggregation is unbuilt.

#### 4.4.12 The residual — and it is a SINGLE law-set parameter

**Accrual vs per-period expiry is resolved, and the reasoning matters more than the answer.** The
question was: does a long-quiet society present a single-day attack surface equal to its entire
saved pool? **The per-caller limit already answers it.** A per-caller ceiling bounds any single
caller's draw *regardless of how large the accrued pool is*, so an accrued budget **cannot be
drained by one actor**. Draining it requires **many** callers, which is one of exactly two things:

1. **a genuine surge of external interest** — the budget doing precisely the job it exists for, and
   a signal to raise it by law rather than a failure; or
2. **a sybil attack** — many identities under one hand.

So "accrue or expire" stops being the security question. It becomes an ordinary policy preference a
society may set either way, and the real question is (2).

> ### The load-bearing security parameter is THE COST OF OBTAINING CITIZENSHIP.
>
> **The PR budget bounds the blast radius. Citizenship cost bounds the number of actors who can aim
> at it.**

Cheap citizenship reopens the free tier at scale under N identities — each sybil gets its own
per-caller allocation, and the per-caller ceiling that made §4.4.3's containment work is defeated by
multiplying callers rather than by exceeding any one limit. Expensive citizenship excludes
legitimate newcomers and starves the beneficial function the PR budget exists to fund (§4.4.11) —
§3.6.1's unsatisfiable-bar failure, arriving on the membership axis.

**That the whole scheme's outward attack resistance concentrates into one explicitly law-set number
is a feature, not a defect** — one parameter, one amendment path, one thing to audit, and it moves
`law_hash` when it changes (row 4). A security property that concentrates somewhere visible is
better than one distributed across mechanisms nobody can total up. But it must be *stated* as the
load-bearing parameter rather than left implicit, which is what this subsection is for. Note also
§4.4.9: this same number is simultaneously the access-control bar, so it cannot be tuned for
sybil-resistance alone without moving who may hold a grant.

**OPEN — and it replaces accrual-vs-expiry as the sole remaining budget question:
sybil-resistance of citizenship.** What makes citizenship costly enough to bound N without being
costly enough to exclude the callers the PR budget exists to attract? Not answered here.
**Hub's**, because Hub owns citizenship.

---

## 5. What this does to the composite-authority primitive

The sprint-one candidate (allowlists §12.1, role §9.1, ladder §11): **ONE composite policy
revision/digest** and **ONE horizon bounded by every contributing authority** — standing grants,
allowlists, floor, clearances, occupancy, manifest generation, ladder generation.

**Partly subsumed. Specifically:**

**Subsumed — the DIGEST.** `Rules.law_hash: String` (`r6.rs:34`) is a single SHA-256 over the
governing law document, and `Rules.society` (`r6.rs:36`) names the issuing society. The composite
digest **is** `law_hash`, and §12.1 already says so from the other side: *"AC-12 already requires
that an allowlist edit move `law_hash`; that requirement is unchanged and is now understood as the
composite surfacing to members through `law_hash`."* No new object. Every act's `Rules.law_hash`
pins the whole seven-authority tuple, and row 4 makes it checkable per decision.

**NOT subsumed — three specific remainders:**

1. **Ordering.** A hash is not ordered. §3.4's stranding rule — *"a clearance revocation or manifest
   amendment bumps a generation and strands every derived entry minted under the old one"* —
   requires deciding whether entry E's generation is **older** than the current one. `sha256(A)` and
   `sha256(B)` are incomparable. `Rules` has **no generation field**. The monotonic counter is
   therefore a genuine remainder, not a redundancy: `law_hash` answers *"is this the same policy?"*
   and the generation answers *"is this an older policy?"*, and stranding needs the second.
2. **The horizon.** `horizon = min(now + STANDING_SNAPSHOT_TTL_SECS, earliest covered expiry across
   ALL authorities)` has **no carrier**. `Request.deadline` (`r6.rs:92`) is the action's own
   deadline; `Rules` carries no validity window at all. This is the same hole row 2 found under T1's
   *"fresh certified snapshot"*. **Gap (a) — genuine extension**, and the natural shape is a
   `valid_until` on `Rules`, which would let `validate()` refuse an act evaluated against an expired
   law snapshot — something no current code path can do.
3. **The per-authority breakdown.** A digest that moved does not say *which* of the seven moved. For
   the composite that is arguably correct (any authority moving invalidates the snapshot), but
   §3.5's three independent revocation paths each want to say *which* one stranded an entry, and
   §6 criterion 3 tests them independently. A flat hash cannot distinguish them.

**So: `Rules.law_hash` + a `generation` + a `valid_until` on `Rules` fully subsumes the composite
primitive; `law_hash` alone subsumes about half of it.** The right read is that the composite
primitive is **not a new object** — it is two missing fields on an existing one — and that is a
better outcome than either "fully subsumed" (which would have been wrong) or "needs its own object"
(which would have been the fourth parallel structure this amendment exists to prevent).

---

## 6. The honest cost

### 6.1 The real distance: hestia today vs `R7Action`

Measured, not estimated (`grep -rln "web4_core::r6" --include=*.rs .` over the hestia checkout):

**Three files import from `web4_core::r6`, and they import five leaf types:**

| site | imports | what it does |
|---|---|---|
| `core/src/reputation.rs:19,22` | `ReputationDelta`, `SovereignStrength`, `TensorDelta`, `DeltaClass` | builds a `ReputationDelta` from an `EntityTrust` before/after diff (`delta_from_change`, `reputation.rs:134`), appends it to `reputation-deltas.jsonl` (`log_delta`, `reputation.rs:207`) |
| `core/src/witness_act.rs:26` | `WitnessAttestation` | attaches attestations to witnessed acts |
| `core/src/server/state.rs:1079` | (doc reference only) | names the local sink |

**Zero `R7Action` constructions.** Zero `Rules`, `ActionRole`, `Request`, `Reference`,
`ResourceRequirements`, `ActionResult`, `ActionStatus`, `Constraint`, `Precedent`, `ProofOfAgency`.
Of the eleven types the envelope is made of, hestia uses **one** (`WitnessAttestation`) plus the
four reputation-side types.

**One partial envelope does exist, and it is worth naming precisely**:
`core/src/policy/law_gate.rs:114` builds a `web4_policy::R6Request` — a *different, thinner* type
(`web4-policy/src/lib.rs:548`) with four fields (`role`, `action`, `payload`, `resource`), which is
R6's Role + Request + a resource bag and **nothing else**: no `Rules` as data, no `Reference`, no
`Result`. And its `resource` is `Default::default()` (§4.3).

**So the distance, stated as one sentence:** *hestia emits R7's reputation OUTPUT without ever
constructing the R6 INPUT it is supposed to belong to, and separately evaluates a four-field
policy-layer R6 request whose resource bag is empty.*

The sharpest consequence of that: `ReputationDelta.action_id` (`r6.rs:304`, doc *"Ledger reference
(action ID / tx hash)"*) is populated from `RepContext.action_id` (`reputation.rs:84`) — a
caller-supplied `&str`. **There is no `R7Action` it identifies.** Every row in
`reputation-deltas.jsonl` names a parent action that does not exist as an object anywhere.

### 6.2 What wrapping would break

- **Nothing at the type level, immediately.** The delta types are unchanged; `R7Action.reputation`
  is `Option<ReputationDelta>` (`r6.rs:354`) and takes exactly the delta `delta_from_change` already
  produces. Wrapping is additive.
- **The existing sink corpus becomes retroactively unparented.** Once `action_id` means "the id of
  an `R7Action` in the chain", every pre-wrap row in `reputation-deltas.jsonl` has an `action_id`
  that resolves to nothing — and per `fb_changing_what_artifact_contains`, a new KIND of content in
  an existing artifact breaks readers silently. Either the field's meaning is versioned or the
  corpus is partitioned. **This must be decided before the first wrapped emit, not after.**
- **Row 8's hazard is a live risk during migration.** Building `Rules` from a layer that contributes
  no permissions produces an allow-all (`r6.rs:50`). Any wrapping work must carry a test that a
  layer contributing nothing **narrows or is inert**, never widens — the differential shape
  `fb_sabotage_changes_nothing_absent` requires.
- **Cost that is real and should not be minimised:** `R7Action` is a large struct with five
  mandatory sub-structs. Constructing one per gate decision, on a sub-millisecond in-process path
  (ladder §2.1 rung 0), is not free. The ladder's own framing helps — rung 0 is `R6` (cheap, no
  reputation), rung 1+ is `R7` — and that is another argument for §3's single selection, but it
  should be measured, not assumed.

### 6.3 Does `Result` / settlement fit a GATE REFUSAL? **No, and this is the gap.**

`ActionStatus` (`r6.rs:173-182`), in full:

```rust
pub enum ActionStatus { Pending, Validated, InProgress, Success, Failure, Error }
```

**There is no `Refused`, no `Denied`, no `Declined`.** A gate deny — the single most common
governed act in this repo — has no shape:

- `Failure` reads as *"the act ran and did not work"*. A refused act **never ran**. Recording a deny
  as `Failure` is the `fb_composed_not_delivered` shape: refused and attempted-then-failed become
  indistinguishable in the record.
- `Error` reads as *infrastructure*. Recording a deny as `Error` is **precisely** the conflation
  `DeltaClass` (`r6.rs:260-270`) was added to prevent — its own doc names the measured cost:
  *"hestia PR #357 class: infrastructure fail-closed denies scored as member conduct."* The status
  axis reproduces on the input side the exact defect the reputation axis fixed on the output side.
- `Pending` is worse. `validate()` (`r6.rs:402-443`) returns `Vec<String>` and **sets no status at
  all**; `R7Action::new` initialises `status: ActionStatus::Pending` (`r6.rs:381`). So an action
  refused by validation is byte-indistinguishable from an action that was never attempted. That is
  `ref_fail_closed_denies_unrecorded` — *"fail-closed deny leaves NO trace"* — reproduced inside
  web4-core.

And there is no `Declined` either, which row 10 and ladder §3.1 note 1 both need: *"`decline` is not
an error… today a rung that timed out and a rung that abstained would be indistinguishable, and
`ref_equality_referee_abstains_not` is the general form of that confusion."*

And §4.4.8 supplies a **third** missing disposition from a completely independent direction:
**budget-exhausted**. A caller refused because the society's external-interaction budget is spent is
not `Failure` (nothing ran), not `Error` (nothing is broken — the design is working), and not the
same as a merit refusal. Three independent demands — gate deny, rung decline, budget exhaustion —
for variants that do not exist is the strongest available evidence the enum is genuinely
under-specified rather than merely inconvenient for hestia.

**Named gap, and it is web4's to fix, not hestia's:** `ActionStatus` needs at minimum `Refused`
(the act was not permitted; state is bit-identical to before — CLAUDE.md's O clause), `Declined`
(no view was formed; the act may still proceed up a ladder), and a disposition for
resource-exhaustion that is distinguishable from both. All are **terminal-with-no-side-effect** and
none exists. Until they do, wrapping a refusal in an R6/R7 envelope makes the record *worse shaped*
than hestia's current bespoke deny record, which at least names its own disposition.

Settlement has the mirror hole: a refused act must **roll back**, not **commit** — `rollback`
(`atp.rs:87`) returns locked→available — while a *forfeited* one commits (§4.2.3). With no status
distinguishing refused from failed, there is no basis on which to choose the verb.

---

## 7. RWOA + S + V self-audit

This PRD proposes no surface. The audit is on the surfaces the amendment would create if adopted,
assessed at design time.

```
surface: R7Action construction at a governed act   act: record a consequential act (compose/admit/escalate/adjudicate)
S: high/varies [construct: kind × consequence → R6|R7 selection, §3]
R: n/a [construct: the envelope is a record, not an authorization path]
W: pass [construct: ActionRole{actor_lct, role_lct} r6.rs:67-75 + Reference.witnesses r6.rs:124]
O: FAIL as specified [construct: no ActionStatus::Refused, §6.3 — a denied act cannot be recorded as having left state bit-identical]
A: pass-with-gap [construct: canonical_hash r6.rs:446 + prev_action_hash r6.rs:360 chain the record; the evidence-basis gap is Reference-vs-consulted, row 12]
V: present [construct: Rules.prohibitions r6.rs:42 short-circuits at r6.rs:47-49 — governance.* returns a refusal, not a price]
verdict: ESCALATE — adoptable only after ActionStatus gains Refused/Declined (§6.3). Adopting first would degrade the deny record.

surface: ATP-governed escalation (inward)   act: open an escalation against a min_atp constraint
S: med/reversible [construct: Constraint{min_atp} r6.rs:57, enforced r6.rs:423-430]
R: n/a   W: pass [construct: ActionRole + the escalating member's session identity]
O: pass [construct: validate() r6.rs:402-443 runs before execution; both ATP checks are preflight]
A: pass [construct: atp_consumed r6.rs:196 inside the same hashed record — answers fb_spend_invisible_spender]
V: present [construct: Rules.prohibitions; and an insufficient-ATP act is refused, not downgraded]
verdict: PASS (design)

surface: outward external-interaction budget draw   act: fund a stranger's exchange / escalation from society ATP
S: high/irreversible-in-effect (a spent or forfeited draw is not returned) [construct: §4.4.4 three-level template]
R: n/a [construct: caller reachability is a routing key, never authority — role §10.1]
W: pass [construct: ActionRole names the OCCUPANT; the caller is evidence via Reference — note row 9's two-party gap]
O: pass-by-design [construct: draw checked before the exchange proceeds; low-salience terminates EARLY, §4.4.5]
A: pass-with-gap [construct: Rules.society r6.rs:36 + law_hash r6.rs:34 pin the budget in force; the DRAW itself has no carrier — §4.4.2]
V: present [construct: society ceiling is pre-declared and separate — the blast-radius bound, §4.4.3; ceiling changes return a refusal, not a rung, §4.4.6]
verdict: ESCALATE — the design is sound and RULED; adoption is blocked on two web4-core extensions,
  not on an unanswered question: (i) Constraint cannot express a depleting nested pool (§4.4.2),
  (ii) ActionStatus cannot express budget-exhausted (§4.4.8/§6.3).
```

The verdicts have moved since dp's rulings. The outward half is **no longer blocked on a policy
question** — it is blocked on two named, small, web4-core-side extensions, which is a materially
better place to be. The V clause on the outward surface is the one worth reading twice: the veto is
**structural rather than procedural** — the society pre-declares what it is willing to lose, and no
runtime decision can exceed it (§4.4.3). That is a stronger V than any escalation path, because it
cannot be argued with at act time.

---

## 8. Falsifiable acceptance criteria

**AC-E1 — the mapping is checkable, not asserted.** A test (or a CI doc-check) asserts every
`file:line` citation in §2 resolves to a construct of the named identifier in the pinned web4
checkout. The arm that must fire: rename `Constraint.threshold` in a scratch copy and assert the
check goes red. Per `fb_derived_constant_needs_producer`, a citation without a producer rots.

**AC-E2 — `rate_limit` stays dropped until it exists.** Assert `grep -c "rate_limit"` over
`web4-core/src/` equals 1 (the doc comment at `r6.rs:57`). If it rises, row 5 is re-openable. If any
PRD in this family cites `Constraint{rate_limit}` as a carrier while this holds, that is the defect
this criterion exists to catch.

**AC-E3 — the empty-permissions hazard cannot ship.** A differential: an `R7Action` whose `Rules`
has `permissions: []` and `prohibitions: []` must be **refused**, not allowed, by whatever hestia
wraps around `has_permission`. Today `r6.rs:50` allows it. Both arms: the same action with an
explicit permission is allowed.

**AC-E4 — refused ≠ failed ≠ never-ran.** Three actions — one refused by `validate()`, one that ran
and failed, one never attempted — must produce three distinguishable records. **This criterion
currently FAILS by construction** (§6.3) and is the acceptance test for the `ActionStatus`
extension. Recording it as a failing criterion rather than as an open question is the point:
`fb_declare_open_decision_red`.

**AC-E5 — the ATP selector resolves.** After populating `R6Request.resource` (§4.3), a hub-law norm
selecting on `r6.resource.atp` evaluates against a real value. Negative arm: with the map empty the
same norm must be observably inert — proving the criterion measures the plumbing and not the norm.

**AC-E6 — `consulted` is not `Reference`.** Any rung implementation must record what it read
separately from what it was offered, and a test must show the two differing for a rung that reads
only part of the bundle. A rung whose `consulted` equals its `Reference` on every decision is
`fb_guard_never_fired_claim` — an unfired claim.

**AC-E7 — law_hash moves when any of the seven authorities moves.** §5's composite, tested through
the envelope: mutate each contributing authority in turn, assert `Rules.law_hash` differs each time.
Seven arms, one per authority. The arm that must fire: pin one authority out of the digest and
assert its arm goes red.

**AC-E8 — provenance-only carryover is measurable, not merely stated.** Row 6: an escalated action's
`Request.parameters` must not contain the prior action's payload. Positive control: the same
escalation with the transcript deliberately attached must be caught. Without this arm, row 6 is a
schema property nobody enforces (§2.2, row 6's second half).

**AC-E9 — the three budget ceilings NARROW, in both directions.** §4.4.2: a per-call allocation may
never exceed the per-caller limit, and a per-caller limit may never exceed the society ceiling.
Property test over random triples. **Both arms:** a salience assessment that raises a *default*
per-call draw within the per-caller ceiling **succeeds**; the same assessment attempting to exceed
the per-caller ceiling is **refused**. Without the positive arm, a store that refuses every
modulation passes and salience is broken in the other direction — the shape
`PRD_ALLOWLISTS.md` §3.6.3 pins for the ceremony ratchet.

**AC-E10 — salience ADMITS, it never COMPOSES.** §4.4.6: no rung verdict, at any confidence, may
change a per-caller or society ceiling. The arm that must fire: a rung returning `approve` on a
`budget.ceiling.*` route must be answered with a **refusal, not a rung id** (ladder §5.3's shape).
A route table that returns a rung for that kind is the ratchet-defeat.

**AC-E11 — the free tier is bounded and the self-funded tier is not subsidised.** §4.4.7: a
non-citizen caller's total draw across a period cannot exceed their per-caller limit regardless of
call count; and a citizen's escalation draws from **their own** balance
(`ResourceRequirements.available_atp`, `r6.rs:157`), never from the PR pool. Differential: the same
act by the same identity before and after citizenship must draw from different sources, and the
record must say which.

**AC-E12 — budget exhaustion is distinguishable from merit refusal, at all three surfaces.**
§4.4.10: in the caller-facing text, in the act record, and on the operator dashboard. The arm that
must fire: with the budget spent, a refusal that is byte-identical to a merit refusal fails the
criterion. Currently **unsatisfiable** at the record surface (§6.3) — recorded as failing rather
than deferred, per `fb_declare_open_decision_red`.

---

## 9. Open questions

**Q1 — RULED, three times, and moved out of this section.** *Who pays for an outward caller's
escalation?* dp ruled (2026-08-14): a **society-law-declared external-interaction budget** — the
machine form of a PR cost — structured as **three nested ceilings** (society ⊇ per-caller ⊇
per-call), modulated by **salience** in both directions, with **citizenship as the boundary** past
which callers fund themselves. It is now §4.4. Stub kept so a reader who remembers this as the
load-bearing open question can see it was answered and where. **What remains open is Q6, not the
mechanism.**

**Q6 — sybil-resistance of citizenship. THE remaining budget question, and it is Hub's.** §4.4.12.
The scheme's outward attack resistance reduces to one law-set number: cheap citizenship reopens the
free tier at scale under N identities; expensive citizenship excludes the newcomers the budget
exists to attract. Not answered here, and deliberately not guessed at — Hub owns citizenship.

**Q2 — Does the family's ternary consequence grade collapse to R6/R7's binary, or ride alongside?**
§3 recommends alongside (`kind × consequence → (R6|R7, Constraint[])`). Open because collapsing to
binary is simpler and might be right if `max_consequence` (ladder §3.2) is the only consumer of the
finer grade — which is checkable, and nobody has checked.

**Q3 — Does `web4_policy::R6Request` converge on `web4_core::r6::Request`, or stay a thinner
evaluator input?** Two types spell "R6 request" today (`web4-policy/src/lib.rs:548` vs
`r6.rs:78-99`) with different fields. One vocabulary or two is exactly the question this whole
amendment answers "one" to everywhere else, and it should be answered by whoever owns web4-policy,
not asserted here.

**Q4 — What is the migration disposition of the existing `reputation-deltas.jsonl` corpus** once
`action_id` acquires a referent? §6.2. Version the field or partition the corpus; either is fine,
silence is not.

**Q5 — Should `ActionStatus::Refused` carry the refusing rule?** `ref_deny_names_marker` records
that today's deny record names the RULE and not the ACT, for a class of four. The envelope has room
for both (`Request` names the act, `ReputationDelta.rule_triggered` names the rule at `r6.rs:307`)
— but only on the R7 path. An R6 refusal has nowhere to put the rule. Small, and it will be
discovered late if not recorded now.

---

## 10. Non-goals

- **Not building any of this.** Docs-only. No code lands in this PR.
- **Not amending web4-core.** §2's gaps (a) are stated as things web4 should absorb; they are
  web4's decisions, and hestia proposing them is not hestia making them.
- **Not answering §9 Q6** (sybil-resistance of citizenship). Deliberately — it is Hub's, and §4.4.12
  states why it is the one that matters.
- **Not setting any budget NUMBER.** §4.4.4 ships the shape; every value is a society's own law.
- **Not deprecating the three PRDs.** The envelope subsumes their *carriers*, not their *arguments*.
  §3.6.1's efficiency-attractor rationale, §4.3's measurement obligation and §10.5's three
  human-org fixes are not fields in a struct and never will be.
- **Not claiming the wrapping is free.** §6 exists because it is not.

---

## 11. What this PRD would look like if it were wrong

Stated because `PRD_ADJUDICATOR_LADDER.md` §12 sets the precedent and the discipline is worth
keeping.

If this amendment is wrong, the failure is **premature unification**: R6/R7 is a schema with one
struct, a validator and no engine (§1 qualifier 2), and adopting it would mean hestia's four
governed acts inherit a shape optimised for a framework nobody has run. The symptom would be
`Request.parameters: HashMap<String, Value>` (`r6.rs:85`) quietly becoming the home for everything
the envelope does not model — the independence grade, the `consulted` list, the layer provenance,
the occupancy id — at which point the envelope is a wrapper around a JSON bag and the four bespoke
structures have not been removed, only hidden. **The measurable early warning is the ratio of typed
fields to `parameters` keys at the first three wrapped call sites.** If most of what a governed act
needs to say ends up in `parameters`, this amendment was structure-for-its-own-sake and should be
withdrawn rather than defended.

The counter-argument, and why the PRD is proposed anyway: row 10 already happened. `DeltaClass` and
`SovereignStrength` are hestia-discovered semantics that landed **in web4-core** and are now the
canonical fleet interop currency (`core/src/reputation.rs:4-13`). The envelope has already absorbed
one hestia lesson correctly. That is evidence the direction works, and it is evidence about this
specific pair of codebases rather than about schemas in general.
