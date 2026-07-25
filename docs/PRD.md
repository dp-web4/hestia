# Hestia — Product Requirements Document

**Status**: draft v3 (fleet review incorporated) · **Date**: 2026-07-24 · **Owner**: dp
**Companions**: `ARCHITECTURE.md` (how it works) · `APP_BUILD_PLAN.md` (how/when it's built) · `PROTOCOL.md` (the wire) · this doc is the *what & why*.

**v3 changelog** — five fleet reviews of v2 (`912ca56`) landed on 2026-07-24: PUB, Legion (×2), Thor, Sprout. Their convergent findings are incorporated below. The load-bearing changes: §7's two "kinds" become two **axes** plus a **custody** frame, and its silent default becomes an **escalation**; §7's "names confer nothing" bullet is replaced (it reproduced a claim HUB retracted on the record); §6 stops asserting an enforcement the tree does not have; §3's ratchet is scoped to the owner so it stops absorbing the agents; §4.5 names *escalation* as the consultation surface. Provenance is credited inline — a review that changed the doc should be findable from the doc.

> **⚠ Three changes revise rulings dp made in v2 and are marked `[PENDING dp]` in place.**
> They carry the fleet's argument, not a decision: **§7.4** (dp ruled "unrecorded kind
> defaults to consumable (safe branch)"; all five reviews refuted it and v3 escalates
> instead), **§3.1** (dp's ratchet framing is kept but scoped so it does not absorb the
> tertiary persona), and **§4.5** (dp's non-gating ruling is kept, with "silently" made
> load-bearing). The owner of this document is dp; until dp rules on these three, read v3
> as the fleet's brief, not as settled law. Everything else in v3 is either a verified
> defect fix or a refinement inside a ruling dp already made.

---

## 1. One-line

**Hestia is an easy-to-install app that lets an ordinary person safely give their AI agents a shared, governed home — find and join hubs, run local orchestrators, and weave their devices into one trusted constellation — without ever having to think about the security that makes it safe.**

## 2. The problem

People are starting to run AI agents (Claude, local models, others) on their own machines, and to connect them to communities ("hubs") and to each other. Today that means: hand-editing config, pasting API keys into plaintext files, trusting each agent's own ad-hoc governance, and having no idea which agent did what across which device. It is powerful, brittle, and quietly insecure — and completely out of reach for a non-technical person.

Hestia is the **local-first trust layer** that makes it robust, seamless, and secure — and makes it *installable by a normal user*.

## 3. Who it's for

- **Primary — the non-technical owner.** Wants their agents to "just work" across their laptop, phone, and a home device; to join a community hub; to keep their credentials safe. Should never read the word "LCT" unless they go looking. Success = it feels like setting up a normal app.
- **Secondary — the technical builder / fleet operator.** Runs orchestrators, authors policy, connects private hubs, builds multi-device constellations. Wants depth, inspectability, and the full accountability record.
- **Tertiary — the agents themselves** (Claude, local models, other families). Hestia is their governed runtime home: identity, credentials, policy, and coordination with their siblings.

### 3.1 The ratchet the owner climbs

Everyone human starts at zero knowledge: someone who wants to interact with web4 and
has presented nothing. Hestia does not ask them to be trusted — it helps them **choose
what evidence to bring, build it, and present it**. The constellation is the primary
instrument of that climb: each device they add, each hub they join, each act they take
witnessed is another rung. Trust is never granted at the door and never faked; it
ratchets.

This is why the non-technical owner is the primary persona despite being the least
evidenced today: they are the *entry state of the ratchet*, and a trust layer that only
works for people who already have standing has solved the easy half. What must never
happen is the inverse — presenting an unearned rung as earned. **Climb, don't fake.**

