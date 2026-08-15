# PRD — the ADJUDICATOR LADDER: who decides, as configuration rather than as code

**Status**: proposed — dp-directed 2026-08-14; design PRD, not started; the seam that lets other
PRDs' open questions be configuration rather than rulings.
**Author**: claude-code (CBP), 2026-08-14.
**Relates to**: `docs/PRD_ALLOWLISTS.md` (§3.6 the ceremony ratchet — this PRD is that ratchet
applied to the DECIDER rather than to the evidence; §7 open questions recast as extension points),
`docs/PRD_ROLE_SCOPE_BRIDGE.md` (§2 proof tiers, §7 the second-factor question — an agent rung is a
candidate second factor), `docs/DESIGN_DECISIONS/0015-not-same-work-is-claimed-not-assigned.md`
(the measurement this exists to move, and the correction to it), `docs/PRD_GOVERNANCE.md` (the
one-authority-path invariant), `docs/PRD_GATE_CONSOLIDATION.md` (§5 the closure rule — a control
must protect its own registration), issues #434 (claim-window race), #440 (the gate's own FP class),
#437 (dissent lands as dissent), #264 (the named resolver), #128 (asker basis).
**Checkout pinned**: every `file:line` below is read at `dae0aa3` in a worktree of `origin/main`.
Line numbers drift; the construct names do not, and the construct name is the citation that matters.

---

## 0. The directive (dp, 2026-08-14) — VERBATIM, and it is the spec

> "all of these things we're going to have to take a best guess at and evolve as we go. the key is
> to have mechanisms for the evolution, not hardcode things. and remember, the policy entity AGENT
> is still intended to slot in between heuristic slot and human, as a middle escalation layer. and
> even that can be a neural net, and THEN an agent. your own 'auto mode' in claude-code already
> implements this. so rather than rule on these, i want to add hooks for planned infrastructure.
> ultimately, a competent agent will be a far more effective reviewer than a human - always there,
> much faster, able to actually look at the full context, consult the actual law. that is the goal."

Everything below is construction detail for that paragraph. Where this document and §0 disagree,
§0 wins.

---

## 1. What exists — measured, and three corrections to the brief

This PRD was commissioned on a description of the seam that is directionally right and factually
wrong in three places. The corrections are not pedantry: two of them change what has to be BUILT,
and one of them changes what this PRD is allowed to CLAIM.

### 1.1 The seam is real, and it is not where it was said to be

**Verified.** `Escalation::decided_by` is `Option<String>` — a field designed for any decider —
at `core/src/server/gate_escalation.rs:343`, beside `decided_role` (`:352`), `decided_via:
Option<Channel>` (`:344`) and `independence: Option<Independence>` (`:355`). The doc comment on
`decided_role` already carries dp's ruling from 2026-07-30:

> "at some point we need to stop putting 'human' on a pedestal. and focus on the role. sovereign
> is a role. who or what fills it is secondary."

**Corrected (1) — `handler.rs:~8656` is not the decide path. It is a test fixture, and for a
different type.** `core/src/server/handler.rs:8656` constructs a `ScopeRequest` (not an
`Escalation`) inside the unit test `a_scope_grant_covers_exactly_one_path`. The other cited-shape
site, `handler.rs:14102`, is `standing_scope_surface_tests::live_request` — also a `ScopeRequest`,
also a test. Neither can hardcode a production decider because neither runs in production. A PRD
whose central claim rested on those lines would have been arguing from a fixture.

**Corrected (2) — `EscalationStore::decide` is already generic, and already refuses anonymity.**
`core/src/server/gate_escalation.rs:1064`:

```rust
pub fn decide(&mut self, id: &str, approve: bool,
              decided_by: &str, decided_role: &str, via: Channel,
              independence: Option<crate::arbiter::Independence>,
              reason: Option<&str>, now: u64) -> Result<Escalation, DecideError>
```

There is no `"operator"` literal in it. `:1078` returns `DecideError::AnonymousDecider` on an empty
decider — the store already insists that a ruling name its ruler. **The store layer needs no
widening at all.**

**Corrected (3) — the escalation surface already has a NON-operator production decide path, and it
is fully wired.** There are exactly two production callers of `decide`:

| call site | decider passed | channel | independence |
|---|---|---|---|
| `core/src/server/http.rs:2482` (`operator_gate_escalation`, fn at `:2457`) | literal `"operator"` / `"role:constellation:sovereign"` | `Channel::OperatorSession` | `None` |
| `core/src/server/handler.rs:13811` (`tool_gate_arbitrate_escalation`, fn at `:13700`) | `&arb.plugin_id` / `&arb.role_lct` — **resolved from the caller's live session** | `Channel::PeerMember` or `SelfWithdrawn` | computed by `arbiter::eligibility_for` |

So the hardcode is real but it is **one of two doors, and it is the operator's own door**, where
hardcoding the decider is correct — that endpoint is behind `operator_gate` and the caller has
proved an operator LCT. The MCP door at `handler.rs:13700` is already a peer rung: it resolves the
arbiter from a live session, runs NOT-SAME server-side (`:13748-13780`), records `independence`,
witnesses a refusal as `gate_escalation_arbiter_refused`, and refuses a self-directed approval as a
hard internal error (`:13803`).

The genuine `"operator"` hardcodes on a *decide* path are on a different surface — the SCOPE
request, not the gate escalation: `core/src/server/http.rs:1679` (`scope_decide`, fn at `:1488`)
sets `req.decided_by = Some("operator".to_string())`, and `core/src/server/dashboard.rs:1352`
projects the same literal. Those are in scope for this PRD's §2.4 and should not be confused with
the escalation path, which does not have the defect.

**What the corrections change.** The core proposal is *not* "widen `decided_by`" — that is done.
It is: **the sequence of deciders is not represented anywhere.** `decided_by` records who *did*
decide, after the fact. Nothing in the system says who *should be asked, in what order, for this
act*. That is the missing construct, and it is a new one rather than a widening.

### 1.2 The routing data already exists — and nothing reads it

This is the sharper finding, and it is the one that makes the ladder cheap.

`core/src/policy/law_gate.rs:135-142` extracts `outcome.escalate_to` — hub law's own statement of
**who should resolve this** — and `:187` emits it as a machine-readable `escalate_to:<who>` token on
`PolicyEvaluation::constraints`. It is pinned by the test
`a_named_resolver_is_carried_as_data_not_only_prose` (`law_gate.rs:339`), whose fixture law reads:

