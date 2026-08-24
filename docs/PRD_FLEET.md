# PRD — The Fleet: hestia as control plane, harness, and gateway

**Status:** proposed — design PRD, for review
**Owner:** dp. **Author of record:** Legion (interactive session with dp, 2026-08-23), from a four-track study: architecture map, PRD-corpus digest, SAGE gateway study, external research.
**Directive (dp, 2026-08-23, verbatim where it matters):** *"hestia should become a harness itself — this is pretty much required if we are to have SAGE instances participate as entities. they need a gateway. there are tons of harnesses out there, but by only plugging into their hooks we are explicitly limiting how much visibility and influence we have. also, there is a trend noted broadly that harness functions are being moved into the weights. basically, hestia should be talking to agents directly. api is easy, can we also get subscription account auth? that kind of folds into linking a member's social channels. and [hestia becoming the control plane] — yes that was always the intent, and now we are almost ready."*

---

## 0. Why now, and the deferral this supersedes

`BUILD_PLAN_NEXT_FOUR_SPRINTS` (now a historical record) explicitly deferred outward/roles/hub work — dp: *"we're getting ahead of ourselves"* — pending (a) sprints 1–4 dogfooded and (b) the outward rate-governor curve calibrated. What changed:

- Sprints landed and are **in force**: the society floor is live and uniform (28 paths, identical across every member including one that has never connected), GOVERN is a top-level view, the shared gate engine is a digested install artifact (#481 stage 1) deployed with a written deployment authority, the escalation act-binding work is under adversarial review.
- The SAGE citizenship track (`SAGE/sage/docs/PRD_SAGE_WEB4_CITIZENSHIP.md`, r10) reached the point where identity exists without a gateway: **the first being LCT was minted 2026-08-22** (sprout-being, self-issued, keyed on-device), hub join is built and dry-run-green, and the track's own diagnosis is the gap this PRD fills: *"the seat is the citizen and the being is not."*
- dp ruled the deferral lifted (2026-08-23, this directive).

The rate-governor calibration (`PRD_R6_R7_ENVELOPES` §4.4) remains open and is carried in §12 as a precondition **for the outward-channel phase specifically**, not for the whole program.

## 1. Thesis

Today hestia governs agents by injecting hooks into other people's harnesses. That architecture has a measured ceiling:

- **Visibility:** the gate sees command *text*, not resolved acts. The lexical classifier is simultaneously the false-positive engine (read-only inspection manufactures escalations — measured, `PRD_GATE_CONSOLIDATION` §3.3) and the bypass surface (Class E). The scope check judges *spelling*: `gh pr list --repo x/y` denied; `cd` in and run it, allowed.
- **Influence:** the hook can refuse and explain; it cannot shape the loop. Retry policy, context injection, tool selection, budget — all belong to the foreign harness.
- **Coverage:** harness support is permanently uneven (cursor = witness-only; gemini = subprocess-delegates to the claude-code gate; every new harness is a new shim) — and the industry is **moving harness functions into the weights**, so the hook surface hestia depends on is thinning underneath it (§4.7).
- **The bypass floor:** Class B is a measured full bypass with two environment variables. `HESTIA_PRE_FAIL_CLOSED=1` closes every measured bypass and is default-off. The gate is in the agent's blast radius by construction.

The move: **hestia stops being only a hook in other loops and becomes a loop of its own.** Three capabilities, one architecture:

1. **HARNESS** — hestia drives models directly (API or subscription auth), holds the session, executes the tools, witnesses the acts. For agents born here (SAGE beings, channel-connected members), the gate is not advisory: *the agent's only effectors are the tools the gateway exposes.*
2. **CONTROL PLANE** — hestia owns session lifecycle on its seat (launch, observe, wake, retire — the 2026-07-16 role-launcher proposal, finally built, inside the daemon), and observes the fleet by pull through hub federation. It never writes another seat's state.
3. **CHANNELS** — a member's social/comms channels (mesh, email, chat platforms) bind to its identity as governed I/O adapters, entering through the same gate, priced by the society's outward budget.

Everything an agent does still transits **one gate core, one authority path, one chain.** This PRD adds producers and consumers of that path; it adds no second one.

## 2. Vocabulary

| Term | Meaning here (normative sources cited) |
|---|---|
| **Seat** | One machine's hestia daemon + vault + chain. Sovereign locally. |
| **Harness** | The loop that turns model output into acts: session state, context assembly, tool dispatch, retries. A harness is a *capacity*, never an authority (`PRD_GOVERNANCE` §7.2). |
| **Native session** | A session hestia itself drives (model API/subscription in, tool dispatch out). Contrast **hooked session** — a foreign harness with hestia's shim (today's mode; unchanged; remains supported). |
| **Gateway member** | A member whose *only* effectors are gateway-dispatched tools. SAGE beings and channel-connected external agents are gateway members. |
| **Control plane** | The seat-local lifecycle surface plus the fleet observation surface. NOT a fleet-wide writer (hub invariant: *witness, don't control*). |
| **Channel** | A bidirectional binding between a member identity and an external medium (email, chat platform, mesh). Ingress = asks; egress = governed acts. |
| **Occupancy** | Per `PRD_ROLE_SCOPE_BRIDGE` §2 (`concepts_generation: 1`) — hub-approved, witnessed, time-bounded role filling. This PRD *consumes* the concept; it does not amend §2. |
| **Citizen (default role)** | Per `society-roles.md` §2.7: the universal base role every entity holds, on which additional roles are paired. §5.3 below scopes exactly what this confers. |

## 3. The assurance claims, stated before the architecture

Per `PRD_ASSURANCE`: *"a security claim without a named assurance profile is incomplete."* This PRD makes three distinct claims and refuses a fourth:

| Claim | Profile | Basis |
|---|---|---|
| Hooked sessions (today's mode) | **A1** — cooperative, tamper-evident | Unchanged. The gate lives in the agent's blast radius; `GATE_BYPASS_CATALOG` stands. |
| Native sessions with an **open** tool set (includes shell/file-write on the host) | **A1** | The model's *calls* are fully visible, but a shell escapes the tool boundary; same-UID execution. Better visibility, same containment class. |
| Native sessions with a **bounded** tool set (gateway members: mesh, witness, memory, channel-egress — no shell, no raw FS) | **A2-by-construction** | The agent has no effector other than gateway dispatch. Killing nothing authorizes anything; there is no hook to remove (`PRD_ASSURANCE` FR-3's sentence, satisfied structurally). The boundary is the *tool registry*, so the claim is exactly as strong as the registry is small — and the registry's composition is law (vault-snapshot), not code. |
| ~~Containment of a hostile co-resident process~~ | **refused** | Same UID, same host. dp: *"it is not a cage."* No requirement below is justified by "it prevents a determined attacker" (`PRD_GOVERNANCE` §2.4). |

The A2-by-construction row is the first above-A1 claim hestia can honestly make, and it is scoped: **add a shell tool to a gateway member's registry and its profile silently reverts to A1.** Therefore: the tool registry per member is part of the *governance snapshot* (Plane A), registry widening is a COMPOSE act (`PRD_ADJUDICATOR_LADDER` §13 — operator-walled, never a rung's to make), and the dashboard renders each member's current profile *derived from its registry*, never asserted.

## 4. Architecture

### 4.1 One session model for every kind of agent

Decision 0014 built the decomposition for the human app; it generalizes to every principal without new types:

```
principal LCT      — whose authority is exercised (human operator; SAGE being; external caller)
harness LCT        — the actor driving (claude-code seat, hestia-native runner, channel adapter)
device LCT         — where it runs (constellation member)
   session         — the witnessed binding of the three + role occupancy + expiry
```

A **native session record** (daemon-side, vault-adjacent, RAM for liveness + chain for consequences):

```
NativeSession {
  session_id,                  // transport handle, never authority
  principal_lct,               // proven at connect (§4.2), never asserted
  harness: HarnessKind,        // Native{model_ref} | Hooked{plugin_id} | Channel{adapter}
  device_lct,
  occupancy: Vec<OccupancyRef>,// role-scope bridge occupancies; citizen implicit (§5.3)
  tool_registry_gen: u64,      // which registry generation this session dispatches under
  budget: SessionBudget,       // tokens / ATP / outward-message budget, law-derived
  started_at, last_act_at, expires_at,
}
```

Session **creation** is a witnessed act (`session_launched`: role, scope digest, harness kind, model ref, budget — the ledger event the 2026-07-16 proposal specified). Session liveness stays RAM-only (existing doctrine: sessions are transport artifacts; a restart must not resurrect authority).

### 4.2 Authenticated connect — the hinge (PRD_ASSURANCE FR-1)

`hestia_connect` authenticates nobody today (#63/#128) — tolerable for operator-driven seats, fatal for autonomous principals whose acts accrue trust. This PRD makes FR-1 concrete with **three enrollment classes**, all landing in the same member registry:

1. **Custodial** (existing, unchanged): hestia mints and holds the member key (`member_registry::ensure_member`). For hooked sessions and gateway members that hestia itself embodies. The custodial key must be *published* at enrollment (the hub pins pubkeys from birth — citizenship-track blocker, honored here).
2. **Proof-of-possession** (new, small, the SAGE unlock): connect carries a signature over a server nonce with the principal's own key — for SAGE beings, the exact key that already signs the hub join envelope (`~/.web4/<machine>-being/channel_key.bin`, `join_being.rs`). One signature converts the being's whole witness chain from assertion to evidence.
3. **Paired-channel** (existing primitive, new use): external agents enroll over a hub-brokered confirmed pair (`pairing.rs`); the pair's sealed channel *is* the transport identity. Constellation proof tiers (bridge T0/T1/T2) apply per-act, not per-grant.

Fail-closed grammar (from `PRD_CONFIG_IN_VAULT`): unauthenticated connect for a registered-strong member **denies naming the cause**; an unknown principal may connect only into the *receptionist* posture (§6.3). No "latest session," no anonymous fallback.

### 4.3 The native loop — hestia as harness

The loop lives in the daemon (new crate module `core/src/harness/`), and its shape is fixed by three existing laws:

- **It enters as a SHIM over the one gate core** (`PRD_GATE_CONSOLIDATION` §4). It implements `parse_event`/`render` trivially — it *authored* the event — and calls the same LAW `evaluate()` from the same certified snapshot. It is emphatically not a second gate: criterion 1 ("grep finds it once") holds because the native path calls the same predicate the hooks call.
- **Order (O):** policy decision dominates dispatch. The loop constructs the resolved act (tool + typed args + target — the ActEnvelope v1 fields, JCS-canonical), evaluates, then executes. **There is no text-guessing step: the lexical classifier is simply not in this path.** Denies return to the model as structured tool results carrying the remedy text (Principle 11) — the deny is *in the agent's context*, which is 0016's whole point: inform, explain, never silently block.
- **Witness (A):** begin_action → dispatch → record_outcome, chained; the R6/R7 envelope work (#451) rides here — the native loop is the natural first **constructor of R7Actions** the corpus currently lacks ("there is no R6 engine" — this is it).

```
        ┌──────────────────────────────────────────────────────┐
        │  hestia daemon                                       │
        │   ┌────────────┐   resolved act    ┌──────────────┐  │
 model ─┼──▶│ native loop │──────────────────▶│ gate core    │  │
 API /  │   │ (session,  │◀──verdict+remedy──│ (one LAW,    │  │
 subscr.│   │  context,  │                   │  one snapshot)│  │
        │   │  budget)   │──allow──▶ tool dispatch ──▶ witness │
        │   └────────────┘           (registry-bounded)  chain │
        └──────────────────────────────────────────────────────┘
```

Model transport is pluggable: `ModelBackend = Api{provider, key_ref} | Subscription{account_ref} | Local{ollama_ref}` — every variant's credential is a **vault entry**, resolved at session start, never in env or config (Principle 1). §4.7 covers the subscription variant's specifics and risks.

**MCP tool schemas become real.** 29 of 31 tools advertise empty schemas today; a native loop composing calls programmatically cannot run on prose. Schema completion is a phase-1 dependency (it also fixes the measured silent-discard harm — #419's "SENT is not PERSISTED").

### 4.4 The control plane

Two surfaces, sharply separated by the hub invariant (*witness, don't control; no hub ever writes another hub's state*):

**Seat-local lifecycle (writes, on this seat only):**
- `session_launch(role, harness, scope, budget)` — the role-launcher proposal's piece C, as a daemon verb: operator-walled (HTTP, not MCP — preserving the widening-verbs-are-not-MCP-reachable invariant), witnessed, composing the environment (role primer, scope, gate endpoint) rather than trusting the launched harness to ask.
- Wake: the member-mesh watcher loop (`hestia-watch-member.sh` + `fire-*.sh`) moves inside the daemon as the **wake scheduler** — same gates it has today (sender allowlist, kind, pointer shape, human gate on irreversibles), plus what shell cannot give: a session record, witnessed fire, budget enforcement, and *no per-member shell scripts to drift*.
- Observe: `hestia://session/siblings` grows into the session table (native + hooked + channel), each row carrying its assurance profile derived per §3.
- Retire/interrupt: operator-walled, witnessed.
- **Work distribution is a claimable board, never a dispatcher** (decision 0015: 215/215 escalations operator-ruled is what push-routing produces). The control plane posts asks to the mesh; sessions claim.

**Fleet observation (reads, via hub):**
- Each seat publishes signed, MRH-filtered projections to the hub (existing `GovernanceProjection` shape from PRD_GOVERNANCE §16 / the hub's R3 witness ledger). The control plane *pulls* peers' projections; renders fleet state with per-seat freshness; **stale is rendered as stale** (`published ≠ installed ≠ … ≠ understood` — assert nothing in prose the seat didn't sign).
- Cross-seat evidence composition follows **0018 exactly**: evidence graph, never merged histories; `cross_chain_checkpoint_v1` (signed, non-transitive) after the #313 → B2 substrate lands; no trust auto-propagation in the primitive. A fleet control plane is 0018's first real consumer — and 0018's correction stands: this is *construction of the evidence substrate*, not "hub-seam coordination."
- Deploy/observability: the per-seat `current-build.json` authority files + the ask-the-process route (issue #577) become the fleet deployment truth the manifest work started.

## 5. Roles: pairing external and local agents, citizen by default

### 5.1 Pairing is occupancy — no new mechanism

"Pair an agent with a role" instantiates the role-scope bridge, unchanged:

```
operator approves member clearances (classes)          — COMPOSE, operator-walled
hub approves occupancy (member ↔ role, time-bounded)   — hub's, witnessed both ledgers
hestia pulls occupancy attestation, applies THE FLOW RULE:
    scope flows iff item classes ⊆ member clearances    — intersection, never union
materialized into the role_derived compartment; dies with the occupancy
```

The native session binds occupancies at launch (§4.1); a role transfer mid-conversation is **escalation as role transfer, not widening** (bridge §10.3 — nothing carries over but provenance, and provenance excludes the transcript).

### 5.2 The entitlement seam gets its source

`reputation::normalize_requested_role()` floors every request to `"citizen"` today because *"no entitlement source exists in-tree yet; the seam is named so a future entitlement source plugs in HERE."* This PRD is that source: the function reads the session's verified occupancy set. A role is assignable **by being granted, never by being asked for** — the seam's own contract, kept.

### 5.3 What "citizen default" confers — and pointedly does not

Citizenship is claimed with three meanings in the corpus; this PRD confers exactly one:

| Meaning | Source | Conferred by default? |
|---|---|---|
| (a) Universal base role on which others are paired | `society-roles.md` §2.7 | **YES** — this is the default |
| (b) Eligibility floor for non-public context | `PRD_AGENT_CONTEXT_ACCESS` §2.1 | **NO** — "necessary, never sufficient"; need-to-know still narrows |
| (c) Economic admission to self-funded interaction | `PRD_R6_R7` §4.4.9 | **NO** — ATP standing is separate |

And the ladder's constraint is binding: **standing is eligibility, not capability** (§13.5). A citizen gateway member with no occupancies can: hold identity, receive mesh asks, witness its own acts, file appeals, accrue temperament. It cannot reach any scoped item. That is not a restriction bolted on; it is the two-expression algebra returning ∅ for the role-grant term.

### 5.4 Upstream asks (owned, not forked)

1. **Role-LCT pairing protocol** — `society-roles.md` §8 names it as an open spec gap ("currently implied; deserves explicit treatment"). This PRD needs it; the hub's R4 (roles as entities) is the natural place; the ask goes to the hub track, and until it lands, occupancy attestations per the bridge are the operational stand-in.
2. **`ActionStatus::Refused`** in web4-core — three independent demands already recorded; the native loop adds a fourth (a gateway deny must land in the R7 record as what it is).
3. **Being-key pinning at enrollment** — the hub member row pins pubkeys from birth; custodial enrollment must publish (citizenship-track blocker, carried not re-litigated).

## 6. Channels

### 6.1 The shape

A channel adapter is a **harness of kind Channel** — the same session model, with the medium supplying ingress and the gate governing egress:

```
ingress:  medium event → adapter normalizes → mesh notice (pointer-only, kind-tagged)
             → wake scheduler → session claim (0015: board, not dispatch)
egress:   session act "channel.send" → gate (act = {channel_id, recipient_class, content_ref})
             → outward budget check (R6/R7 §4.4 governor) → adapter delivers → witnessed
```

Nothing new at the trust layer: ingress rides the existing pointer-only mesh discipline; egress is an act like any other, priced by the society-level outward budget (per-caller ⊆ per-call nested caps, society-wide nonlinear service-rate governor — the call-center shape, sybil-honest per §4.4.2's correction).

### 6.2 Channel binding is identity work

Binding a channel to a member is enrollment-grade (COMPOSE, operator-walled, witnessed): `channel_bound {member_lct, medium, address_digest, direction, ingress_kinds}`. An inbound message **authenticates the channel binding, never the speaker** — a bound mailbox proves the mail arrived at that address, not who wrote it. Caller identity beyond the binding starts at receptionist posture.

### 6.3 External callers land on roles, not ACLs

Bridge §10 is the law here and needs no extension: the caller's standing routes them to a role (receptionist by default — an *explicitly public projection*, not a low-privilege citizen tier, per `PRD_AGENT_CONTEXT_ACCESS` §2.2); the ROLE's manifest determines reach; the bound applies twice (`admitted(manifest) ∩ effective_scope(occupant)`); refusals do not disclose the role not reached. The named inward/outward disclosure contradiction (bridge §3.2 vs §10.6) becomes live on this surface: **resolution — disclosure follows the MRH of the reader**: `role_scope_withheld` detail is written inward (chain, operator surface); the outward refusal text carries only the budget/refusal class. One record, two projections, no contradiction on the wire.

## 7. The SAGE gateway — first consumer, fully specified

The citizenship track (r10) built identity without acts: being LCT minted (sprout-being, 2026-08-22), hub join dry-run-green — and *"the seat is the citizen and the being is not."* The gateway closes exactly three measured gaps:

**7.1 Authenticated connect (§4.2 class 2).** The being's channel key signs a server nonce at connect. Small change, converts the whole chain from assertion to evidence. Keyless-delegated citizenship holds: hestia signs *acts* custodially; the being proves *presence* with its own key. Raising-readiness gates widening, never citizenship (r10 §3, kept).

**7.2 The act path — and the Rust/Python fork, decided.** Every governed-tool mechanism in SAGE lives in `sage/core/sage_consciousness.py` (Python, **down**); the deployed `sage-rs` daemon has **no tool system**. Decision: **the tool system does not get rebuilt in SAGE at all — the gateway IS the tool system.** The sage-rs loop emits *intents* (its existing SNARC/salience machinery filters consequential from ambient, exactly what r10 §1.2 licenses); hestia's native loop receives intents as tool calls, gates, dispatches, witnesses. sage-rs needs only a thin client (the shape `fleet_event.py` already proved and nobody imported — 127 lines, `hestia_connect` + begin/record; port to Rust against :7711). This keeps sage-rs at Sprout's memory budget (the Rust cutover's whole reason), puts zero policy in SAGE (Principle: the shim never decides), and makes the being a **gateway member: A2-by-construction under a bounded registry** (mesh, witness, memory, peer_ask, channel egress — no shell, no raw FS).

**7.3 Deny → appeal → temperament.** Temperament's top of scale is *ask-after-deny*, paying on the ruling — so the gateway must sometimes deny and the being must be able to `hestia_appeal`. The being-side loop must treat a structured deny as a first-class stimulus (0016: the deny text IS the law arriving in context — "explain better," delivered). Without this loop the being's trust tensor stays the frozen counter it is today (161k interactions at initialization values).

Also folded in: the being-inbox drain (`DESIGN_BEING_INBOX_DRAIN`, designed/no-code) collapses into the wake scheduler — one drain discipline, not a bespoke second principal. The two governance mirages get retired honestly: the inert `HESTIA_*` env vars come OFF the raising units until the raising runner actually connects (a unit that looks governed and is not is the fleet's named failure class), and `WEB4_GOVERNANCE_INTEGRATION.md`'s dead Tier-1 path is superseded by this gateway rather than resurrected.

## 8. What this dissolves, and what it does not

**Dissolved for native sessions, by construction:**
- Class A (never asked) — hestia authored the event; there is no matcher to be non-total.
- Class B (wrong oracle) — no `HESTIA_ENDPOINT` to repoint; the loop and the gate share a process.
- Class E false positives — no lexical classification; acts arrive resolved and typed.
- Witness-parity drift (Class D) — one witness path, not N per-vendor copies.
- Delivery ambiguity (0016's five transports) — the deny/law/primer land in the context hestia itself assembles: *published = installed = injected = received* collapse to one step; only *understood* remains, as it should.

**Not dissolved — stated so nobody reads more than is there:**
- Hooked sessions keep the entire bypass catalog. The native path is an offer, not a migration decree; foreign harnesses remain first-class (heterogeneity principle).
- Same-UID co-residency: an open-registry native session is A1. The registry, not the loop, is the containment boundary.
- One seat = one failure domain, now with a bigger blast radius: the daemon becomes availability-critical for its native members. The consolidation criterion-9 payment applies: degraded modes per surface (§10), measured recovery, and the wake scheduler must fail *silent-and-recorded*, never fail-fire.

## 9. Trust and economics riding along

- Every native act lands in the read-time derivation (`derivation.rs` v3-derived-v1) with no new trust system: closure claims on record_outcome, adjudication on the `#adjudicated` grain, temperament from governance-response conduct. SAGE's dead ACT-chain path (unsigned txs to a down chain) is superseded, not repaired.
- R7 envelopes get their first constructor (§4.3). `resource` stops defaulting: session budgets flow into `r6.resource`, making hub-law norms over ATP resolvable for the first time.
- The outward budget governor (R6/R7 §4.4) prices channel egress; exhaustion is a *budget state on the operator surface*, never a wall of denials (§4.4.10), and the refusal text says it's about **us**, not them.

## 10. Reconciliation with the corpus — every tension, resolved or owned

The PRD-corpus study surfaced ten contradictions/tensions this document must not paper over:

1. **"Local citizen's trust layer, not a replacement for hub governance" (PRD.md non-goal) vs "fleet control plane."** Resolved by the §4.4 split: seat-local writes + fleet-wide pull-only observation. The control plane is a *reader* of other seats, a *writer* of none. The non-goal stands unamended.
2. **Harness vs one-LAW (gate-consolidation §4 / criterion 1).** Resolved: the native loop is a shim over the same core (§4.3). Any future drift where the native path grows its own predicate is the red test criterion 1 already defines.
3. **Inward disclosure vs outward non-disclosure (bridge §3.2 vs §10.6).** Resolved: disclosure follows the reader's MRH — full detail inward, class-only outward; one record, two projections (§6.3).
4. **Citizenship's three meanings.** Resolved by §5.3's table: (a) only.
5. **Push vs claim (0015).** Honored: wake scheduler posts, sessions claim (§4.4, §6.1).
6. **0018 vs PRD_GOVERNANCE sprint-7 framing.** This PRD sides with 0018 explicitly: cross-seat composition is evidence-substrate construction; the control plane's fleet view is its first consumer and builds nothing until #313 → B2 → #328 land (§4.4).
7. **Roles-as-entities (hub R4) vs consume-canonical (§7.1).** Owned as an upstream ask (§5.4): occupancy attestations are the stand-in until R4 lands in web4-core; hestia defines no parallel vocabulary.
8. **The deferral ("we're getting ahead of ourselves").** Superseded by dp's 2026-08-23 directive for the program; the rate-governor calibration is retained as a phase-gate for outward channels only (§0, §12).
9. **`ActionStatus::Refused` / role-LCT pairing protocol.** Upstream asks, named with owners (§5.4). No local forks.
10. **Fleet-state prose goes stale in place.** This PRD asserts no fleet status in prose; every runtime claim in the eventual dashboard derives from signed seat projections with freshness (§4.4), and this document cites the deployment ladder rather than declaring states.

Additionally, three PRD_GOVERNANCE invariants that constrain the design and are kept without exception: the vault is authority (model credentials, tool registries, channel bindings are all vault/snapshot state — §4.3, §3); escalation amends law (a native-session deny escalates through the same ladder; no bypass mint); provisional occupancy is loud (a gateway member in a role with no qualified occupant carries `Provisional` on every verdict).

## 11. Phasing

Ordered by dependency, each phase ending in something the fleet *uses* (the build-plan rule that survived):

- **F0 — foundations (blocking everything):** authenticated connect (three enrollment classes, §4.2); MCP schema completion (#419 class); session records + witnessed launch. *Dogfood: one hooked member re-enrolled proof-of-possession; the connect of an unknown id observed to deny.*
- **F1 — native loop, local model first:** `ModelBackend::Local` (ollama — zero external risk) driving one native session under a bounded registry; R7 constructor; deny→remedy→context loop. *Dogfood: a native session performs a real mesh task end-to-end, witnessed.*
- **F2 — SAGE gateway:** sage-rs thin client (Rust port of the fleet_event shape); being connect via key proof; intents→gate→dispatch; appeal path exercised at least once for real (temperament reachable). Sprout stays in budget (client adds ~0; the loop runs in hestia). *Dogfood: sprout-being's first witnessed act chain + first adjudicated V3 grain.*
- **F3 — control plane, seat-local:** session_launch verb (operator-walled), wake scheduler inside the daemon (retiring the shell watcher on this seat), session table with derived assurance profiles. *Dogfood: one autonomous track launched and woken by the daemon for a week; the shell watcher deleted on this seat only after parity is measured.*
- **F4 — API + subscription backends:** `Api{...}` then `Subscription{...}` per §13's risk posture (external-research findings; documented-first). *Dogfood: one native session on a metered API key; subscription mode behind an operator flag with its risk note rendered where it is enabled.*
- **F5 — channels:** one adapter (the mesh already exists; first external medium chosen by operator), binding ceremony, outward budget live in shadow first (would-deny rate measured), then enforced. **Gate: the §4.4 rate-governor calibration answered before enforcement.** *Dogfood: an external ask arrives on the channel, routes to receptionist, escalates once by role transfer, and the whole trace is queryable per caller and per role.*
- **F6 — fleet observation:** seat projections pulled hub-side; fleet session/deploy view with freshness; checkpoints only after 0018's substrate (#313 → B2 → #328). *Dogfood: the "is HUB dark?" question of 2026-08-18 answerable from one surface in one minute.*

Explicitly *not* phased here: hooked-session migration (never forced), A3/A4 isolation work, hub-side R4.

## 12. Open technical questions

Carried honestly, each with its owner:

1. **Rate-governor nonlinearity** (R6/R7 §4.4) — the named precondition for F5 enforcement. Owner: dp + hub track. Proposed instrument: shadow-mode channel traffic replayed against candidate curves.
2. **Session re-attestation cadence** — a days-long native session outlives trust recomputation; how often must connect-proof refresh? (Bridge T1/T2 per-act tiers answer the high-stakes end; the floor cadence is open.) Owner: this PRD's F0.
3. **Model-stream interruption semantics** — when the gate denies mid-loop, what happens to the in-flight model turn? (Return-as-tool-result is the design; whether providers' streaming APIs make the deny visible *before* side-effect-bearing parallel calls is per-backend and needs measurement.) Owner: F1.
4. **Registry granularity for A2-by-construction** — is per-tool enough, or do argument-level bounds (e.g. peer_ask restricted to society members) need registry-level expression? Leaning: registry names tools; law bounds arguments — the fold already does this. Owner: F1/F2.
5. **Subscription-auth durability** — see §13; the entire mode may be ToS-fragile and must be architecturally optional. Owner: F4, revisited each provider-policy change.
6. **Wake-scheduler fairness** — 0015's claim board at daemon scale: starvation, priority, and the budget interaction (a member with spent budget must not hold claims). Owner: F3.
7. **Cross-seat session identity** — can a native session migrate seats (Legion → Sprout)? Not in v1; noted because the being-key model makes it *possible* and the session-is-transport doctrine makes it *cheap to refuse* for now. Owner: post-F6.
8. **Multi-daemon co-residency** — `HESTIA_HOME` supports N identities per host (being + seat); do two daemons share a port, a chain, neither? Current answer: one daemon, N members (the being is a member of the seat's daemon); a second daemon per being is rejected until a concrete need appears. Owner: F2.

9. **Provider subscription policy verification** — §13.5's posture-1 claim (vendor CLI headless under the owner's login = supported) reflects fleet practice and author knowledge; the external-research track on current provider terms did not complete. Before F4's subscription flag ships, verify each provider's current position in writing and record it beside the flag. Owner: F4, re-verified on every provider-policy change.
10. **Slack/channel ToS + AI-disclosure-law verification** — §13.8's two go/no-go items (Slack's no-persistent-index clause; EU AI Act Art. 50 live since 2026-08-02) are carried from a peer-research pass and must be re-confirmed against current primary ToS/statute text before F5 is specified. This can *descope Slack entirely*; it is a phase-gate, not a footnote. Owner: F5 pre-spec.
11. **hestia as its own STS (RFC 8693 + attenuated tokens)** — §16 rule 1: should the vault issue minute-scale, audience-bound, monotone-narrowing derived credentials to agents (AAT/`draft-niyikiza` shape, offline-verifiable) rather than ever handing over an upstream token? Highest-leverage borrow identified; maps onto the gate + witness chain. Owner: F0 (identity) design, informs F4/F5.

12. **Transparent subscription-passthrough legality** — the `ANTHROPIC_BASE_URL` forwarding proxy (§13.5, LiteLLM-precedented, token never stored) may or may not fall under Anthropic's "may not intermediate session tokens" clause. The docs invite the question; resolve by a direct ask before building it. Owner: F4, gray path only.
13. **hestia as OIDC issuer for Anthropic WIF** — should hestia issue per-agent OIDC JWTs exchanged for short-lived service-account API tokens (§13.5), making LCT-per-agent the credential subject on the sanctioned direct-API path? This is the ToS-clean per-agent story and likely the right one for SAGE beings. Owner: F0/F4.

## 13. The external landscape — protocols, competitors, and the auth question

From a dedicated research pass (2026-08-23; confidence-tagged in the study; load-bearing items verified against primary sources). Four findings change the PRD's posture; none change its architecture.

### 13.1 MCP moved, and the move manufactures demand for exactly this

The `2026-07-28` MCP revision is the largest since launch: sessions and the handshake are **removed** (stateless turns, per-request `_meta`), required gateway-routable headers (`Mcp-Method`, `Mcp-Name`) with mandatory header↔body validation, and — the strategic core — **sampling is deprecated** (SEP-2577, removal floor 2027-07-28) with the stated migration path *"Integrate directly with LLM provider APIs."*

Sampling was the one place MCP let a server get inference without holding a provider credential. Its removal tells **every MCP server author who needs inference to acquire their own keys** — across a fleet, N copies of a key, N rotation points, N unaudited egress paths, N cost centres. That is precisely the problem a local credential-vault + policy + witness daemon exists to solve. The deprecation is the strongest external argument for the native loop: **hestia holds the credential once, drives the model, and the fleet's servers never see a key.**

Two more protocol facts with direct design force:
- **The Agents WG's charter answers the "is this territory taken?" question:** *"The charter does not predetermine where inference or agent loops run"* — MCP stewards Tasks (client-polled) and explicitly does **not** standardize agent runtimes, planning, memory, or orchestration. There is no blessed server-side agent-loop pattern, and the one that came closest is being removed. The native loop is open territory, not a fight.
- **Structural current to build with, not against:** sampling died because it needed a long-lived bidirectional channel, which the stateless turn removes. The native loop must not depend on persistent MCP connections for its own operation; hestia's member-facing MCP surface should track the stateless model (rmcp v3.x implements `2026-07-28`; Rust is functional-but-beta tier upstream — budget for tracking).

Auth stack facts the gateway inherits: MCP servers are OAuth 2.1 resource servers (RFC 9728 mandatory); **token passthrough is prohibited** (an upstream credential is always the gateway's own, never the client's forwarded token — which is hestia's vault doctrine stated as protocol law); DCR is deprecated in favour of CIMD; and the `oauth-client-credentials` extension names *"daemon processes or long-running workers"* as its use case — the inbound-auth story for headless members. The version-downgrade bypass (a client speaking an older revision to dodge header-body validation) must be explicitly rejected at hestia's boundary.

### 13.2 A2A is the between-societies protocol, and it is not ready in Rust

A2A v1.0 (Linux Foundation; since 2026-06 under the same foundation as MCP) is the emerging agent↔agent surface: AgentCards at a well-known URI, eight task states, signed cards for cryptographic identity. The official composition guidance matches this PRD's shape verbatim: *"Each individual agent internally uses MCP to interact with its specific tools and resources"* — A2A between agents, MCP within. For hestia: **channels and hub federation are where A2A eventually lands** (an AgentCard is a natural projection of a member's public role surface), but the Rust SDK situation is immature (official SDK pre-1.0, third-party space contradictory), so A2A enters as a **watch item with a named trigger** (first external A2A caller), not a build item. The LF's incubating **AI Catalog / Trust Manifest** (`/.well-known/ai-catalog.json`, "verifiable identity, compliance attestations, provenance") is the single most hestia-adjacent identity artifact in the ecosystem and is unresolved — follow up before inventing a parallel discovery format.

### 13.3 Competitors: the composite is open, single capabilities are not

The gateway field is crowded and two presumed differentiators are already occupied: **agentgateway** (Rust, LF-governed — same home as MCP/A2A — KMS-envelope credential vault with AAD-bound ciphertext, SPIFFE per-workload identity) and **LiteLLM** (deepest MCP gateway, OAuth both directions, a beta Rust core). The local-daemon niche has a direct neighbour in **Infisical agent-vault** (credential proxy for agent harnesses, ~2k stars). The PRD positions against these by name:

| | agentgateway | LiteLLM | Infisical a-v | **hestia** |
|---|---|---|---|---|
| usable vault w/o cloud KMS | no (AWS KMS) | Enterprise | yes | **yes (Argon2id+ChaCha20, local)** |
| verifiable audit | **none** | mutable Postgres | none | **hash-chained witness, signed** |
| policy = law w/ escalation | route-level | key/team perms | none | **law + ladder + appeal** |
| identity model | SPIFFE SVID | virtual keys | none | **LCT + roles + occupancy + society** |
| runs on a Jetson w/o infra | no (K8s-shaped) | needs Postgres | partially | **yes (18MB, no deps)** |

**The genuinely open gap is verifiable audit**: every surveyed gateway logs to mutable storage; the field's own hash-chain proposals (LiteLLM #25237/#30238, explicitly motivated by EU AI Act Art. 12) remain unmerged; regulatory pull is growing. The honest positioning is therefore **not** "hestia does MCP aggregation" (eleven maintained projects do) — it is: *the audit record as evidence — signed, hash-chained, independently verifiable by a party who does not trust the daemon (PRD_ASSURANCE's north star) — plus vault, law, and identity in one local-first binary with no Postgres, no Kubernetes, no cloud KMS.* That composite does not exist elsewhere. Integration and verifiability, not novelty of parts.

### 13.4 Provider-shim honesty

Anthropic's OpenAI-compat layer is self-described as not production-grade, and its failure mode is the fleet's least favourite: *"most unsupported fields are silently ignored rather than producing errors"* (caching unsupported; token-detail fields always empty, blinding cost dashboards; sampling params silently clamped or rejected). Design rule for `ModelBackend`: **native adapter per provider, never a common-denominator shim; degradations labeled, never silent; no injected defaults.**

### 13.5 Subscription-account auth — the boundary, verified

*(Evidence class: primary-source verified 2026-08-23 against code.claude.com/docs/en/legal-and-compliance, quoted verbatim below; enforcement timeline [SEC]. This section is corrected from the first draft, which had the right posture but an imprecise boundary.)*

The question: can hestia drive models under a member's *subscription* (Claude Pro/Max, ChatGPT Plus) rather than metered API keys? The answer is now precise, and it is largely negative for token-holding designs and positive for orchestration designs.

**Anthropic prohibits the token-holding design explicitly, and enforces it.** Verbatim from the Claude Code legal docs: *"Anthropic does not permit third-party developers to offer Claude.ai login into their own applications, or to route requests through Free, Pro, or Max plan credentials on behalf of their users. Moreover, developers may not collect, store, or intermediate Claude.ai credentials or session tokens — sign-in to a Claude account must complete through Anthropic's own flow."* Enforcement is live: server-side blocks of third-party clients using subscription OAuth began Jan 2026 (OpenCode, "This credential is only authorized for use with Claude Code"), legal requests followed, the policy was formalized Feb 2026. Google closed its Gemini-CLI free lane entirely (June 2026). **So `ModelBackend::Subscription` MUST NOT mean hestia holding or replaying a subscription token — that is prohibited, detected, and pursued.**

**But the same policy names the sanctioned carve-out, verbatim:** it *"does [not] prevent an end user from signing in to the unmodified Claude Code binary with their own Claude subscription, including where a platform hosts Claude Code."* The binary must not be modified and no auth method removed. So the adopted design is exact:

- **`ModelBackend::Subscription{vendor_cli}` = hestia orchestrates the vendor's UNMODIFIED harness under the owner's own login** — `claude -p --output-format stream-json` (the path every fleet launcher already uses), Codex `app-server` (JSON-RPC, OpenAI's documented embedding surface, inherits the user's ChatGPT-plan entitlement through the Codex binary). Subscription economics and ToS both preserved; hestia is a *meta-harness* supplying governance around the vendor loop, not a client holding the credential.
- **This makes a Subscription session a HYBRID**, and its assurance is honestly A1: the vendor loop sits between hestia and the model and may make its own tool calls governed only by the hooked shim. **Full A2-by-construction (§3) requires `Api` or `Local` backends, where hestia holds the loop.** The dashboard derives and shows this per session; nothing asserted.
- **One gray-but-precedented option, flagged not adopted:** a transparent forwarding proxy (`ANTHROPIC_BASE_URL` → hestia → api.anthropic.com) under the user's Claude Code login, forwarding the `Authorization` + `anthropic-beta` OAuth headers untouched, witnessing and gating the passing traffic, never storing the credential. LiteLLM ships exactly this ("Claude Code Max Subscription", `forward_client_headers_to_llm_api: true`, token never stored). It is genuinely ambiguous whether passthrough-with-accounting is "intermediating session tokens" — carried as open question §12.12, not built until resolved.
- **The sanctioned direct-API path for per-agent identity is Anthropic Workload Identity Federation:** hestia acts as an OIDC issuer whose per-agent JWTs are exchanged (RFC 7523) for short-lived `sk-ant-oat01-` tokens bound to service accounts with CEL match rules — API-billed, ToS-clean, and it **maps directly onto LCT-per-agent**. This is the recommended shape for autonomous members (SAGE beings) that should not ride a human's subscription at all.
- **Cheap sanctioned lane worth noting:** Anthropic-wire-compatible subscription providers (GLM, Kimi coding plans) explicitly *want* third-party harness traffic and speak the Messages format — a compliant low-cost backend for fleet agents where frontier capability isn't required.

Provider-shim rule unchanged and reinforced by primary source (§13.4): native adapter per provider; Anthropic's own guidance is *"never fall back to OpenAI-compatible shims"*; never inject defaults (a stock `temperature: 0.7` hard-400s current Anthropic models); OpenAI-compat is a labeled degradation only.

### 13.6 Harness functions moving into the weights — what remains structurally

*(Evidence class: author knowledge + the direction dp named; not independently re-researched this pass.)*

The trend is real: tool orchestration, planning loops, retries, and memory management keep migrating from harness code into model training. The design consequence is already in this PRD's §1, but stated as a filter: **anything the model can absorb, the harness must be prepared to lose.** What cannot move into weights, because it is *about* the weights' output rather than produced by it:

- **Credential custody** — a model must never hold the key (token-passthrough prohibition is now protocol law, §13.1).
- **Authority and law** — which acts are admitted is the relying party's, by construction (satisfied_by lesson).
- **Witness** — evidence about acts must be authored by a party the actor cannot edit (FR-4).
- **Identity/session binding** — who is acting, provable at connect.
- **Budget/economics** — ATP and outward governors are society properties.

hestia's native loop is deliberately thin on exactly the absorbable functions (context assembly and dispatch plumbing, replaceable as models thicken) and thick on the five non-absorbables. That is the futureproofing argument: **the hook surface hestia depends on today is thinning; the five functions above are what a harness is *for* once the loop itself is in the weights.**

Corroborated by the research pass (Lee 2026-05, Böckeler/Thoughtworks 2026-04, arXiv 2604.07236, and Anthropic's own Opus-5 migration guidance which literally instructs *"delete your verification scaffolding"*): the harness splits into a **dissolving half** (loop, planning, memory, retries, tool-wrapping — now absorbed into models and sold by the vendors as Tool Runner / Managed Agents) and a **permanent half** (credential custody, sandbox, policy, witness, identity). The normative anchor is `draft-klrc-aiagent-auth-03` (authors from OpenAI, Okta, AWS, Ping, Zscaler): *"The Large Language Model MUST NOT have access to an agent's credentials."* **hestia builds only the permanent half** and drives model access through it; the dissolving half is the vendor's to ship and the model's to absorb.

### 13.7 Channel linking — patterns

*(Evidence class: author knowledge; standard patterns, nothing exotic required.)*

Ingress/egress adapters per §6 use the boring, proven shapes: platform bot identities (bot token = a vault credential bound to the adapter's harness LCT), webhook ingress with signature verification where offered, OAuth account-linking ceremonies for address binding (§6.2's operator-walled `channel_bound` act), and plain SMTP/IMAP for mail. Agent-identity standards worth watching rather than adopting now: A2A signed AgentCards and the LF AI Catalog **Trust Manifest** (§13.2) — if the Trust Manifest matures, a member's public channel surface becomes a signed, discoverable artifact, and hestia should project it from the LCT rather than mint a parallel format. Named trigger to revisit: the manifest spec publishing field-level detail.

### 13.8 Channel viability is a legal/ToS question before it is a technical one

*(Evidence class: peer-research pass, 2026-08-23, confidence-tagged in source; the two go/no-go items below verified as load-bearing and carried as design constraints, not yet re-confirmed against primary ToS text by this author — §12.10.)*

Two findings gate the channels phase (F5) independently of any code:

- **Slack's API ToS (effective 2025-10-10) prohibits the obvious architecture.** Verbatim prohibitions: *"use API Data to train a large language model"*, *"create persistent copies, archives, indexes, or long-term data stores of other organizations' API Data"*, cross-org data use. Only *"limited and temporary"* handling essential to immediate operation, with prompt deletion; **no self-hosting carve-out.** So the Slack adapter is either (a) an ephemeral, single-org, no-LLM-ingestion relay with no message cache/vector index, or (b) out of scope. **A Slack-message memory or index built for a member is not a mitigation problem; it is a scoping decision, and it must be made before the adapter is specified.** This is the single highest-order design input for channels.
- **EU AI Act Art. 50 transparency is enforceable *now* (since 2026-08-02) and was deliberately excluded from the Digital Omnibus deferral.** A member agent posting into a channel on a human's behalf must disclose it is AI **perceivably in the interaction itself** — a ToS line or an "assistant" label does not satisfy it. This is a product requirement in the egress path (a per-channel disclosure the adapter enforces), interacting directly with §6 and with the Telegram-Business "reply as the owner" primitive (the most powerful and most dangerous channel act — a governance-gate candidate by itself). US analogues: CA SB 1001 (bot disclosure) and SB 243 (in force 2026-01-01, private right of action).

Platform-fit ranking, for phase-1 adapter selection (all peer-researched, tags in source):
- **Telegram / Discord — cheapest NAT fit.** Telegram: OIDC account-linking now exists, `getUpdates` long-poll needs zero inbound reachability, native `sendRichMessageDraft` streams AI replies; **one poller per bot token** is a vault invariant. Discord: **interactions are delivered over the Gateway** (a NAT'd daemon gets full slash-command support, no public HTTPS), and privileged intents are self-serve under 10k users (obsoleted the old 100-server rule, 2026-06-10). Both bind on the platform's stable subject id, never email.
- **Matrix — the only medium where hestia is the *authority*, not a guest** (appservice API = one virtual identity per agent, unrate-limited) — but only if the homeserver is local; otherwise it PUSHes to you and it's an architecture fork, not a config flag. `matrix-sdk-crypto` is a no-network state machine, a clean fit for vault-owned keys. Note **it is 0.x — pin exactly.**
- **Email — good inbound, poor self-hosted outbound** (Gmail/Outlook require SPF+DKIM+DMARC+PTR; residential MX is dead; always relay via 587/465). Gmail auth: **Workspace + Internal consent screen = no CASA assessment, no 7-day refresh expiry**; personal Gmail = IMAP + app password. **Never a per-agent Google token scheme** (100 refresh tokens per account per client_id, silent eviction of the oldest).
- **SMS — outbound-only alerting or out of scope** (US 10DLC registration mandatory with no hobbyist exemption; inbound is webhook-only, the one channel with no NAT-friendly receive).

The structural pattern worth stating: **chat platforms in 2026 reward being small and private (Slack 50/min undistributed vs 1/min; Discord self-serve intents under 10k; Google's personal-use verification exemption); telecom punishes it.** A local-first fleet is on the right side of every chat platform's incentive and the wrong side of every telecom's — which is itself an argument for the channel set the PRD picks.

## 14. Acceptance criteria

Each falsifiable, most with a named negative control (the corpus's own discipline):

**Identity**
- An unregistered principal's connect under a strong-registered id **denies naming the cause**; the deny is witnessed. *Control: the same connect with a valid key-proof succeeds.*
- No MCP tool can create, widen, or bind: enrollment, registry widening, channel binding, session launch are HTTP-operator-walled. *The existing `no_mcp_tool_can_*` test family extends to each new verb.*
- A gateway member's every act carries `principal_lct` proven at connect; grep the chain for any act attributed to an unproven principal → zero.

**Native loop**
- The native path calls the same `evaluate()` as the hooks: one definition site (criterion-1 grep), and a law change moves native verdicts in the same generation with no native-path deploy.
- A denied native act leaves state bit-identical (O), and the deny arrives in the model's next context as a structured result carrying the remedy. *Control: the same act under an amended law executes.*
- Kill the daemon mid-session: the in-flight act neither executes nor half-witnesses; on restart the session is gone (RAM), its chain intact.
- The lexical classifier is absent from the native path *by module dependency* — the native crate does not link the closure classifier. A dependency edge appearing is a red test.

**A2-by-construction**
- A bounded-registry member attempting any effector outside its registry produces a typed refusal + witness, not an execution — including via prompt-injected tool names. *Control: adding the tool to the registry (operator COMPOSE act) makes the same call succeed, and the member's rendered assurance profile visibly drops to A1 if the tool is shell-class.*
- Registry widening by any rung, delegation, or self-request fails (ladder §13.2's never-self-issued, tested).

**SAGE**
- sprout-being connects with key proof from Sprout (key never leaves the device), performs a witnessed act, files one appeal, and its derived temperament moves off initialization. Memory on sprout stays within `MemoryMax=4G`.
- The raising units carry no inert `HESTIA_*` vars: either the runner really connects, or the vars are gone. *A unit asserting governance it doesn't have is the red condition.*

**Control plane**
- `session_launched` ledger events exist for every native/woken session; zero sessions in the table without one.
- The wake scheduler fires only on claim; a poster cannot address work to a specific member (0015). *Control: a claim by an eligible session succeeds; assignment attempts have no verb to call.*
- Fleet view renders a seat unheard-from-for-N-hours as **stale/dark**, never as its last state. *Control: silence a test seat's projection; the view must change.*

**Channels**
- Outward sends stop at the budget with the §4.4.10 exhaustion message (about us, not them); the operator surface shows a budget state. *Control: raising the law's budget resumes delivery.*
- An inbound channel message can never mint authority: the receptionist projection retrieves nothing from private context (AGENT_CONTEXT_ACCESS §2.2's separation, tested at the retrieval predicate, not post-filter).
- Escalation transfers role with no transcript carryover — assert the escalated-to context contains provenance only.

**Security (§16)**
- The daemon binds loopback/unix-socket only; a bind to `0.0.0.0` is a red test, and a same-host reverse proxy cannot reach an operator verb without a challenge-signed session. *This is the OpenClaw differentiator, tested.*
- No agent ever receives an upstream provider/channel token: every credential handed to a session is a short-lived, audience-bound derived token. *Control: grep the vault-issue path for any raw upstream token reaching a session context → zero.*
- The mass-revoke path is exercised in a test (Discord grant-wide vs Slack per-token both covered) before any channel adapter ships.
- An agent posting to a channel emits the Art. 50 AI-disclosure in the interaction; an egress without it is refused. *Control: a channel.send with disclosure suppressed denies.*

**Honesty**
- Every dashboard assurance/deployment claim is derived (registry → profile; signed projection → fleet state), never asserted prose. The always-on-signal audit (#577) applies to every new indicator: each must have an observed transition or a designed dark state.

## 15. RWOA self-audit

```
surface: fleet PRD (design document)   act: none directly; commits the fleet to an architecture
S: high/reversible-as-doc, irreversible-as-built [construct: phased gates F0–F6, each with dogfood + controls]
R: n/a (document)   W: pass [construct: dp directive 2026-08-23; author of record named; review requested from CBP/HUB/kimi/GPT per NOT-SAME]
O: pass [construct: F0 identity precedes all authority-bearing phases; shadow-before-enforce retained]
A: pass [construct: this document carries its evidence basis — four named studies + the corpus citations inline]
V: present [construct: subscription mode architecturally optional + flag-gated; outward enforcement gated on rate-governor calibration; A2 claims derived, never asserted]
verdict: PASS as a proposal — ratification is dp's, and implementation only through the phase gates
```

## 16. Security threat model — hestia is in the OpenClaw/Drift family, and must say so

*(Evidence class: peer-research pass, 2026-08-23; incident facts confidence-tagged in source. This section is the honest self-placement PRD_GOVERNANCE §2.4's adversary discipline requires for a credential-holding gateway.)*

A daemon that holds provider credentials and social-channel tokens and drives agents is architecturally the same shape as two named 2026 disasters, and the PRD must answer both by name:

- **OpenClaw (Jan–Feb 2026) — the cautionary twin.** A local-first agent daemon that bound `0.0.0.0:18789` and auto-trusted localhost (so any same-host reverse proxy bypassed auth); researchers pulled Anthropic keys, Telegram/Slack tokens, and months of chat history; ~63% of ~30k+ exposed instances had *no auth at all*. **What hestia does differently, by construction:** loopback/unix-socket bind with a required auth token, never `0.0.0.0`, never "localhost is trusted" (the operator gate already enforces challenge-signed sessions; reachability is not authority — the document's spine). This must be an acceptance criterion, not a default.
- **Salesloft Drift (Aug 2025) — the exact failure chain, minus one hop.** source repo → cloud env → OAuth token store → **700+ customers' third-party accounts**; the stolen OAuth tokens **defeated MFA everywhere downstream** (an OAuth token *is* the MFA bypass); the actor grepped exfiltrated support tickets for `AKIA`/`secret`/`key`. hestia's chain is repo → vault → N members' credentials. **The one artifact the Drift attacker never touched was the audit log** — which is precisely hestia's differentiator.

Three design rules fall out, and they are the honest differentiators against agentgateway/LiteLLM/Auth0-Token-Vault (§13.3), stated as requirements:

1. **The vault never hands an upstream token to an agent.** It is its own STS: issues short-lived, audience-bound, *attenuated* derived credentials (the MCP token-passthrough prohibition as protocol law; the AAT monotone-narrowing algebra — *"authority can stay the same or narrow, but never widen"* — offline-verifiable from a root key, which maps almost exactly onto a governance gate + witness chain). This is the single highest-leverage borrow available and is added as open question §12.11.
2. **Encryption at rest is worth nothing against local code execution while the daemon is unlocked** (CircleCI 2023: the attacker *"extracted encryption keys from a running process"*; CHAINDROP 2026 actively enumerates agent config files). So: per-subject encryption keys (a single vault DEK is the Drift architecture), an explicit per-credential-class choice between unattended operation and user-present unlock, and systemd encrypted credentials (TPM2-sealed, tmpfs-only, **do not propagate down the process tree** — the property env vars lack) as the storage primitive. TPM sealing defends disk theft, not the live-process threat — stated, not hidden.
3. **Every token hestia holds is a pure bearer credential** — DPoP/mTLS sender-constraining is unavailable at Slack/Discord/Google-consumer/GitHub/Telegram. Blast radius is managed by the four things Drift lacked: short lifetime, minimal scope, per-subject keys, and a **pre-built, tested mass-revoke** (remembering the asymmetry: Discord revokes grant-wide, Slack per-token). And the Telegram bot token — scopeless, expiryless, unrevocable except by global rotation — is the one object that breaks the vault's attenuation promise: it is a distinguished credential class or it is not held (§12.7-adjacent).

Legal placement, briefly: an operator choosing platforms, agent behavior, and retention is a **data controller, not a processor** (EDPB 07/2020; the household exemption fails the moment another data subject's comms are involved). The precedent that matters: **Irish DPC €91M against Meta (2024) for storing passwords in plaintext, never externally exposed** — insecure credential storage is itself the violation; "we were never breached" is not a defense. This is the legal weight behind the vault being the product's core, not a feature.