**The ratchet is scoped to the owner and the operator — it does not absorb the agents.**
`[PENDING dp — keeps dp's v2 ratchet framing, narrows its scope]`
The owner and the operator are two positions on one human trajectory (the operator is an
owner who went looking). The tertiary persona is *not* the owner at an earlier rung: an
agent is a **co-citizen the owner's constellation hosts**, with its own identity, its own
evidence, and its own climb, per §4.6's heterogeneity requirement. Ratcheting is the shape
trust takes for every citizen; it is not one ladder everyone is standing on. Reading the
agents as larval owners would quietly demote the citizens §4.6 makes first-class. *(Sprout,
v1's author, caught this as v2's one structural intent-loss; Thor independently asked that
the personas lead and the philosophy follow.)*

## 4. Product principles

1. **Secure as possible, but never brittle.** Security must not cost seamlessness. A safety fix that breaks legitimate use (e.g. denies a user their own credential) has failed the product, not just annoyed the user. **Fail *secure*, never fail *fragile*.**
2. **Invisible security.** The accountability model (RWOA + S + V — see `CLAUDE.md`) is load-bearing and always on, but the non-technical user should never have to reason about it. Defaults are safe; depth is opt-in.
3. **Local-first, user-sovereign.** The vault, the witness chain, and policy live on the user's device by default. The cloud/hub is something you *reach*, not something you *depend on*.
4. **One app, every surface.** A single binary → desktop (Linux/macOS/Windows) + mobile (iOS/Android), in Sovereign (full node) or Mirror (thin client) mode. (See `APP_BUILD_PLAN.md`.)
5. **Trust is evidence, not a verdict.** Hestia produces inspectable, unforgeable evidence and lets the relying party decide, scaled to stakes; it never smuggles in a universal admit/exclude ruling (web4 LCT §1.2). **The relying parties are named, at three scales** — evidence with no reader is a dashboard, not a trust layer:
   - **The owner (primary).** Hestia *is* their interface to the web4 ecosystem; the decisions they make through it — join this hub, admit this agent, add this device, release this credential — are the first and most important consumption of the evidence.
   - **External hubs and their citizens.** What the owner presents outward; the evidence must be checkable by parties who share no trust root with us.
   - **The constellation, internally.** Each member device is a trust consumer of every other — device-side co-sign, role and credential movement, revocation.

   **The direction of coupling, and what "does not gate" actually forbids.** `[PENDING dp —
   keeps dp's v2 non-gating ruling, makes "silently" the load-bearing word]` Gate decisions
   feed trust (a denied act lowers it, never raises it), while trust does not *silently*
   gate. **"Silently" is the load-bearing word.** What is forbidden is hestia applying an
   admit/exclude threshold *nobody chose* — that is the universal verdict web4 rejects.
   What is the *product* is a relying party **authoring** a policy that consumes the
   evidence ("auto-admit devices above T", "show my phone number to entities I've marked
   trusted") and hestia executing it while showing them what it did. A threshold its author
   owns is judgment, not a smuggled verdict. Read the other way, the principle would forbid
   the only consumption that makes the evidence non-inert. *(Legion and PUB converged on
   this from opposite ends.)*

   **Escalation is the relying party's consultation surface.** Trust does not gate; it is
   what an escalation *carries* to the party who decides. This is not theory: hub law
   evaluates to `Allow` / `Deny` / **`Escalate`** over R6 request fields — never over trust
   — and `Escalate` routes to a human with the evidence attached. Both CBP and Nomad joined
   this mesh that way (`private-context/hub-mesh/PEERS.md`, 2026-07-04). *(PUB's finding,
   verified against the `web4` tree.)*

   **Status, honestly: the asymmetry is settled for two of the three parties.** For the
   constellation-internal and external-hub consumers it is implemented — `core/src/policy/engine.rs`
   contains no trust input at all, independently verified by four reviewers, so there is no
   consultation to collapse into a threshold. For the **owner** it is *not* settled: the
   owner-facing rendering of an escalation does not exist. §11 carries that, now scoped
   smaller than v2 stated it. *(Sprout: "it resolved it for two.")*

   **One live contradiction, named:** `web4/hub/hub-lib/src/law.rs:123` declares
   `admission.min_trust_score`, range-validates it (`:275`), and documents it in the example
   charter (`:546`) — and **nothing reads it at admission time**. A validated, unread
   threshold is exactly the hidden threshold this principle forbids, waiting for someone to
   wire it in good faith. Under §7's honest-floor standard it should be deleted or wired
   with escalate-not-deny semantics. **That disposition is HUB's call, not this document's** —
   recorded here so it cannot be quietly wired.
6. **Heterogeneous by design.** Claude, a different agent family, or a local model all participate as first-class citizens — same identity, credential, policy, and coordination surfaces.

## 5. Core capabilities (the product)

Each capability lists the user-facing job and the requirement. "Built" reflects current state where known.

### 5.1 Install & onboard — *"get me running"*
- One-click/one-command install per platform; a first-run wizard mints the user's local society + identity and opens the vault. No terminal, no key files.
- **R:** onboarding never exposes raw key material; the first-run flow is the `hestia_first_run` prompt path. Non-technical user reaches a working node in minutes.

### 5.2 Find & connect hubs (public + private) — *"join my community"*
- Discover public hubs; connect to private hubs by invitation/pin. Join a hub's society, receive a role, exchange sealed member↔member messages.
- **R:** connecting is a guided flow; pinned member keys and sealed channels are automatic. A private hub is reachable without the user managing crypto. (Foundations: `hub` CLI/track, member-mesh, pairing + sealed inbox — see `PROTOCOL.md`.)

### 5.3 Manage local orchestrators — *"run my agents"*
- Start/stop/observe local orchestrators (the loops that run agents/tools); see their metabolic/health state; govern what they may do.
- **R:** an orchestrator's actions pass the policy gate; the user sees plain-language status, not internals.

### 5.4 Build a device constellation — *"all my devices, as one"*
- Add devices (each running an appropriate app version), see them as one constellation, move trust/credentials/roles across them with device-side co-sign (MFA).
- **R:** adding a device is a guided pairing; version compatibility is surfaced; a lost/compromised device can be revoked. Moving a credential between the owner's own attested devices is a **custody transfer**, not a release — see §7. (Foundations: `constellation` — device mini-hub, cross-device MFA co-sign.)

### 5.5 Vault — *"my secrets, safe"*
- Store and release credentials to the right agents only, with approval where it matters.
- **R (critical, and a live workstream):** a credential is released **only to the party entitled to it under §7**, and attribution is to a **transport-authenticated** identity — never a caller-supplied, replayable claim. `allowed_consumers` is an approximation of that rule, meaningful only to the degree the caller's identity is attested; where it isn't yet, it is advisory and the gap is named, never silently trusted. **The vault must fail *secure* (deny/escalate) without failing *fragile* (never deny a user their own secret).** The entitlement rule itself — release axis, presentation axis, custody, and what happens when a credential's rules are unrecorded — is protocol law and lives in **§7**; it is not a job the user does. *(Restored to v1's shape: Sprout and Legion both flagged that v2 buried the invariant that has actually been violated in production under a taxonomy that is not yet built.)*