```yaml
escalation:
  - condition: "r6.request.action == Bash"
    escalate_to: policy-agent
```

**dp's "policy entity AGENT" is already spelled, by name, as a resolver a law can choose.** The
comment at `law_gate.rs:124-131` says exactly why the field was promoted from prose to data:

> "`outcome.escalate_to` names WHO hub law wants to resolve this. It was interpolated into the
> reason sentence and nowhere else, so the one fact the ladder needs — which resolver — could only
> be recovered by parsing English. […] here it was the reason the resolver pool has exactly one
> member in it."

And then: **`grep -rn escalate_to core/src plugins` returns nothing outside `law_gate.rs` itself.**
The producer has no consumer. The law can name a resolver; the escalation machinery never asks.
This is the repo's known producer-with-no-call-site shape, and it is precisely the join this PRD
supplies.

### 1.3 The historical decided-by measurement — CITED, not re-measured, and the common citation is stale

**Not re-measured.** No `hestia_query_history` tool was reachable from this session's toolset, so
the chain was not re-walked. What follows is prior measurement, cited as prior.

**The figure in wide circulation is `215 of 215`,** and it appears at `docs/PRD_APP.md:113`,
`docs/PRD_GOVERNANCE.md:654`, `docs/DESIGN_DECISIONS/0015-...md:18`, and — still — in a live code
comment at `core/src/policy/law_gate.rs:129`. Its origin is a 2026-08-06 census over the trailing
25,000 chain entries:

```
215 decisions · decided_by {'operator': 215} · decided_via {'operator_session': 215}
```

**That figure is superseded, and the supersession is in this repo.**
`docs/DESIGN_DECISIONS/0015-not-same-work-is-claimed-not-assigned.md:495-506` records a full re-walk
of CBP's chain to genesis on 2026-08-09 (126,350 entries):

```
decided_by:   operator 325   kimi-code 3   claude-code 2
decided_via:  operator_session 325         peer_member 5
independence: null 325                     cross_vendor 5
```

Five peer rulings — `claude-code`→`kimi-code` ×2, `codex`→`claude-code` ×2,
`unattributed`→`kimi-code` ×1 — all cross-lineage, all graded `cross_vendor`.

**So the motivating claim as briefed — "the middle rung is built in pieces and has never decided
anything" — is REFUTED, and the refutation makes the case stronger, not weaker.** The rung is not
built in pieces; it is built end-to-end and has been exercised five times. The honest number is:

> **5 of 330 escalation decisions, 1.5%, were made by a peer member. 98.5% were dp.**

0015 §10a states the confound and this PRD carries it forward verbatim rather than quoting the
number bare: **1.5% is pre-board and confounded — it measures availability, not willingness.** No
routing surface existed, so nobody was asked. It is not evidence that members will not rule. The
five rulings are evidence the mechanism works when exercised.

**A verb with no caller is not a capability** (0015 §1). This PRD is about the caller — and
specifically about the thing that would *call*: a stored rung order, consulted at escalation time.

Second-order finding, worth its own line because it is a live defect: **the stale 215/215 figure is
cited inside a code comment at `law_gate.rs:129` that is arguing for a design decision.** That is
`GATE_BYPASS_CATALOG.md:923-924`'s pattern reproduced — a figure that travelled
conversation → PRD → cited authority, wrong by 5–10×, corrected in place with the propagation path
kept. Fixing that comment is not this PRD's job, but naming it is: §6.3 turns it into an acceptance
criterion.

### 1.4 The machinery inventory — what a ladder would be assembled FROM

| construct | site | what it already does | what the ladder needs from it |
|---|---|---|---|
| `EscalationStore::decide` | `gate_escalation.rs:1064` | decider-generic; refuses anonymous | nothing — use as is |
| `tool_gate_arbitrate_escalation` | `handler.rs:13700` | peer rules another member's escalation, NOT-SAME server-side | becomes ONE rung's transport, not the only one |
| `tool_gate_escalation_corroborate` | `handler.rs:13895` | adds a peer FACTOR without deciding; `stance` REQUIRED since #437 (`handler.rs:13935-13958`, schema `:321-356`, `additionalProperties:false`) | **this is the advisory rung's transport** — see §4.2 |
| `tool_arbitrate_appeal` | `handler.rs:3010` | rules a filed appeal; emits the `adjudication` chain event; single-shot | the appeal ladder is the same ladder; §2.5 |
| `tool_witness_adjudication` | `handler.rs:2098` | peer verdict on a value axis (`upheld/partial/refuted/deferred`) with a `method` field | the verdict vocabulary already exists — reuse, do not mint |
| `arbiter::eligibility_for` | `arbiter.rs:227` | clauses 0–4: proven asker, not-the-appellant (direction-aware), not-the-denying-gate, recognised reasoner, grade distance | §5 — extends to rungs unchanged |
| `arbiter::Independence` | `arbiter.rs:82` | `CrossVendor` \| `CrossMember`; **no `CrossSession`, deliberately** (`:92-110`) | the anti-capture floor |
| `arbiter::select_arbiter` | `arbiter.rs:355` | sorts candidates `(liveness, independence, id)` | the nearest thing to routing that exists — but it ranks by REACHABILITY first, and is not a fallback sequence |
| `bar_for(marker)` | `gate_escalation.rs:228` | hardcoded filename → `SingleApprover` \| `SovereignPlusPeer` | **this is the stakes classifier, and it is hardcoded — §2.3 is its replacement** |
| `tool_operating_law` + `law_hash` | `handler.rs:870`, hash at `:1069`, emitted `:1078` | composes the member's law and returns a sha256 over the whole composed body | **dp's "consult the actual law" is SOLVED — §3.3** |
| `escalate_to` token | `law_gate.rs:187` | law names its resolver, as data | **zero consumers — §1.2** |

**Does not exist anywhere** (verified by search): no confidence score on any ruling; no stakes or
tier type in the adjudication path; no ordered decider list. `Bar` (two variants) and
`invited_peers` (`handler.rs:12629`, capped 8, ordered by liveness) are the closest analogues, and
`resolve_invitation`'s own comment (`:12668-12670`) says its ordering is reachability, not merit —
it is an invitation list, not an escalation chain, and nothing consumes it as a fallback sequence.

---

