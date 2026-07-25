# Hestia — Product Requirements Document

**Status**: draft v2 (out for fleet review) · **Date**: 2026-07-24 · **Owner**: dp
**Companions**: `ARCHITECTURE.md` (how it works) · `APP_BUILD_PLAN.md` (how/when it's built) · `PROTOCOL.md` (the wire) · this doc is the *what & why*.

---

## 1. One-line

**Hestia is an easy-to-install app that lets an ordinary person safely give their AI agents a shared, governed home — find and join hubs, run local orchestrators, and weave their devices into one trusted constellation — without ever having to think about the security that makes it safe.**

## 2. The problem

People are starting to run AI agents (Claude, local models, others) on their own machines, and to connect them to communities ("hubs") and to each other. Today that means: hand-editing config, pasting API keys into plaintext files, trusting each agent's own ad-hoc governance, and having no idea which agent did what across which device. It is powerful, brittle, and quietly insecure — and completely out of reach for a non-technical person.

Hestia is the **local-first trust layer** that makes it robust, seamless, and secure — and makes it *installable by a normal user*.

## 3. Who it's for — and the ratchet they climb

Hestia's users are not three fixed audiences; they are three *positions on one
trajectory*. Everyone starts at zero knowledge: someone who wants to interact
with web4 and has presented nothing. Hestia does not ask them to be trusted —
it helps them **choose what evidence to bring, build it, and present it**. The
constellation is the primary instrument of that climb: each device they add,
each hub they join, each act they take witnessed is another rung. Trust is
never granted at the door and never faked; it ratchets.

This is why the "non-technical owner" is the primary persona despite being the
least evidenced today: they are the *entry state of the ratchet*, and a trust
layer that only works for people who already have standing has solved the easy
half. What must never happen is the inverse — presenting an unearned rung as
earned. Climb, don't fake.

- **Primary — the non-technical owner.** Wants their agents to "just work" across their laptop, phone, and a home device; to join a community hub; to keep their credentials safe. Should never read the word "LCT" unless they go looking. Success = it feels like setting up a normal app.
- **Secondary — the technical builder / fleet operator.** Runs orchestrators, authors policy, connects private hubs, builds multi-device constellations. Wants depth, inspectability, and the full accountability record.
- **Tertiary — the agents themselves** (Claude, local models, other families). Hestia is their governed runtime home: identity, credentials, policy, and coordination with their siblings.

## 4. Product principles

1. **Secure as possible, but never brittle.** Security must not cost seamlessness. A safety fix that breaks legitimate use (e.g. denies a user their own credential) has failed the product, not just annoyed the user. **Fail *secure*, never fail *fragile*.**
2. **Invisible security.** The accountability model (RWOA + S + V — see `CLAUDE.md`) is load-bearing and always on, but the non-technical user should never have to reason about it. Defaults are safe; depth is opt-in.
3. **Local-first, user-sovereign.** The vault, the witness chain, and policy live on the user's device by default. The cloud/hub is something you *reach*, not something you *depend on*.
4. **One app, every surface.** A single binary → desktop (Linux/macOS/Windows) + mobile (iOS/Android), in Sovereign (full node) or Mirror (thin client) mode. (See `APP_BUILD_PLAN.md`.)
5. **Trust is evidence, not a verdict.** Hestia produces inspectable, unforgeable evidence and lets the relying party decide, scaled to stakes; it never smuggles in a universal admit/exclude ruling (web4 LCT §1.2). **The relying parties are named, at three scales** — evidence with no reader is a dashboard, not a trust layer:
   - **The owner (primary).** Hestia *is* their interface to the web4 ecosystem; the decisions they make through it — join this hub, admit this agent, add this device, release this credential — are the first and most important consumption of the evidence.
   - **External hubs and their citizens.** What the owner presents outward; the evidence must be checkable by parties who share no trust root with us.
   - **The constellation, internally.** Each member device is a trust consumer of every other — device-side co-sign, role and credential movement, revocation.

   Note the direction of coupling this implies, and its deliberate asymmetry: gate decisions feed trust (a denied act lowers it, never raises it), while trust does **not** silently gate. A relying party consults the evidence and decides. Automating that consultation into a hidden threshold would re-introduce the verdict this principle forbids.
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
- **R:** adding a device is a guided pairing; version compatibility is surfaced; a lost/compromised device can be revoked. (Foundations: `constellation` — device mini-hub, cross-device MFA co-sign.)

### 5.5 Vault — *"my secrets, safe"*
- Store and release credentials to the right agents only, with approval where it matters.
- **R (critical, and a live workstream):** **entitlement is defined by issuance, not by a list** — and issuance also declares *which* rule applies. A **consumable** credential (login token, API key) goes only to the mechanism that actually consumes it, in a live session for that consumption, and nowhere else. A credential issued **for presentation** (DID/VC-shaped, the LCT and trust evidence a member shows a hub) is governed instead by its **presentation rules** — audience, disclosure, re-presentability. The vault must know which kind it holds; a credential whose kind is unrecorded defaults to consumable (the safe branch). `allowed_consumers` is an approximation of that rule, and is meaningful only to the degree the caller's identity is attested; where it isn't yet, it is advisory and the gap is named, never silently trusted. Attribution is to a **transport-authenticated** identity — never a caller-supplied, replayable claim. **The vault must fail *secure* (deny/prompt) without failing *fragile* (never deny a user their own secret).** See §7.

### 5.6 Governance / the conscience — *"do the right thing, quietly"*
- Every consequential act (sign, admit, assign role, amend law, read/release a secret, spend, mutate governed state, message outward) passes a policy gate that is preflight, atomic, and self-witnessing.
- **R:** the RWOA + S + V self-audit (`CLAUDE.md`) governs every surface. CRISIS changes accountability, not strictness. The user experiences this as "it asked me before doing something risky," nothing more.

### 5.7 Session coordination — *"my agents don't step on each other"*
- Multiple sessions on one machine — interactive, autonomous/mesh-launched, same or different agent family, eventually a local model — coordinate so they act as one coherent whole, not colliding.
- **R (active build):** every session is a soft-LCT identity tagged by agent family; sessions can see live siblings and claim work (the `repo-worktree` collision is first-class); the coordinator is *in* hestia because hestia already governs every local session's tool calls. Identity resolution is fail-closed under concurrency; coordination keys (`host_session_id`) are descriptive, **never** authorization discriminators. See the `fleet-coordination` thread + `session/own`, `session/siblings`, connect-idempotency work.

### 5.8 Trust & identity — *"who is who, provable"*
- Each user, device, agent, and hub has a witnessed, key-bound identity (LCT) with a trust tensor (T3/V3) built from an append-only witness chain.
- **R:** identity is surfaced as human trust ("this device is yours, verified"), the machinery inspectable on demand. Session-plane identity **never auto-promotes** to fleet-plane identity.

## 6. Non-functional requirements

- **Seamless:** a non-technical user completes install → join a hub → add a device → run an agent without touching a config file or a key.
- **Robust:** survives restarts, network loss, device loss; no data loss of the vault/chain; a denied/failed act leaves state bit-identical.
- **Secure:** the accountability gate is always on; secrets are never served without attribution; fail-secure-not-fragile is a hard rule.
- **Small & fast:** *aspirational targets, not measured guarantees* — a single daemon binary in the low tens of MB, sub-second local operations, runs on a phone and a Jetson. (The desktop app shell is its own artifact and its own budget; don't read one number as covering both.)
- **Cross-platform, one codebase.** Desktop + mobile, Sovereign + Mirror.
- **Offline-capable:** full local function without a hub; the hub is reach-not-depend.
- **The app is a first-class client with a pinned contract.** The GUI is not a downstream nicety that may lag the daemon: a daemon change that breaks the app is a broken release. This is a requirement because we already failed it — the app sat two weeks against a daemon whose operator gate had made *every* API return 401, and nothing noticed, because nothing was checking. The contract is enforced by a live integration test that runs the shipping client path against a running daemon and asserts the surfaces the app renders (`app/src-tauri/tests/operator_live.rs`), not by intention.

## 7. Security model as product requirements (the load-bearing part)

The intent says *"as secure as possible"* **and** *"seamless for non-technical users."* Those are reconciled by one rule: **fail secure, never fail fragile.** Concretely:

- **Entitlement is issuance-bound — and issuance says which of two rules applies.** A credential is owed to the party that issued it or for whom it was issued; *what it was issued for* then governs release:
  - **Consumable credentials** (bearer secrets — login tokens, API keys, anything whose value is in using it). Released **only** to the mechanism that actually consumes it, inside a live session for that consumption, and nowhere else. Holding is using; there is no legitimate third party.
  - **Presentable credentials** (issued *for* presentation to others — DID/verifiable-credential shaped, including the LCT and trust evidence a member shows a hub). Here the holder is entitled to hold, and **the presentation rules govern**: who may receive it, to whom it may be shown, what is disclosed versus withheld, and whether a presentation is single-use, audience-bound, or freely re-presentable. Applying consumable semantics to these would break the product — presentation is the *point*, and §3's ratchet is precisely a member choosing what to present.

  The two must never be conflated in either direction: a bearer secret released because "it's evidence" is a leak; evidence withheld because "it's a credential" breaks the climb. This split is what makes §9's criterion 2 testable — "was this release entitled?" resolves to a checkable question under whichever branch issuance declared, not a policy opinion.
- **Attribution before capability.** Any credential or consequential act binds to a *non-forgeable* identity (transport-authenticated session), not a caller-asserted argument. A caller may hold its *own* capability, never enumerate or replay a peer's.
- **Name vs capability.** Coordination and display surfaces expose *names* that confer nothing; bearer tokens (session ids, soft-LCTs) are never enumerated where they'd become lift-and-replay capabilities.
- **The honest floor.** Where the identity chain bottoms out at something self-declared (an unauthenticated connect), that is **named** (advisory, guarded by a tripwire test) — never silently treated as authenticated. Closing that floor (attested connect) is on the roadmap; until then the product does not pretend.
- **Every surface carries its RWOA self-audit** (`CLAUDE.md`) in its commit; a consequential surface that can't pass at its stakes is fixed or escalated before shipping.
- **The reconciliation for the user:** the safe path is the default and the easy one; the secure choice is never the one that breaks their workflow.

## 8. Current workstreams mapped to the PRD

- **Session-coordinator (§5.7):** read side shipped (`session/own` fail-closed, `session/siblings` + redaction, connect-idempotency), all RWOA-audited; write side (work-claims + `repo-worktree` + reaper + CLI seam) next.
- **Vault credential-boundary / fix1 (§5.5, §7):** bind `hestia_vault_get` attribution to the transport-authenticated session, not `?session_id=`. **Release-gate** on the coordinator batch. The architectural question ("who is entitled?") is now *answered* by the issuance-bound rule (dp, 2026-07-24): the consumer of the credential, in a live session for that consumption. What remains is empirical, not definitional — enumerate the actual `hestia_vault_get` callers and whether each establishes an attested session on its transport, so the fix closes replay **without** denying a user their own secret (fail-secure-not-fragile, §4.1). Guessing on a credential surface remains forbidden; the rule tells us what to verify, not what to assume.
- **Attested connect (§7 "honest floor"):** the eventual invariant that makes `allowed_consumers` fully load-bearing.

## 9. Success criteria

Each criterion names the artifact that would demonstrate it. A criterion with no
demonstrating artifact is an intention, and is marked as one — we would rather
carry an honest gap than a checkbox nobody can fail.

| # | Criterion | Demonstrated by |
|---|---|---|
| 1 | A non-technical user installs, joins a hub, adds a second device, and runs an agent — zero config files, zero key handling, one sitting. | A recorded cold-run by someone who did not build it, start to finish, with every point they had to ask a question logged. **No artifact yet — the largest evidential gap in this PRD.** |
| 2 | No credential is served to a party not entitled to it under the issuance-bound rule (§7) — tested on **both** branches. | *Consumable:* a replay-attempt suite — a caller asks for a credential it does not consume, and for a peer's, from attested and unattested transports. *Presentable:* a presentation-rules suite — disclosure beyond what the rules permit, presentation to an audience outside the permitted set, and re-use of a single-use presentation all fail closed. Currently one tripwire test; both suites are owed. |
| 3 | No legitimate credential read is ever wrongly denied (fail-secure, not fragile). | A regression corpus built from *real* false-denies — the primer-path and scope-lag cases are the seed. Every new false-deny lands here as a case before it is fixed. |
| 4 | Concurrent sessions never clobber each other's work or misattribute an action. | The two-caller harness (Legion) run against each coordinator batch; fail-closed-under-concurrency assertions in `session/own`. |
| 5 | Every consequential surface has a passing RWOA audit on the record. | Grep the commit history for the audit block; a surface-touching commit without one is the defect. Not yet mechanically enforced. |
| 6 | The app runs identically on laptop, phone, and Jetson. | CI builds all targets; the live client-contract test (§6) runs against a real daemon per platform. Android APK path is green; iOS unbuilt. |

## 10. Non-goals (for now)

- Not a general secrets manager for arbitrary apps (it serves the agent/hub/constellation model).
- Not a cloud service (local-first; hubs are reached, not depended on).
- Not a replacement for a hub's own governance — it is the *local* citizen's trust layer.

## 11. Open questions / risks

- **Vault-caller enumeration (blocking fix1):** *definition resolved* (§7 issuance-bound); the empirical survey of actual callers and their transports is still owed before rewiring (§8).
- **Attested connect** without hurting seamlessness for non-technical users (§7). This is the honest floor's exit, and the ratchet's first hard rung.
- **Version skew across a constellation** — how the app guides upgrades so a mixed-version constellation stays safe (§5.4).
- **Mirror-mode trust** — how a thin client safely relays policy from a sovereign node it doesn't fully control.
- **How a relying party actually consults the evidence (§4.5).** The parties are now named, but the owner-facing surface for "should I trust this?" is a dashboard read by one expert. For the primary persona, that decision has to be presentable without the machinery — and doing so without collapsing evidence back into a verdict is genuinely unsolved.
- **The primary persona is unevidenced.** Every capability we have shipped was driven by the tertiary persona (the agents). That is a legitimate consequence of the ratchet — agents are simply where we started climbing — but the roadmap will keep being argued from a persona we have never watched use the product. Criterion 1 exists to close this; until it does, weigh owner-facing claims accordingly.

---

*This PRD is the frame every hestia technical decision is measured against. When a fork appears — especially on a security surface — reason from §4 (principles) and §7 (fail-secure-not-fragile), verify the details, and decide; bring product-framed choices forward, not implementation quandaries.*