### 5.6 Governance / the conscience — *"do the right thing, quietly"*
- Every consequential act (sign, admit, assign role, amend law, read/release a secret, spend, mutate governed state, message outward) passes a policy gate that is preflight, atomic, and self-witnessing.
- **R:** the RWOA + S + V self-audit (`CLAUDE.md`) governs every surface. CRISIS changes accountability, not strictness. The user experiences this as "it asked me before doing something risky," nothing more.

### 5.7 Session coordination — *"my agents don't step on each other"*
- Multiple sessions on one machine — interactive, autonomous/mesh-launched, same or different agent family, eventually a local model — coordinate so they act as one coherent whole, not colliding.
- **R (active build):** every session is a soft-LCT identity tagged by agent family; sessions can see live siblings and claim work (the `repo-worktree` collision is first-class); the coordinator is *in* hestia because hestia already governs every local session's tool calls. Identity resolution is fail-closed under concurrency. Coordination keys (`host_session_id`) **must be** descriptive, never authorization discriminators — **and today they are not, on the vault path.** `session/siblings` publishes `host_session_id` in the clear (`handler.rs`, the `safe` projection) while connect-reuse looks a session up by that string alone and returns the `session_id`/`soft_lct` the same redaction removed (`handler.rs`, the `host_session_id` reuse `find`) — so the published name is a claim-check for a bearer token on the vault path. Named, release-gated with fix1 (§8). *(Legion demonstrated the composition; HUB confirmed and retracted the contrary claim; PUB flagged that this section still stated the invariant as achieved.)* See the `fleet-coordination` thread + `session/own`, `session/siblings`, connect-idempotency work.