## 2. The ladder as DATA, not code

### 2.1 The rungs, in order

```
  rung 0   HEURISTIC GATE        the shared core, today — deterministic, in-process, sub-ms
  rung 1   POLICY-ENTITY AGENT   dp's middle layer — advisory first, deciding later
  rung 2   HUMAN OPERATOR        the sovereign, today's only real decider
```

Rung 0 is not "the part before the ladder". It is a rung, and it must implement the same interface
(§3) as the others, or the ladder has a special case at its base and the special case is where
divergence lives.

### 2.2 The rung sequence is CONFIGURATION

> **Adding a rung must never require touching the deciding code.**

The stored object is a mapping:

```
(act kind × consequence) -> ordered rung list
```

It lives **beside the other authority data** — the same vault store family
`PRD_ALLOWLISTS.md` §3.4 consolidates (#431's `scope`/`standing`, the allowlist floor,
`PRD_ROLE_SCOPE_BRIDGE.md` §3.1's `clearances`) — and is mutated by the **same operator-walled
path**: challenge-signed operator session, witness-then-widen ordering, atomic vault persist with
rollback, `no_mcp_tool_can_mutate_*` denylist construction. It carries its own monotonic
generation, folded into the composite of §11.

Sketch, deliberately minimal:

```
ladder:
  generation: 7
  rungs:
    - id: heuristic          kind: builtin      threshold: 0.95    max_consequence: low
    - id: policy-agent       kind: agent        threshold: 0.80    max_consequence: med
      binding: { endpoint: <mesh member id>, lineage: <vendor>, mode: advisory }
    - id: operator           kind: human        threshold: 0.0     max_consequence: high
  routes:
    - when: { kind: "governance.*" }          rungs: [operator]
    - when: { kind: "floor.tool.add" }        rungs: [heuristic, policy-agent, operator]
    - when: { kind: "*" }                     rungs: [heuristic, operator]
```

**Bootstrap default is `[heuristic, operator]` for everything** — which is exactly today's
behaviour, expressed as data. That is the migration test: the ladder ships as a no-op, and
`PRD_ALLOWLISTS.md` §3.6.6's ceremony-neutrality argument applies here unchanged. A config that
changed behaviour on the day it landed would be an unstated behavioural change riding a migration,
which is how "shipped ≠ in force" happens in reverse.

### 2.3 `bar_for` is the thing being replaced, and naming it is load-bearing

`gate_escalation.rs:228` is a hardcoded filename match: four specific paths get
`Bar::SovereignPlusPeer`, everything else `SingleApprover`. It is the system's *only* stakes
classifier and it lives in a `match` arm. `PRD_ALLOWLISTS.md` §3.6.5 already proposes
`required_tier(kind, society_consequence) -> Tier` as a stored table for the ceremony axis; **this
PRD proposes `rungs_for(kind, consequence) -> [RungId]` on the same key**, from the same store,
resolved by the same lookup.

One key, two answers: *how much evidence* (the ceremony tier) and *who supplies it* (the rung
list). Two tables would drift to two taxonomies of `kind` with no surface on which to notice — the
same argument §3.6.6 makes for why consolidation enables the seam.

**This PRD commits to the SEAM, not to the table.** The initial routes are deliberately trivial and
reproduce today's behaviour. Populating them is data.

### 2.4 The scope surface joins the same ladder

`http.rs:1679`'s hardcoded `"operator"` (§1.1) is the scope-request path, and today it has no
concept of a decider other than the operator at all — no `decide()` equivalent, no independence, no
factors. It should not grow a *parallel* ladder. It routes through `rungs_for("scope.grant.*", …)`
like everything else, and the literal becomes the resolved rung's identity. Stated here so it is
not mistaken for a non-goal.

### 2.5 The appeal ladder is this ladder

`tool_arbitrate_appeal` (`handler.rs:3010`) is a second adjudication path with its own NOT-SAME
call, its own single-shot check, and its own `routed_to`/`was_designee` fields. It is the same
shape and must read the same config. Two ladders is the two-stores defect one layer up.

### 2.6 Who occupies rung 1 is NOT the seam's business

dp: *"even that can be a neural net, and THEN an agent."*

The rung-1 binding is a `kind` discriminant plus an opaque config blob. The interface (§3) is what
is fixed; the occupant is not. Concretely, all three of these are valid rung-1 bindings under the
same schema and the same call site:

- **a heuristic** — a deterministic scorer, in-process, no network. Occupying rung 1 with a
  heuristic is a legitimate and *useful* state: it is how the evidence bundle and the verdict record
  get exercised before anything expensive is wired.
- **a neural net** — a classifier returning `(verdict, confidence)` with no rationale worth reading.
  It fails the rationale requirement of §3.1 and therefore may only ever hold ADVISORY (§4).
- **an agent** — a full model with tool access that can read the chain and call
  `hestia_operating_law` itself.

dp cites Claude Code's own auto-mode as an existing implementation of the pattern, and the analogy
is exact in the part that matters: auto-mode is a *stored policy about which decisions get referred
upward*, not a fork in the code, and the thing occupying the middle changes without the escalation
path changing. **Stated as a design constraint:** if any code in the deciding path branches on
`rung.kind`, the seam has failed. The only permitted branch is in the *transport* — how the bundle
is delivered and the verdict collected — and that branch lives behind the interface, not in front
of it.

---

## 3. The ADJUDICATOR INTERFACE

### 3.1 One contract, every rung

```
adjudicate(EvidenceBundle) -> Verdict {
    decision:   approve | deny | decline        // decline is first-class, not an error
    rationale:  String                          // required for approve; see below
    confidence: f64 in [0,1]                    // required, always
    consulted:  Evidence[]                      // WHAT IT ACTUALLY READ
}
```

Four notes, each of which is a defect this repo has already paid for:

1. **`decline` is not an error.** A rung that cannot form a view must be able to say so and pass
   the bundle up without the escalation entering a failure state. Today a rung that timed out and a
   rung that abstained would be indistinguishable, and `ref_equality_referee_abstains_not` is the
   general form of that confusion.
2. **`rationale` is required to APPROVE, not to deny.** This is the existing asymmetry at
   `http.rs:2465-2478` and `handler.rs:13784-13793`, stated identically: refusing is the default and
   costs nothing to explain; permitting is what a reader will have to weigh later. Do not invent a
   second asymmetry.
3. **`confidence` is reported, never thresholded by the rung itself.** `arbiter.rs:79` already
   holds this line for `Independence` — *"Recorded, never thresholded here."* The rung emits;
   the ladder compares against the rung's stored threshold. A rung that decided its own sufficiency
   would be `satisfied_by` again (CLAUDE.md's named 2026-07-16 inversion).
4. **`consulted` is what it ACTUALLY read, not what it was offered.** This is the whole
   auditability of the rung. A rung that received the full bundle and read the tool name is a
   filter wearing an adjudicator's clothes, and `consulted` is the only field that can tell them
   apart. It is what makes §4.3's disagreement analysis possible — "the rung and the human
   disagreed" is uninteresting until you can see that the rung never opened the payload.

`decision` reuses the existing vocabulary rather than minting one: `tool_witness_adjudication`'s
`ADJUDICATION_VERDICTS` (`handler.rs:2085`) is `["upheld","partial","refuted","deferred"]` and
`deferred` is the same act as `decline`. Where the two vocabularies must coexist, map explicitly and
assert the map — a third spelling of the same verdict is how `fb_vocabulary_language_bet` starts.

### 3.2 Escalation to the next rung fires on exactly three conditions

- **confidence below the rung's stored threshold** — an uncertain rung defers, it does not guess.
- **consequence exceeds the rung's `max_consequence`** — the rung may be certain and still
  unauthorised. Checked BEFORE the rung is asked, not after it answers, so a rung is never handed a
  bundle it could not have been permitted to decide.
- **the rung declines** — including transport failure, timeout, and unreachability, all of which
  are declines and all of which are recorded distinguishably (`ref_mesh_undelivered_echo`: an
  rc=124 is anti-evidence, and a silent timeout that reads as "no objection" is the single most
  dangerous failure mode this interface can have).

**Exhausting the ladder without a verdict is a DENY, and it is witnessed as such.** Fail-closed,
with a record — because `ref_fail_closed_denies_unrecorded` measured that today's fail-closed denies
leave no trace at all, and a ladder that silently runs out is worse than one that never ran.

### 3.3 Every rung receives the SAME evidence bundle a human would get

> **If a rung sees less than the human would, it is not a rung. It is a filter.**

This is dp's *"able to actually look at the full context"* stated as a schema. The bundle is:

| element | source, today | note |
|---|---|---|
| **the act** | `Escalation.tool_name`, `.marker`, `.stated_detail` (`gate_escalation.rs:283+`) | `stated_detail` is WHAT the act would do — added precisely because intent and effect are different claims and the decider must compare them |
| **the asker's stated reason** | `Escalation.stated_reason` | and its provenance: caller-asserted, worth what a self-declaration is worth |
| **the asker's basis** | `Escalation.asker_basis` (`arbiter.rs:146`) | `Session` vs `Asserted` — clause 0 reads this, and a rung must too |
| **the law snapshot** | `tool_operating_law` (`handler.rs:870`) | **hash-pinned: `law_hash` = sha256 over the whole composed body (`:1069`), covering `layers`, `lists_bound`, `operator_grant`, `scope_grants`, `standing_grants`** |
| **the member's history** | the witness chain, per member | including prior denies and their rules |
| **prior related decisions** | escalations on the same `marker`, with their outcomes | the thing a human cannot hold in their head |
| **the refusal text** | the deny record | including which RULE fired — noting `ref_deny_names_marker`: today's record names the rule, not the act, for a class of four |
| **the existing factor set** | `Escalation.factors` (`gate_escalation.rs:364`) | including any dissent, with its argument and its `independence` grade |
| **the bar in force** | `Escalation.bar`, copied at open | so the rung is judged against the criterion that applied then |

**dp's "consult the actual law" is a solved sub-problem, and this PRD's job is to not re-solve it.**
`hestia_operating_law` exists, is attributed-callers-only, composes society/role/instance layers or
the substituting operator grant, and returns `law_hash`. The rung consults it and **records the
hash it consulted**, which converts law-consultation from a claim into a checkable fact. That is
the difference between a rung that read the law and a rung that remembered it — and it is the
direct remedy for `GATE_BYPASS_CATALOG.md:923-924`.

One known hazard, named because it will bite: `tool_operating_law`'s reply is an **allowlist
re-projection of the hashed body** (`handler.rs:1081-1122`), and the doc comment at `:1082-1101`
records that fields have landed in the hashed body and been silently dropped from the reply four or
five times. **A rung pinning `law_hash` may therefore be pinning a superset of what it was shown.**
AC-8 asserts against it.

### 3.4 The verdict record

Every rung's verdict is witnessed, whether or not it decided anything. Advisory verdicts are the
measurement (§4.3) and an unrecorded advisory verdict is an unmeasurable one. The record carries
the rung id, the verdict, the confidence, the `consulted` list, the `law_hash` relied upon, the
ladder `generation` in force, and the rung's independence grade relative to the asker. Atomic with
the decision, per CLAUDE.md's A clause: a record that omits its evidence-basis fails A even if a
record exists.

---

## 4. Why this is safe to start light — the ladder is itself RATCHETED

`PRD_ALLOWLISTS.md` §3.6 establishes the pattern for *how much ceremony* an act requires: declared,
stored tiers; bootstrap-light; asymmetric ratchet where lowering pays the tier being lowered FROM; a
slow-and-loud deadlock escape. **This section is that ratchet applied to WHO decides.** Same store,
same generation, same operator wall, same escape.

### 4.1 The promotion path

```
  stage A   ADVISORY            the rung records a verdict; the human still decides
  stage B   DECIDES-UNDER-TIER  the rung decides acts at or below a stated consequence
  stage C   WIDER               the tier rises
```

Stage A is a **shadow mode**, and it is the same instrument `PRD_ALLOWLISTS.md` §7 Q2 proposes for
the TOOLS axis: computed, recorded, verdict unchanged. That parallel is not a coincidence and
should be built once.

### 4.2 Advisory has a transport already

A stage-A agent rung does not need new plumbing. `tool_gate_escalation_corroborate`
(`handler.rs:13895`) is exactly the shape: it adds a peer FACTOR to a pending escalation, it
**decides nothing**, it runs NOT-SAME through the direction-blind `eligibility` so a
self-corroboration is always refused (`:13992-14005`), and since #437 its `stance` is required and
explicit with no default (`:13935-13958`) — because an unstated stance once defaulted to
concurrence and recorded a peer's dissent as agreement (specimen `99417cc`).

**The advisory rung is a corroborator that is always asked.** That is the whole delta: today
corroboration is opportunistic and nobody is invited on the `SingleApprover` path; under the ladder,
rung 1 is invited on every routed act, its stance lands as a factor, and the operator decides over
the whole set exactly as `bar_met()` (`gate_escalation.rs:408`) already evaluates it.

Two properties this inherits for free, and both matter: **dissent is evidence, never a veto**
(dp's invitation-semantics ruling, enforced at `handler.rs:14059-14062`), and a factor
**permits nothing by itself** and is witnessed separately so it cannot be laundered into a ruling.
An advisory rung that could block is not advisory.

### 4.3 The promotion criterion must be MEASURED, not asserted

> **Agreement rate with the human decision, over N decisions, per act kind, with disagreements
> preserved as the interesting data.**

Per act kind, because an aggregate hides the mixture — a rung at 95% overall may be at 60% on the
one kind that matters, and `fb_column_whose_meaning_changed` is the general form. The disagreements
are the payload, not the residue: a rung that disagreed and was right is the strongest available
argument for promotion, and a rung that disagreed and was wrong tells you which kind to withhold.

**Stated plainly, because it is the failure mode this whole section exists to prevent:**

> **An advisory rung that is never measured never earns promotion. It sits at stage A forever,
> recording verdicts nobody reads, and the ladder becomes a more elaborate way to do what we do
> today. The measurement IS the mechanism of evolution dp is asking for — not the config, not the
> interface. Those are the plumbing that makes the measurement possible.**

Three guards on the measurement itself, each earned:

- **The denominator names its population.** "Agreement rate" over which escalations, in what
  window, at what grain? A bare rate is true of more than one population.
- **Both arms must be able to fire.** A promotion criterion that can only be satisfied is not a
  criterion. The negative arm — a rung whose measured agreement is below threshold is REFUSED
  promotion, and the refusal quotes the measured number — is the one that proves the gate works.
  `PRD_ALLOWLISTS.md` AC-11 states the identical requirement for the shadow-to-enforce flip.
- **Promotion is an operator act at the ladder store's ceremony tier.** It is not a threshold the
  system crosses on its own. See §5.3.

### 4.4 The deadlock escape applies here too

`PRD_ALLOWLISTS.md` §3.6.4's hazard reappears: ratchet rung 1 into a route as the only non-operator
decider, then have it become unreachable, and the route is unsatisfiable. The answer is the same
answer: escalation to the next rung on decline (§3.2) means an unreachable rung degrades to the
human rather than to a deadlock, and the degradation is witnessed and rendered
(`ladder degraded — rung <id> declining`) rather than silent. A ladder that silently loses a rung
looks identical to a ladder configured without it.

---

## 5. The ANTI-CAPTURE rules

### 5.1 NOT-SAME extends to the ladder, unchanged

`arbiter::eligibility_for` (`arbiter.rs:227`) is the precedent and the implementation. **A rung is
a party to the eligibility computation exactly as a peer member is.** The clauses carry over
verbatim, and each one earns its place here:

- **Clause 0 (`:240`) — the left operand must be proven.** An `Asserted` asker cannot be
  peer-cleared, because NOT-SAME comparing a name a caller typed grades a forgeable operand — and
  an *unrecognised* one as maximally independent (#128). **This applies to a rung with full force:**
  a policy agent grading a forged asker as cross-vendor is the same defect with a faster clock.
- **Clause 1 (`:267`) — a member is never its own adjudicator.** Direction-aware: refusing your own
  request is a `SelfWithdrawal` (`arbiter.rs:54`), granting yourself is `Refused`. A rung occupied
  by member M must not adjudicate M's act, and **an adjudicator must not rule on an act it
  requested** — which is clause 1 read in the ladder's direction.
- **Clause 2 (`:302`) — not the gate that denied.** A rung must not adjudicate a refusal its own
  heuristic produced. This is the clause that bites hardest at rung 0→1: if the policy agent's
  scoring shares a code path with the heuristic gate, clause 2 is being satisfied nominally and
  violated in substance.
- **Clause 3 (`:316`) — recognised reasoner.** Added after `agent-inventory`, an hourly cron, was
  selected as arbiter and graded `cross_vendor` — the strongest tier, for a scheduled script
  (`arbiter.rs:184-205`). A rung binding must resolve to a recognised lineage or the rung is not
  eligible. This is the floor, not a competence claim.
- **Clause 4 (`:326`) — grade the distance**, and record it.

**And the deliberate absence carries over too.** `arbiter.rs:92-110` removed `CrossSession` on the
grounds that a second session of the same member *"is the same model, the same training, the same
dispositions, differing only in what it has read. It is precisely the entity that cannot see this
entity's blind spots."* **A rung-1 agent of the same lineage as the asker is `CrossMember` at best,
never `CrossVendor`, and a rung-1 agent that is the *same member* is nothing at all.** The seam
must record lineage on the rung binding so this is computable rather than assumed.

`PRD_ROLE_SCOPE_BRIDGE.md` §7 Q3's phrase is the right test and this PRD adopts it: a quorum of
same-host processes is **one factor wearing k hats**. A ladder whose rungs share a failure domain
is one rung wearing k hats.

### 5.2 The LADDER CONFIG is governance data

> **Changing which rung decides what is exactly as consequential as changing the law.**

A law that says "deny X" and a ladder that says "rung 1 decides X, and rung 1 approves everything"
are the same policy. So the config lives behind the same wall (operator-gated, witness-then-widen,
no MCP tool reaches it) and under the same ceremony ratchet as the floor it governs.

`PRD_GATE_CONSOLIDATION.md` §5's closure rule is the governing precedent — *"a write that can
redirect which core executes is equivalent to a write to the core"* — and §3.6.3's corollary is
the operative clause: **the control must protect its own registration.**

### 5.3 A rung that can promote itself is the ratchet-defeat one layer up

This is the sharpest rule in the document and it is worth stating alone.

> **No rung may write the ladder config. No rung may adjudicate a change to the ladder config. A
> route whose `kind` is `ladder.*` resolves to `[operator]` and the table returns a refusal for any
> other value — not a rung id.**

`PRD_ALLOWLISTS.md` §3.6.5 uses exactly this shape for `governance.*`: the table **returns a
refusal, not a number**, because an entry returning "tier 3" would imply a price exists. Same here:
an entry naming any rung for `ladder.*` would imply a rung could ever be the decider, and the whole
point is that it cannot.

Ratchet asymmetry, inherited from §3.6.3: **narrowing a rung's authority is cheap; widening it pays
the tier being widened FROM.** Without this, a rung promoted to decide `floor.tool.add` could, in
one step, be routed to decide its own promotion — and the effective authority of every act collapses
to whatever the cheapest rung will approve.

**And the honest concession, per `PRD_ALLOWLISTS.md` §3.6.4:** against a determined actor holding
the operator's UID this buys nothing. hestia is assurance profile A1 (HST-009); every member runs as
the operator. What these rules defeat is the efficiency attractor — the shortest path to "get this
decided" must not run through "re-route the decision to something that says yes." The bypass is
available, expensive, and legible, which is the most an A1 system can honestly claim.

---

## 6. What an agent rung can do that a human cannot — as ACCEPTANCE CRITERIA

dp: *"always there, much faster, able to actually look at the full context, consult the actual
law."* Each clause below is a measurable criterion, not a hope. A rung that cannot demonstrate these
has no argument for existing, because on every other axis a human is better.

### 6.1 No claim-window race (#434) — "always there"

#434 measured the loop racing two timers: `ESCALATION_RPC_TIMEOUT_S = 1.5s` against a 4-call
sequence at ~750ms/call, and a 600s horizon against human latency. This session measured the
downstream form of it repeatedly: **approvals that expired unclaimed** — a human decided, and the
decision arrived after the window it was for. `PRD_ALLOWLISTS.md` §5.2 routes around it rather than
fixing it, and says so.

**AC-L1.** For escalations routed to a decision-capable agent rung, the measured
`decided_at − opened_at` distribution has a p99 inside the claim horizon, over a stated window and a
named population. The arm that must be able to fail: **the same measurement on operator-decided
escalations in the same window is the reference**, and if the rung is not measurably faster the
criterion fails. A rung that inherits human latency through a slow transport has bought nothing.

### 6.2 Full-context reading — "able to actually look at the full context"

**AC-L2.** For every rung verdict, `consulted` (§3.1) names the payload, the law snapshot, and at
least one prior related decision. Asserted on the record, not on a comment. The arm that must fire:
a rung stubbed to read only `tool_name` produces a verdict whose `consulted` list is short, and the
assertion goes RED. Without that arm, the criterion passes on a rung that reads nothing, because
"the field is present" is not "the field is populated with what it claims."

**AC-L3, the sharper one.** For a sample of decisions, the rung's `consulted` set is a **superset**
of what the operator's UI actually displayed. This is the criterion that earns dp's sentence
literally rather than rhetorically: if the rung reads less than the dashboard shows, "full context"
is marketing.

### 6.3 Law consultation by hash, not by memory

The failure mode is documented and this repo has paid for it: `GATE_BYPASS_CATALOG.md:923-924`
records a figure that *"travelled from conversation → PRD → cited authority without ever being
measured, and was wrong by 5–10×."* §1.3 above found a live instance of the same shape — the stale
`215 of 215` still sitting in a code comment at `law_gate.rs:129` arguing for a design decision,
three days after a re-walk to genesis superseded it.

**AC-L4.** Every rung verdict carries the `law_hash` it consulted, obtained from
`hestia_operating_law` within the decision, not cached across decisions. The arm that must fire:
mutate the law between two decisions and assert the two verdicts carry different hashes. A rung
carrying a constant hash is a rung consulting its memory.

**AC-L5.** A rung's rationale that cites a rule must cite a rule present in the snapshot whose hash
it recorded. Falsifiable by construction: strip a rule from the snapshot, assert the rung either
does not cite it or declines.

### 6.4 Availability — the queue drains at machine speed

**AC-L6.** Time-to-first-verdict on the routed queue, measured per rung. The population is stated;
the reference arm is the operator's own time-to-first-verdict on the same kinds in the same window.

**AC-L7, and this is the one that would have caught the 2026-08-07 incident.** No escalation routed
to a live rung expires PENDING. `0015` records the cost of the alternative: two unwanted
`permits_write: true` permits went into force because the peer asked to deny them woke after the
operator had already approved both, and decisions are single-shot. The arm that must fire: with the
rung stubbed unreachable, an escalation DOES expire pending — proving the criterion measures the
rung and not the absence of traffic. A criterion that passes on an empty queue measures nothing;
`fb_zero_iteration_loop_reads_all` is the general shape.

---

## 7. RWOA + S + V self-audit

Per `CLAUDE.md`. Three new surfaces. Constructs named, not line numbers.

```
surface: adjudicator interface (rung invocation)   act: rule on a governance-surface write
S: high/irreversible-in-effect [construct: an approved escalation admits a write to the governance closure; the act it authorises cannot be un-taken]
R: n/a [construct: reachability never authorizes a rung; a REACHABLE rung is not an ELIGIBLE one — arbiter::eligibility_for runs first, and select_arbiter's liveness-first ordering is explicitly a routing input, never a gate]
W: pass [construct: rung identity resolved from a live session (resolve_attributed_caller) for agent rungs, from the ladder binding for builtin rungs; arbiter::eligibility_for clauses 0-4 including the recognised-reasoner floor; EscalationStore::decide refuses an anonymous decider (DecideError::AnonymousDecider)]
O: pass [construct: max_consequence checked BEFORE the rung is asked (§3.2); eligibility computed before decide(); a declined or refused rung leaves the escalation bit-identical]
A: pass [construct: the §3.4 verdict record — rung id, verdict, confidence, consulted[], law_hash, ladder generation, independence — atomic with the decision entry; an advisory verdict is witnessed even though it decides nothing]
V: present [construct: escalation to the next rung on decline/low-confidence/over-tier; ladder exhaustion is a witnessed DENY, never a pass-through; the human rung is terminal and always present in every route]
verdict: PASS — CONDITIONAL on the rung never being the terminal rung for `governance.*` or `ladder.*` (§5.3). If a route ever resolves those to a rung, this block is void.
```

```
surface: ladder config store   act: change WHICH rung decides WHAT
S: high/irreversible-in-direction [construct: re-routing an act kind re-prices every future decision of that kind; acts decided under a widened route cannot be un-decided — the same shape as PRD_ALLOWLISTS §3.6's tier lowering]
R: n/a [construct: reachability never authorizes a config change]
W: pass [construct: challenge-signed operator session (authenticate_operator), same wall as /api/allowlist/* and /api/clearance/*; no MCP tool reaches it — same denylist construction as no_mcp_tool_can_mutate_standing_scope]
O: pass [construct: authorize() before store mutation, before persist, before the composite generation bump and the export]
A: pass [construct: witnessed ladder_route_changed carrying from/to route, kind, consequence, evidence relied upon, operator identity; generation moves]
V: present [construct: §4.4's degrade-to-human on decline means no config change can make a route unsatisfiable; §5.3's `ladder.*` refusal means no rung can route its own promotion]
verdict: PASS — and explicitly NOT a boundary against a determined same-UID actor (A1/HST-009). It defeats the efficiency attractor, not an adversary.
```

```
surface: promotion path (advisory -> deciding)   act: grant an agent rung the authority to decide unsupervised
S: high/irreversible-in-effect [construct: the first act a newly-promoted rung decides is decided; promotion is not a trial that can be rolled back through the acts it produced]
R: n/a [construct: a rung's availability is not evidence of its judgment — this is the R clause in its most tempting form, since availability is exactly what makes a rung attractive]
W: pass [construct: promotion is an operator act at the ladder store's ceremony tier; the rung is never a party to its own promotion (§5.3)]
O: pass [construct: the measured agreement rate is computed and the threshold checked BEFORE the route is rewritten; a refused promotion leaves the config bit-identical and the refusal quotes the measured number]
A: pass [construct: the promotion entry carries the measurement — window, denominator, per-kind agreement, disagreement count — not merely the verdict. A promotion record that omits its evidence-basis fails A even though a record exists]
V: present [construct: demotion is always available and costs strictly less than promotion; §4.4's degrade-to-human is the runtime veto]
verdict: PASS — CONDITIONAL on §4.3's negative arm existing and being green: a promotion gate that has never refused a promotion is an unfired guard, which is a claim rather than a control.
```

---

## 8. Acceptance criteria — falsifiable

Each names the arm that must be able to fail. §6's AC-L1..L7 are criteria too and are not repeated.

- **AC-1 — the ladder ships as a no-op.** With the bootstrap config (§2.2), every escalation
  reaches the same decider, in the same order, with the same record shape as at `dae0aa3`.
  Differential: a corpus of decisions replayed pre- and post-ladder is byte-identical modulo the
  ladder generation field. The arm that must fire: change one route and assert the differential
  goes RED — otherwise the test proves only that the corpus replays.
- **AC-2 — adding a rung touches no deciding code.** Add a fourth rung by writing config only;
  assert it is invoked. Enforced structurally as well: a grep-level assertion that the deciding path
  contains no branch on `rung.kind` outside the transport module (§2.6).
- **AC-3 — no rung writes the ladder.** `no_rung_can_mutate_ladder_config`, constructed like
  `no_mcp_tool_can_mutate_standing_scope`; plus a behavioural assertion that a route naming any rung
  for `ladder.*` or `governance.*` is REFUSED at write time, with the refusal naming the clause.
- **AC-4 — NOT-SAME binds rungs.** A rung bound to member M, adjudicating M's escalation, is
  refused, and the refusal is witnessed as `gate_escalation_arbiter_refused` exactly as a peer's is.
  Positive control in the same test: the same rung adjudicating a DIFFERENT member's escalation is
  eligible — without it, a store that refuses every rung passes.
- **AC-5 — an adjudicator does not rule on an act it requested.** Distinct from AC-4 and separately
  asserted, since the requester and the subject can differ (`ref_chain_names_performer_not`: the
  chain proves who PERFORMED, and has no field for who ASKED — so this criterion may require a new
  field, and that is a finding, not a blocker).
- **AC-6 — same-lineage rungs grade CrossMember, never CrossVendor.** Property test over rung
  bindings and asker ids, reusing `arbiter::lineage`. And: an unrecognised rung binding is
  INELIGIBLE (clause 3), asserted with the `agent-inventory` case as the fixture.
- **AC-7 — decline, timeout, and unreachable are three distinguishable records**, and none of them
  reads as concurrence. The arm that must fire: a rung stubbed to hang produces a record that is not
  the record a rung stubbed to decline produces.
- **AC-8 — `law_hash` covers what the rung was shown.** Assert the set of top-level keys in
  `tool_operating_law`'s reply equals the set inside the hashed body — the drift documented at
  `handler.rs:1082-1101`. This is the criterion that keeps AC-L4 honest: pinning a hash over a
  superset of what you read is pinning nothing.
- **AC-9 — the ladder moves the composite policy revision.** Change a route; assert the composite
  digest of §11 changes. A routing change invisible to the composite is a policy change no replica
  can detect. Mirrors `PRD_ALLOWLISTS.md` AC-12.
- **AC-10 — ladder exhaustion denies, loudly.** Configure a route whose every rung declines; assert
  a DENY lands with a witnessed `ladder_exhausted` record naming each rung and its decline reason.
  The arm: with one rung answering, no such record is written.
- **AC-11 — the promotion gate can refuse.** Feed a measured agreement rate below threshold; assert
  promotion is refused and the refusal quotes the number. Per §7's conditional verdict this is not
  optional.
- **AC-12 — an advisory rung cannot block.** Assert an advisory rung's `deny` verdict leaves the
  escalation PENDING and decidable by the operator — inherited from the corroborate path, and
  asserted here because §4.2's reuse is a design claim about a surface, not a comment.

---

## 9. Open questions — and the meta-point

**The meta-point, stated in the document because it is the document's reason for existing:**

> This PRD exists so that OTHER PRDs' open questions become **configuration** rather than
> **rulings**. Every question below that this PRD leaves open is one the ladder itself must answer
> per-case at runtime — which means the correct output of this section is not a set of rulings to
> request from dp, but a set of values with declared defaults and declared mechanisms of change.
> Where a question below reads as "needs a ruling," that is a defect in this section, not a request.

**Q1 — what is the `kind` taxonomy, and who owns it?** Shared with `PRD_ALLOWLISTS.md` §3.6.5
(which enumerates `floor.*`, `member.*`, `governance.*`) and with
`PRD_ROLE_SCOPE_BRIDGE.md` §7 Q1 (the permission-class vocabulary). **Extension point, not a
ruling:** one taxonomy, one authoritative home, stored beside the floor, versioned with the
composite. Initial value = §3.6.5's enumeration verbatim, extended with `scope.*`, `appeal.*`,
`ladder.*`. It evolves by operator edit at the ladder store's ceremony tier. The measurement that
would justify extending it: a route that must be expressed and cannot be, recorded as a
`kind_unexpressible` telemetry row rather than argued about.

**Q2 — what is `consequence`, and is it the same scalar as `PRD_ALLOWLISTS.md` §3.6.5's society
consequence?** Leaning yes, one scalar, one store — two would drift. **Extension point:** initial
value `research-single-host`, operator-set, ratchetable. Left open here deliberately: this is a case
where the ladder cannot decide for itself, because the scalar describes the society, not an act.

**Q3 — how is a rung bound to an actual entity?** A mesh member id, an endpoint, an in-process
handler — and how is that binding authenticated at invocation time? Sharpest sub-question: a rung
bound to a mesh member inherits the mesh's delivery semantics, and this repo has measured that a
JSON body is not a sent notice, that notices are not FIFO, and that a dead wake eats a notice. **A
rung reached over a channel with those properties will silently look like `decline`.** §3.2 makes
that safe (decline escalates) but AC-L6 makes it visible, and the visibility is the point.

**Q4 — does the appeal ladder and the escalation ladder share one route table?** §2.5 says yes.
Open: whether `tool_arbitrate_appeal`'s `routed_to`/`was_designee` fields become the ladder's
routing record or a second one. Leaning: they become it. The `was_designee` field already encodes
"the ladder named you and you answered" versus "you answered anyway," which is a distinction the
ladder needs and would otherwise re-invent.

**Q5 — is `confidence` comparable across rung kinds?** A heuristic's 0.8 and an agent's 0.8 are not
the same quantity, and thresholding them against one stored number is `fb_column_whose_meaning_changed`
waiting to happen. **Extension point:** thresholds are stored **per rung**, never globally, which
makes them incomparable by construction rather than by convention. The open part is whether
cross-rung comparison is ever needed; if it is, calibration is required first and the calibration is
a measurement, not a constant.

**Q6 — what does an agent rung do about #440's own FP class?** The gate false-positives on command
text mentioning its own hook filenames; an agent rung reading a bundle that quotes a refusal may
itself trip a gate reading its output. Not a blocker; named because it is the shape of defect that
only appears once a rung is actually reading refusal text, and it will be surprising in the moment.

---

## 10. Non-goals

Not building the policy agent — this PRD is the socket, not the plug. Not fixing #434 (§6.1
measures around it; the fix is #434's). Not re-designing the escalation store, the vault, or the
gate's decision topology — this consumes them and names them where it depends on them. Not touching
`arbiter.rs` — the NOT-SAME rules extend to rungs unchanged, and any change to them is a change to
appeals too and belongs in its own PR. **Not populating the route table** (§2.3): this PRD commits
to the seam and to a bootstrap table that reproduces today's behaviour; populating it is data and is
marked as such rather than pre-filled with routes nobody measured. **Not correcting the stale
`215/215` figure at `law_gate.rs:129` and in the three PRDs that cite it** — named in §1.3 so it is
not lost, but a code comment fix does not ride a docs-only PRD.

---

## 11. Convergence: ONE composite policy revision, ONE horizon

**GPT's convergence requirement, relayed by dp (2026-08-14), and it binds this PRD and both of its
siblings:**

> Both PRDs must share **ONE composite policy revision/digest** and **ONE horizon bounded by every
> contributing authority** — standing grants, allowlists, floor, clearances, occupancy, manifest
> generation — rather than each inventing certification semantics.

This document adds a seventh contributing authority — the **ladder generation** — and it must join
the same composite rather than minting an eighth certification story.

**Composite revision.** A single digest over the tuple of every contributing authority's generation:

```
composite_revision = H( standing_generation, allowlist_generation, floor_generation,
                        clearance_generation, occupancy_generation, manifest_generation,
                        ladder_generation )
```

Any authority moving moves the composite. `PRD_ALLOWLISTS.md` AC-12 already requires that an
allowlist edit move `law_hash`; §8 AC-9 requires the same of a route change. **One digest, and
`law_hash` is where it surfaces to members** — a member pinning `law_hash` learns that the ladder
changed, exactly as it learns that a grant appeared (`handler.rs:1018`, `:1033`, `:1048`).

**Composite horizon.**

```
horizon = min( now + STANDING_SNAPSHOT_TTL_SECS,   earliest covered expiry across ALL authorities )
```

`PRD_ALLOWLISTS.md:180` already states this for the standing store (`min(now + TTL, earliest covered
expiry)`, reusing `STANDING_SNAPSHOT_TTL_SECS`) and `PRD_ROLE_SCOPE_BRIDGE.md:141` re-states it for
clearances and occupancy. **They must be the same expression, evaluated over the union**, not three
similarly-worded expressions in three documents. A rung binding with an expiry is a covered expiry
and bounds the horizon like any other.

**Why this is not bookkeeping.** Three PRDs each minting a generation, a digest and a TTL produces
three certification semantics that agree until the first time they do not — and the first time they
do not is a snapshot that is fresh by one document's rule and stale by another's, admitting an act
under a policy that had already changed. One composite has one answer.

---

## 12. What this PRD would look like if it were wrong

Stated because a design PRD with no stated failure mode is a proposal wearing a design's clothes.

**The strongest case against it:** the middle rung's problem is not routing. The five peer rulings
of §1.3 happened without any ladder, and 0015's own remedy was a *board* — make the work visible and
claimable — not a *router*. If the binding constraint is that members do not look, a route table
that assigns work to a rung that is not watching produces the same 98.5%, now with more config.

**What would show it.** AC-L6 and AC-L7 are the discriminating measurements: if routed escalations
still expire pending, or time-to-first-verdict does not separate from the operator's, the ladder is
plumbing for a problem it does not have. That is a productive failure and it eliminates a
possibility — but it should be measured at stage A, before anything is promoted, which is what §4
is for.

**The weaker case, which this PRD accepts:** the ladder is not the mechanism of evolution. §4.3's
measurement is. The ladder is what makes the measurement possible, and a ladder built without §4.3
being built alongside it is the well-known shape where an advisory surface accumulates records
nobody reads.