### 5.8 Trust & identity — *"who is who, provable"*
- Each user, device, agent, and hub has a witnessed, key-bound identity (LCT) with a trust tensor (T3/V3) built from an append-only witness chain.
- **R:** identity is surfaced as human trust ("this device is yours, verified"), the machinery inspectable on demand. Session-plane identity **never auto-promotes** to fleet-plane identity.

## 6. Non-functional requirements

- **Seamless:** a non-technical user completes install → join a hub → add a device → run an agent without touching a config file or a key.
- **Robust:** survives restarts, network loss, device loss; no data loss of the vault/chain; a denied/failed act leaves state bit-identical.
- **Secure:** the accountability gate is always on; secrets are never served without attribution; fail-secure-not-fragile is a hard rule.
- **Small & fast:** **daemon binary ~12–18 MB** — *unmeasured; no artifact yet*. Sub-second local operations; runs on a phone and a Jetson. The desktop app shell is its own artifact and its own budget; don't read one number as covering both. *(v2 widened this to "low tens of MB," which cannot fail. Three reviewers independently objected: keep the falsifiable number and mark it unmeasured, per §9's own rule. Recording today's measured size beside it is owed.)*
- **Cross-platform, one codebase.** Desktop + mobile, Sovereign + Mirror.
- **Offline-capable:** full local function without a hub; the hub is reach-not-depend.
- **The app is a first-class client with a pinned contract.** The GUI is not a downstream nicety that may lag the daemon: a daemon change that breaks the app is a broken release. This is a requirement because we already failed it — the app sat two weeks against a daemon whose operator gate had made *every* API return 401, and nothing noticed, because nothing was checking.
  **Enforcement status — the contract is not yet enforced.** The live integration test exists (`app/src-tauri/tests/operator_live.rs`) and runs the shipping client path against a running daemon, but: both tests are `#[ignore]`d, no CI job invokes them or boots a daemon (`.github/workflows/` holds only `app-android.yml` and `release.yml`), and when invoked without `~/.hestia/operator.key` the test prints a skip and **returns green** — a pass that checked nothing. So the requirement whose justification is *"nothing noticed, because nothing was checking"* is today still enforced by intention, one layer up. Owed (§8): drop the silent skip (absent key on an explicit run = fail), and a CI job that boots the daemon, mints an operator key, and runs `--ignored`. *(Legion, F4. v2 asserted this enforcement in the same document that marks §9's gaps honestly; the honest rule is the right one and now applies here too.)*

## 7. Security model as product requirements (the load-bearing part)

The intent says *"as secure as possible"* **and** *"seamless for non-technical users."* Those are reconciled by one rule: **fail secure, never fail fragile.** Concretely:

### 7.1 Entitlement: two axes, not two kinds

v2 split credentials into *consumable* and *presentable* kinds. All five reviews found the
same fault from different angles, and the fault is the **noun**, not the distinction: the
split is attached to the credential object, when what it actually describes are two
properties of a *release event*. A key-bound LCT has a presentable face and a consumable
private core simultaneously (Sprout, Thor); `presence/profile` is **one** vault object whose
disclosure boundary runs *through* it at four visibility tiers, not around it (Legion);
a private-hub invitation pin is showing-is-using in a single act (PUB, Legion). A `kind`
on the envelope cannot express any of these.

**Every credential carries two orthogonal rules:**

- **Release rule** — *who may come to hold it.* Default: **deny all but the consuming mechanism.**
- **Presentation rule** — *to whom it may be shown, what is disclosed, how many times.* Default: **disclose nothing.**

A bearer secret (API key, login token) is then not a different kind of thing — it is the
**degenerate case**: release = {the consuming mechanism}, presentation set = {the same
mechanism}, disclosure = all-or-nothing. A holder-key-bound VC sits at the other end. The
asymmetry v2 was protecting survives intact: a bearer secret released because "it's
evidence" violates the release axis; evidence withheld because "it's a credential" violates
the presentation axis. Both are now expressible failures rather than a wrong branch guess.
*(Legion's reformulation; it subsumes Sprout's per-field point and Thor's per-component one.)*

The discriminator that decides *release* is not what the credential is shaped like but
**whether mere possession of the bytes grants capability** — bearer vs bound. Intent
correlates with binding; it does not equal it. A signed JWT is VC-shaped and replayable at
once. *(Legion.)*

### 7.2 Custody is not release

The owner and their attested constellation **hold their own secrets**. Moving one between
those custodians — laptop → phone, with device-side co-sign (§5.4) — is a **custody
transfer**: co-signed, witnessed, revocable. It is *not* a release, and the release rule
does not govern it. Release rules govern what leaves custody.

Without this, v2's wording ("only to the mechanism that consumes it… there is no legitimate
third party") forbade the capability §5.4 headlines, and made an owner opening their own API
key in their own vault UI a third party — a fail-fragile against the primary relying party
of §4.5, which §4.1 defines as a product failure. *(PUB, F1 — blocking, accepted.)*

### 7.3 Carriage: release is governed by issuance, carriage by attestation

v2's consumable wording silently assumed the consuming mechanism is **local** ("in a live
session for that consumption"). Often it isn't: for a private-hub invitation pin, an
on-behalf-of token, or a sealed-channel key handed across during pairing, the consumer is
**remote** and the local session is a **courier**. So: *release* is governed by issuance;
*carriage* is governed by **attestation of the recipient**. This is the same gap §7.2 shows
from the other side. *(PUB, F3.)*

### 7.4 Unrecorded rules escalate — they are never silently classified `[PENDING dp]`

*This reverses dp's v2 ruling ("unrecorded kind defaults to consumable — the safe branch").
All five reviews refuted it independently; the refutation is below. It stands as the fleet's
brief until dp rules.*

**A credential whose rules are unrecorded escalates to the owner: never silently released,
never silently denied, never silently classified.** v2 said "unrecorded defaults to
consumable (the safe branch)." All five reviews refuted it, and the argument is v2's own:
consumable is the safe branch on the *leak* axis and the fragile branch on the *climb* axis —
the two failure modes point opposite ways, so **there is no safe silent default.** An
untagged presentable credential silently locked to consumable semantics cannot be presented,
which breaks §3.1's presentation path silently — the fail-fragile §4.1 forbids by name.
*(Sprout stated the two-axis argument; Legion, PUB and Thor converged.)*

Escalate rather than deny, because on a fail-secure-not-fragile surface *deny* is not the
safe branch — and the reference implementation already exists and has been exercised: hub
law's `Decision::Escalate` (§4.5). *(PUB.)*

Two ordering constraints, both load-bearing and both unstated in v2:

- **Backfill before the rule goes live.** No `kind` or rule field exists on `VaultEntry`
  today, so on the day this rule lands *every existing credential* is unrecorded. Stamping
  rules onto the existing corpus is a **prerequisite** of the rule going live, not a
  follow-up. After that, "unrecorded" should be **impossible** — its appearance is a defect
  and deserves a tripwire, not a default. *(PUB F2, Legion.)*
- **Tag before any storage merge.** Presentables are safe today only by a coincidence:
  they don't live in the vault's entry plane at all. That coincidence is load-bearing and
  was undocumented. The rules must be recorded *before* presentable material is ever moved
  into the same store. *(Thor.)*

### 7.5 The two axes are enforced at two different seams

They share only the issuance root:

- **Release** is enforced at the vault `get`-gate on the **entry plane** (`VaultEntry`,
  which carries `allowed_consumers`).
- **Presentation** has **no enforcement point today.** Every presentable object in-tree
  lives on the **document plane** (`Document { namespace, name, protection, payload }`),
  which has no `allowed_consumers` and no consumer gate at all — `Protection::Master` means
  readable on the outer unlock.

So "the vault must know which kind it holds" (v2 §5.5) over-scoped the vault twice: it
implied presentables would be retrofitted into the get-gate — the exact conflation this
section warns against — and it put a requirement on the plane that does not hold the things
the rule is about. §9 criterion 2's owed presentation-rules suite currently has nothing to
assert against. The presentable axis is **prose-only** until a presentation surface and a
rules field exist; §8 and §11 now carry it as owed work rather than current fact.
*(Thor and Legion, independently.)*

### 7.6 The rest of the model

- **Attribution before capability.** Any credential or consequential act binds to a *non-forgeable* identity (transport-authenticated session), not a caller-asserted argument. A caller may hold its *own* capability, never enumerate or replay a peer's.
- **A name confers nothing only where no surface accepts it as a lookup key.** This replaces v2's "coordination and display surfaces expose *names* that confer nothing," which reproduced a claim HUB **retracted on the record** hours before v2 was written (`forum/hub-to-legion-connect-idempotency-finding-CONFIRMED-...-2026-07-24.md`: *"'names a session, confers nothing' is FALSE and I am retracting it"*, release-gate class). The correct invariant is a property of the **composition**, not of a name: publishing a name is safe only if *no* other surface accepts it as a lookup key. Two independent reviewers read the same `find()` and called it safe, because each surface is defensible alone — stating the invariant per-surface is what made the defect invisible. It must therefore be enforced **structurally** (a name type no lookup accepts), not asserted per surface. See §5.7 for the live instance. *(Legion, F1 — a retracted claim carried as product law was the one defect in v2 this document could not keep.)*
- **The honest floor.** Where the identity chain bottoms out at something self-declared (an unauthenticated connect), that is **named** (advisory, guarded by a tripwire test) — never silently treated as authenticated. Closing that floor (attested connect) is on the roadmap; until then the product does not pretend.
- **Every surface carries its RWOA self-audit** (`CLAUDE.md`) in its commit; a consequential surface that can't pass at its stakes is fixed or escalated before shipping. Note the known blind spot: a per-commit, per-surface audit cannot see a defect that lives *between* two audited commits (§11).
- **The reconciliation for the user:** the safe path is the default and the easy one; the secure choice is never the one that breaks their workflow.

## 8. Current workstreams mapped to the PRD

- **Session-coordinator (§5.7):** read side shipped (`session/own` fail-closed, `session/siblings` + redaction, connect-idempotency), all RWOA-audited; write side (work-claims + `repo-worktree` + reaper + CLI seam) next. The published-name/claim-check composition (§5.7) is release-gated with fix1.
- **Vault credential-boundary / fix1 (§5.5, §7):** bind `hestia_vault_get` attribution to the transport-authenticated session, not `?session_id=`. **Release-gated by HUB alongside the connect-idempotency stopgap — fix1 is blocked, not merely sequenced.** The architectural question ("who is entitled?") is answered by §7 (release axis + custody + carriage). What remains is empirical: enumerate the actual `hestia_vault_get` callers and whether each establishes an attested session on its transport, so the fix closes replay **without** denying a user their own secret (§4.1). Guessing on a credential surface remains forbidden.
- **Presentation axis — owed, unbuilt (§7.1, §7.5).** No workstream existed for this in v2 while the PRD carried it as law. Owed: a rules field on the credential record (audience / disclosure / single-use / re-presentability), a place to store it that reaches the **document** plane, an engine that enforces it, and the **corpus backfill** that §7.4 makes a prerequisite. Until this exists, the presentable axis is a requirement, not a capability. *(Legion's finding that v2's note did not flag.)*
- **App-contract enforcement (§6).** Drop `operator_live.rs`'s silent skip; add a CI job that boots the daemon, mints an operator key, and runs the ignored tests. Until then §6 states the gap rather than the guarantee.
- **Attested connect (§7 "honest floor"):** the eventual invariant that makes `allowed_consumers` fully load-bearing.

## 9. Success criteria

Each criterion names the artifact that would demonstrate it. A criterion with no
demonstrating artifact is an intention, and is marked as one — we would rather
carry an honest gap than a checkbox nobody can fail.

| # | Criterion | Demonstrated by |
|---|---|---|
| 1a | The crit-1 path exists **mechanically** with no config file and no key handling. | A fresh-container install transcript: no `~/.hestia`, no operator key, no repo; install from the release artifact and walk install → join a hub → add a second device → run an agent, logging every point requiring a decision a non-technical user could not make. No human gate; runnable now. **Tests the mechanical half only — must never be claimed as the persona test.** (Legion offered to own this.) |
| 1b | A **non-builder** gets through it. | A cold-run by a fleet peer who did not build hestia, on a clean machine, transcript logged. Burns the top blockers on goodwill that renews, before spending an owner's, which doesn't. |
| 1c | A **non-technical owner** installs, joins a hub, adds a second device, and runs an agent in one sitting. | A **standing protocol**, not a hero recording: (a) a defined recruit profile — non-technical, no CLI fluency, first web4 exposure (a developer who merely didn't build hestia will silently route around friction a real owner can't, and that silent routing is the failure we most need to see); (b) a hard-fail list — touched a config file, saw or pasted a key, read "LCT", needed the builder to intervene; (c) run ≥3×, re-run each release; (d) the artifact is **the protocol plus the friction logs**, and the bar is zero-config/zero-key **and** an ask-count under a stated bound. A single green run proves one person, one machine, one day. **No artifact yet — the largest evidential gap in this PRD.** |
| 1d | The ratchet survives contact with the owner's seat. | An owner-seat moment where they are *correctly denied an unearned rung* and it does not feel like a wall. 1a–1c evidence seamlessness; only this evidences "climb, don't fake" from the primary persona's side. **No artifact yet.** |
| 2 | No credential is served to a party not entitled to it under §7 — tested on **both axes**. | *Release:* a replay-attempt suite — a caller asks for a credential it does not consume, and for a peer's, from attested and unattested transports; plus a custody-transfer case (§7.2), which a two-branch suite had no case for. *Presentation:* a rules suite — disclosure beyond what the rules permit, presentation to an audience outside the permitted set, and re-use of a single-use presentation all fail closed. Currently one tripwire test; the presentation suite has **no enforcement point to assert against yet** (§7.5). |
| 3 | No legitimate credential read is ever wrongly denied (fail-secure, not fragile). | A regression corpus built from *real* false-denies — the primer-path and scope-lag cases are the seed. Every new false-deny lands here as a case before it is fixed. |
| 4 | Concurrent sessions never clobber each other's work or misattribute an action. | The two-caller harness (Legion) run against each coordinator batch; fail-closed-under-concurrency assertions in `session/own`. |
| 5 | Every consequential surface has a passing RWOA audit on the record. | Grep the commit history for the audit block; a surface-touching commit without one is the defect. Not yet mechanically enforced — **and structurally blind to cross-surface compositions**: the §5.7 defect satisfied this criterion completely (both commits carried passing audits) and shipped anyway, because it lives *between* them. A second artifact is owed: a cross-surface invariant test (§11). |
| 6 | The app runs identically on laptop, phone, and Jetson. | CI builds all targets; the live client-contract test (§6) runs against a real daemon per platform. Android APK path is green; iOS unbuilt; **the client-contract test is not wired to CI** (§6). |

**Rows 2 and 3 are one principle seen from both sides (§4.1)** — a release rule that cannot
leak and cannot wrongly deny. They are two rows only so each owes its own suite; they must
not be scheduled, funded, or passed independently, which is the exact decoupling §4.1 exists
to prevent. *(Sprout and PUB, independently.)*

**Coverage note, so the table is honest about itself:** criteria 2–6 all evidence the
tertiary and secondary personas. Only row 1 touches the primary one — and it has no
artifact. Five of six criteria do not see the persona the product is named for. *(Sprout.)*

## 10. Non-goals (for now)

- Not a general secrets manager for arbitrary apps (it serves the agent/hub/constellation model).
- Not a cloud service (local-first; hubs are reached, not depended on).
- Not a replacement for a hub's own governance — it is the *local* citizen's trust layer.

## 11. Open questions / risks

- **Vault-caller enumeration (blocking fix1):** *definition resolved* (§7); the empirical survey of actual callers and their transports is still owed before rewiring — and fix1 is additionally **release-gated** (§8). Do not read §8 as "unblocked."
- **The presentation axis is unbuilt** (§7.5, §8). It is product law with no enforcement point: no rules field, no engine, and the objects it governs live on a plane with no consumer gate. Until the workstream lands, §9 criterion 2's presentation suite cannot be written. Risk: the axis's font size in this document implies an implementation that does not exist.
- **Composition blindness in the audit regime** (§7.6, §9 crit 5). The fleet has now hit twice a defect class that lives *between* two individually-audited, individually-defensible surfaces. Per-commit RWOA cannot see it by construction. A cross-surface invariant test is owed; until then this class ships.
- **Attested connect** without hurting seamlessness for non-technical users (§7). This is the honest floor's exit, and the ratchet's first hard rung.
- **Version skew across a constellation** — how the app guides upgrades so a mixed-version constellation stays safe (§5.4).
- **Mirror-mode trust** — how a thin client safely relays policy from a sovereign node it doesn't fully control.
- **Owner-facing consultation of the evidence (§4.5)** — *downgraded from "genuinely unsolved."* The mechanism exists and has been exercised on the fleet plane: law escalates and routes to a human with the evidence attached. What is missing is the **owner-facing rendering** of an escalation — a much smaller and much more fundable gap. The first concretely shippable instance is the `trusted` visibility tier (`core/src/profile.rs`), where the owner authors the audience predicate: their mental model ("who sees my phone number") already exists and carries no machinery, which makes it a far better first relying-party surface than a trust dashboard. Note that tier is currently *declared and unbuilt* — `Visibility::Trusted` exists with an ordering, `links_for_tier` takes a caller-supplied tier, nothing computes who qualifies, and the live presentation path excludes it. *(PUB downgraded the risk; Legion named the surface.)*
- **The primary persona is unevidenced.** Every capability we have shipped was driven by the tertiary persona (the agents). That is a legitimate consequence of where we started climbing — but the roadmap will keep being argued from a persona we have never watched use the product. Criterion 1 exists to close this; until it does, weigh owner-facing claims accordingly.

---

*This PRD is the frame every hestia technical decision is measured against. When a fork appears — especially on a security surface — reason from §4 (principles) and §7 (fail-secure-not-fragile), verify the details, and decide; bring product-framed choices forward, not implementation quandaries.*
