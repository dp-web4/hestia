# Hestia — Product Requirements Document

**Status**: draft v5 (current-source reconciliation at `9a6a5c2`; requirements remain normative, implementation status is evidence-ranked below) · **Date**: 2026-08-08 · **Owner**: dp
**Companions**: `STATUS_AUDIT_2026-08-08.md` (current evidence) · `PRD_GOVERNANCE.md` (the governance design) · `ARCHITECTURE.md` (how it works) · `APP_BUILD_PLAN.md` (app implementation and release state) · `PROTOCOL.md` (the wire) · this doc is the *what & why*.

---

## 0. How to read implementation status

This PRD contains historical findings because the corrections are part of the product's evidence.
They must not be mistaken for current source status. Status claims use this ladder:

`source → merged → installed → restarted → live → observed → publicly released`

One rung never proves the next. The 2026-08-08 snapshot is:

- **Current source and reference daemon:** `origin/main` and the running reference daemon both
  identify `9a6a5c2`; the supervisor manifest names the same full build id.
- **Harness parity:** not fully re-proven by that daemon match. The shared gate core remains unwired.
- **Public daemon:** still `v0.0.3`, 324 `core/` commits behind this source baseline.
- **Public app:** still `app-v0.1.2`, Android APK only. No desktop app artifact is public.
- **User evidence:** no clean-machine nontechnical cold run, owner-seat correct-deny transcript, or
  second-device constellation run yet.

The reproducible matrix and issue dispositions live in `STATUS_AUDIT_2026-08-08.md`.

## 1. One-line

**Hestia is an easy-to-install app that lets an ordinary person safely give their AI agents a shared, governed home — find and join hubs, run local orchestrators, and weave their devices into one trusted constellation — without ever having to think about the security that makes it safe.**

## 2. The problem

People are starting to run AI agents (Claude, local models, others) on their own machines, and to connect them to communities ("hubs") and to each other. Today that means: hand-editing config, pasting API keys into plaintext files, trusting each agent's own ad-hoc governance, and having no idea which agent did what across which device. It is powerful, brittle, and quietly insecure — and completely out of reach for a non-technical person.

Hestia is the **local-first trust layer** that makes it robust, seamless, and secure — and makes it *installable by a normal user*.

## 3. Who it's for

Three citizen types, not three rungs of one ladder:

- **Primary — the non-technical owner.** Wants their agents to "just work" across their laptop, phone, and a home device; to join a community hub; to keep their credentials safe. Should never read the word "LCT" unless they go looking. Success = it feels like setting up a normal app.
- **Secondary — the technical builder / fleet operator.** Runs orchestrators, authors policy, connects private hubs, builds multi-device constellations. Wants depth, inspectability, and the full accountability record.
- **Tertiary — the agents themselves** (Claude, local models, other families). Hestia is their governed runtime home: identity, credentials, policy, and coordination with their siblings. They are **co-citizens the owner's constellation hosts — not owners at an earlier rung** (§4.6 heterogeneity is the load-bearing principle here, and v2 blurred it).

### The ratchet — why the least-evidenced persona is correctly primary

The *owner and operator* occupy two positions on one trajectory. Everyone starts at zero
knowledge: someone who wants to interact with web4 and has presented nothing. Hestia does
not ask them to be trusted — it helps them **choose what evidence to bring, build it, and
present it**. The constellation is the primary instrument of that climb: each device they
add, each hub they join, each act they take witnessed is another rung. Trust is never
granted at the door and never faked; it ratchets.

This is why the non-technical owner is the primary persona despite being the least
evidenced today: they are the *entry state of the ratchet*, and a trust layer that only
works for people who already have standing has solved the easy half. What must never
happen is the inverse — presenting an unearned rung as earned. **Climb, don't fake.**

## 4. Product principles

1. **Secure as possible, but never brittle.** Security must not cost seamlessness. A safety fix that breaks legitimate use (e.g. denies a user their own credential) has failed the product, not just annoyed the user. **Fail *secure*, never fail *fragile*.**
2. **Invisible security.** The accountability model (RWOA + S + V — see `CLAUDE.md`) is load-bearing and always on, but the non-technical user should never have to reason about it. Defaults must be safe; depth is opt-in. *Stated as a requirement, not a blanket description: current source contains the worst new-entry vault exposure, while legacy exposure, asserted transport identity, and the absent two-axis entitlement model remain — see §5.5 and §8.*
3. **Local-first, user-sovereign.** The vault, the witness chain, and policy live on the user's device by default. The cloud/hub is something you *reach*, not something you *depend on*.
4. **One app, every surface.** A single binary → desktop (Linux/macOS/Windows) + mobile (iOS/Android), in Sovereign (full node) or Mirror (thin client) mode. (See `APP_BUILD_PLAN.md`.)
5. **Trust is evidence, not a verdict.** Hestia produces inspectable, unforgeable evidence and lets the relying party decide, scaled to stakes; it never smuggles in a universal admit/exclude ruling (web4 LCT §1.2). **The relying parties are named, at three scales** — evidence with no reader is a dashboard, not a trust layer:
   - **The owner (primary).** Hestia *is* their interface to the web4 ecosystem; the decisions they make through it — join this hub, admit this agent, add this device, release this credential — are the first and most important consumption of the evidence.
   - **External hubs and their citizens.** What the owner presents outward; the evidence must be checkable by parties who share no trust root with us.
   - **The constellation, internally.** Each member device is a trust consumer of every other — device-side co-sign, role and credential movement, revocation.

   **The asymmetry, stated precisely.** Gate decisions feed trust (a gate risk signal — *warn or deny* — lowers it, never raises it), while trust does not **silently** gate. *Silently* is the load-bearing word, and it marks an axis of **authorship**, not of automation:
   - Hestia never applies a threshold **hestia** chose. That is the verdict web4 forbids.
   - Hestia will execute a threshold the **relying party** authored, and show them what it did. That is the relying party exercising judgment — the entire point.
   - **Trust never decides; it may modulate how much the relying party is asked.** Lower trust meaning *more prompts and more surfaced evidence* is escalation to a named party, not a hidden gate.
   - **Escalation is the consultation surface.** Trust is not what gates; it is what the escalation *carries* to the party who decides. This is not theory — hub law's `Decision::Escalate` has admitted every non-trivial join on this fleet (PUB, verified in the `web4` tree).
   - The asymmetry constrains **automation, not readership**. Evidence that no relying party actually reads is the failure mode §11 names, not this principle being satisfied.

   **Status, honestly:** settled for the machine consumers (hubs, constellation — authorization there is by attested identity + capability, and `core/src/policy/` has zero trust inputs). **Unsettled for the human one:** the owner is a *named* consumer, not yet a *served* one. See §11.
6. **Heterogeneous by design.** Claude, a different agent family, or a local model all participate as first-class citizens — same identity, credential, policy, and coordination surfaces.

## 5. Core capabilities (the product)

Each capability lists the user-facing job and the requirement. "Built" reflects current state where known.

### 5.1 Install & onboard — *"get me running"*
- One-click/one-command install per platform; a first-run wizard mints the user's local society + identity and opens the vault. No terminal, no key files.
- **R:** onboarding never exposes raw key material; a non-technical user reaches a working node — society + identity minted, vault open — in minutes. **This is the user-facing requirement, not a description of `hestia_first_run`**; that MCP prompt path is one agent-facing implementation of it and v3's wording let the two read as the same thing (Legion).
- **Status: the shipped artifact does not meet it.** In a cold run of `v0.0.3`, `hestia init` creates *an empty vault and nothing else* — `info` reports home, vault file, exists, size; no identity, no society, no LCT, no keypair (Legion, 2026-07-24, transcript on the `hestia-prd-review` thread). Two smaller findings from the same run: non-interactive `init` exits 1 on the passphrase read, so the crit-1 path cannot be scripted without a pty or a `--passphrase-stdin` seam that does not exist; and a *failed* `init` leaves an empty `~/.hestia/` behind, a live counterexample to §6's "a denied/failed act leaves state bit-identical."

### 5.2 Find & connect hubs (public + private) — *"join my community"*
- Discover public hubs; connect to private hubs by invitation/pin. Join a hub's society, receive a role, exchange sealed member↔member messages.
- **R:** connecting is a guided flow; pinned member keys and sealed channels are automatic. A private hub is reachable without the user managing crypto. (Foundations: `hub` CLI/track, member-mesh, pairing + sealed inbox — see `PROTOCOL.md`.)

### 5.3 Manage local orchestrators — *"run my agents"*
- Start/stop/observe local orchestrators (the loops that run agents/tools); see their metabolic/health state; govern what they may do.
- **R:** an orchestrator's actions pass the policy gate; the user sees plain-language status, not internals.

### 5.4 Build a device constellation — *"all my devices, as one"*
- Add devices (each running an appropriate app version), see them as one constellation, move trust/credentials/roles across them with device-side co-sign (MFA).
- **R:** adding a device is a guided pairing; version compatibility is surfaced; a lost/compromised device can be revoked. Moving a credential between the owner's own devices is a **custody transfer**, not a release (§7). (Foundations: `constellation` — device mini-hub, cross-device MFA co-sign.)

### 5.5 Vault — *"my secrets, safe"*
- Store and release credentials to the right agents only, with approval where it matters.
- **R (the invariant, in one sentence):** **a credential is released only to a caller entitled to it, attributed to a transport-authenticated identity — never to a caller-supplied, replayable claim.** Entitlement is defined by issuance, not by a list. The full rule (release axis, presentation axis, custody) is §7; §5.5 is the capability, §7 is the law.
- **R (fail direction):** the vault must fail *secure* (deny/escalate) without failing *fragile* (never deny a user their own secret). §9 rows 2 and 3 are the two directions of this one rule (§4.1) and are passed or failed together.
- **Current source state — contained, not complete.** The 2026-07-24 finding was correct at its
  baseline and drove three concrete repairs:
  - vault reads and writes now require the caller's explicit, live session; the
    most-recently-connected fallback is gone from this authority-bearing path;
  - a new entry whose attributed creator supplies no consumer list is bound to that creator, so
    the ordinary UI default no longer creates a world-readable credential;
  - every release is witnessed, and legacy empty-consumer entries are marked `exposed`, warned,
    and visible on the operator surface.
  Compatibility deliberately leaves existing exposed entries readable to an attributed caller.
  The full invariant therefore remains open: connect identity is still caller-asserted rather than
  transport-authenticated; legacy entries need an explicit migration; empty scope semantics remain
  broader than the final model; and `VaultEntry` still has no issuance-bound release-rule and
  presentation-rule fields. This is a successful containment of HST-001, not completion of §7.

### 5.6 Governance / the conscience — *"do the right thing, quietly"*
- Every consequential act (sign, admit, assign role, amend law, read/release a secret, spend, mutate governed state, message outward) passes a policy gate that is preflight, atomic, and self-witnessing.
- **R:** the RWOA + S + V self-audit (`CLAUDE.md`) governs every surface. CRISIS changes accountability, not strictness. The user experiences this as "it asked me before doing something risky," nothing more.
- **R:** widening a credential's presentation rule — including deriving a presentation from a stored secret for the first time — is a **privilege-widening act**, gate-governed and witnessed. It is the obvious way to launder a bearer secret into something presentable.
- **Current source state — the issuance stopgap is closed.** `POST /credential` is now mounted
  behind the challenge-signed operator gate and appends a `credential_issued` chain event. Public
  metadata and nonce issuance remain unauthenticated by design because neither grants authority.
  This closes the arbitrary-local-caller minting hole found on 2026-07-24. It does **not** settle
  the full wallet flow: which delegation authorizes issuance, how consent is represented, and how
  presentation rules bind the result remain product work under §7.1.

### 5.7 Session coordination — *"my agents don't step on each other"*
- Multiple sessions on one machine — interactive, autonomous/mesh-launched, same or different agent family, eventually a local model — coordinate so they act as one coherent whole, not colliding.
- **R (active build):** every session is a soft-LCT identity tagged by agent family; sessions can see live siblings and claim work (the `repo-worktree` collision is first-class); the coordinator is *in* hestia because hestia already governs every local session's tool calls. Identity resolution is fail-closed under concurrency.
- **R (must be; is not yet):** coordination keys (`host_session_id`) are descriptive, **never** authorization discriminators. On the vault path this does not hold today — the `session_id` that `session/siblings` enumerates is still accepted as a lookup key by `tool_vault_get`. Named, not assumed; it is fix1's target. See the `fleet-coordination` thread + `session/own`, `session/siblings`, connect-idempotency work.

### 5.8 Trust & identity — *"who is who, provable"*
- Each user, device, agent, and hub has a witnessed, key-bound identity (LCT) with a trust tensor (T3/V3) built from an append-only witness chain.
- **R:** identity is surfaced as human trust ("this device is yours, verified"), the machinery inspectable on demand. Session-plane identity **never auto-promotes** to fleet-plane identity.
- **R (persistence, 2026-08-11):** derived trust is **persisted in the vault as a situational cache** and read from there for display — the deliberate law-following recompute writes the cache; between recomputes the cache is the source of truth; the display path re-derives nothing per poll. Specified in **[`PRD_TRUST_CACHE.md`](PRD_TRUST_CACHE.md)**. (The chain stays the sacred, expensive source; the cache is the cheap situational read the dashboard already declares itself to be.)

## 6. Non-functional requirements

- **Seamless:** a non-technical user completes install → join a hub → add a device → run an agent without touching a config file or a key.
- **Robust:** survives restarts, network loss, device loss; no data loss of the vault/chain; a denied/failed act leaves state bit-identical. *Live counterexample: a failed `hestia init` leaves an empty `~/.hestia/` (§5.1). Consequence is nil today — re-running succeeds — but the requirement is falsified, and it is recorded rather than quietly re-worded.*
- **Secure:** the accountability gate is always on; secrets are never served without attribution; fail-secure-not-fragile is a hard rule.
- **Small & fast:** **~12–18 MB daemon binary**, sub-second local operations, runs on a phone and a Jetson. **Measured, and currently missed: 22.97 MB unstripped at `e014552`, against 18.24 MB at the `v0.0.3` release** — so the target was *met at release* and has grown ~+2 MB/month since. **One line recovers it:** there is no `[profile.release]` in `core/Cargo.toml` and no strip step in `release.yml`; `strip = true` yields 18.44 MB, back at the edge. (Legion, 2026-07-24; strip-absence re-verified at `c03837b`.) This is what the falsifiable number bought that v2's "low tens of MB" could not have expressed — met, then missed, then trivially recoverable. Record the measured size per release build. (The desktop app shell is its own artifact and its own budget; don't read one number as covering both.)
- **Cross-platform, one codebase.** Desktop + mobile, Sovereign + Mirror.
- **Offline-capable:** full local function without a hub; the hub is reach-not-depend.
- **The app is a first-class client with a pinned contract.** The GUI is not a downstream nicety that may lag the daemon: a daemon change that breaks the app is a broken release. This is a requirement because we already failed it — the app sat two weeks against a daemon whose operator gate had made *every* API return 401, and nothing noticed, because nothing was checking. The contract is to be enforced by a live integration test that runs the shipping client path against a running daemon and asserts the surfaces the app renders. **Today it is not enforced, and the honest statement is worse than "not yet wired":** `app/src-tauri/tests/operator_live.rs` exists and tests the right path, but both tests are `#[ignore]`d and no workflow in `.github/` invokes them. Until 2026-07-25 it was worse than unwired: with no `~/.hestia/operator.key` the test printed `skip:` and returned **green** — a passing run that checked nothing, which is the requirement's own justification (*"nothing noticed, because nothing was checking"*) recurring one layer up. That silent skip is now removed, and the bad-key test no longer counts an unreachable daemon as a refusal. **Still owed: a CI job that boots a daemon, mints an operator key, and runs `--ignored`.** Until it exists, the contract is enforced by whoever remembers the flag.

## 7. Security model as product requirements (the load-bearing part)

The intent says *"as secure as possible"* **and** *"seamless for non-technical users."* Those are reconciled by one rule: **fail secure, never fail fragile.** Concretely:

### 7.1 Entitlement is issuance-bound — on two axes, not in two kinds

Six independent reviews of v2 converged on one defect and named it six different ways:
`kind` is not a property of a credential. v2 said a credential *is* consumable or
presentable; the counterexamples are ordinary, not exotic — an mTLS/DID keypair
(private half consumable, derived presentation presentable), a private-hub invitation
pin (showing it *is* using it), an SSH deploy key (every use authenticates to a third
party), the `presence/profile` object whose disclosure boundary runs *through* it at
four visibility tiers. The distinction is right; the noun was wrong.

**The first rule is who may cause one to exist.** Both axes below govern an object that
already exists — holding it and showing it. Neither governs **minting**, and minting is the
failure mode live in shipped code (§5.6): an unauthenticated endpoint that signs a claim
about the owner with the owner's key. v3's rule, applied as written, would have reviewed
that endpoint clean, because every rule it lists is post-issuance (Nomad). So, before the
two axes: **issuance is a consequential act like any other — owner-authorized, policy-gated,
witnessed, and refused when the authority for *this* act is absent.** §5.6's derivation rule
covers deriving a presentation from a stored secret; it does not cover issuing one to a
caller, and the two are not the same act. Nothing else in §7.1 changes: this is the rule the
axes hang from, not a third axis.

Every credential therefore carries **two orthogonal rules, both set at issuance**:

- **Release rule — who may come to hold it.** Default: **only the mechanism that
  actually consumes it, inside a live session for that consumption.** A bearer secret
  is not a different kind of thing; it is the degenerate case where the release set is
  a single consuming mechanism.
- **Presentation rule — to whom it may be shown, what is disclosed, how many times.**
  Default: **disclose nothing.** The rule's audience is the discriminating field:
  a credential whose verifier is *fixed at issuance* (this key, github.com) needs no
  further rules; one whose verifier is *chosen at presentation time* (a DID shown to
  any hub) needs them, and cannot be presented without them.

Both defaults are safe and **neither requires a guess** — which is what v2's "unrecorded
kind defaults to consumable" was patching around. Consumable is the safe branch for the
*leak* direction and the fragile branch for the *climb* direction; those failure modes
point opposite ways, so there was no safe silent default to pick (Sprout). Under two
axes there is nothing to pick: **an object with no presentation rule is not
silently classified — presenting it escalates to the owner.** Never silently released,
never silently denied.

The two axes must never be collapsed in either direction: a bearer secret released
because "it's evidence" violates the release rule; evidence withheld because "it's a
secret" violates the presentation rule. Both are now *expressible* failures, which is
what makes §9 criterion 2 testable.

**What "collapsed" means, and what it does not.** Both failures named above are
*classification* confusions — using an object's standing on one axis to decide the
other. Neither says the release rule may not depend on properties of the *recipient*;
`:146`'s "who may come to hold it" is already a statement about principals. The
distinction matters at exactly one intersection, found by probing the shape for a
residue (Sprout): **carriage × an object whose disclosure boundary runs through it** —
`presence/profile` and its four tiers (`:130`), which is the motivating counterexample,
not an exotic one. Carriage attests the recipient rather than assuming it (§7.2), so the
full four-tier object cannot be handed to a courier on the expectation that it
self-filters; what is released must be narrowed to the entitled subset as a function of
the recipient's attestation. Under the *narrow* reading of this invariant that is not a
collapse; under the *strong* reading — release may never be a function of
presentation-context — it is. The wording above picks neither, and a reviewer applying
the strong reading would read audience-narrowed carriage as a defect.

**This resolves here, not in schema v2.** Sprout offers a fork: (a) admit the
dependence — one schema row per object, the release column holding a predicate; or
(b) hold orthogonality absolute and mint N objects, one per tier, each with a static
release set — one row per (object, tier). Two corrections, and together they make the
amendment independent of the schema call:

- **A predicate is not enough for the case that motivates it.** `P(recipient) → bool`
  answers *whether* a recipient may hold the object; carriage needs *which subset*. The
  release rule must be a **projection**, `R(recipient) → released view`, of which the
  all-or-nothing boolean — and a bearer's single-consumer set (`:148`) — are the
  degenerate cases.
- **(b) does not preserve orthogonality; it distributes the same dependence.** Each
  per-tier object's release rule must still test the recipient's attested audience to
  decide tier membership. `R(recipient) → subset` over a fixed finite tier lattice and
  `{P_tier(recipient) → bool}` are the same function, curried. The fork is therefore
  **representational, not semantic**: a real schema-row-granularity call, and dp's/HUB's
  to make, but it does not decide this invariant either way.

So, stated once: **the release rule is a projection fixed at issuance and evaluated at
release**, and the invariant above forbids *classification* confusion between the two
axes — not dependence of release on the recipient's attestation. Written here rather
than deferred, because it holds under either horn. **Still owed and not ours:** the row
granularity for schema v2 (§8), and — if (b) — the N-way issuance, revocation and
custody cost stated as a consequence in §7.2.

### 7.2 Custody is not release

The owner and their attested constellation **hold their own secrets**. Movement inside
that custody — the owner opening their own API key in their own vault UI, a credential
moving to their second device under co-sign (§5.4) — is a **custody transfer**:
co-signed, witnessed, revocable. It is *not* a release, and the release rule does not
govern it.

Without this branch the rule is fail-fragile in two places the document itself
promises: §5.4's cross-device credential movement, and §4.5's owner-as-primary-relying-
party reading their own vault. v2's "there is no legitimate third party" forbade both.
Custody is also not an edge case — the most common credential hestia holds is the
custodial member-LCT binding keypair, sealed in the vault, self-issued, existing
solely to produce presentations the member never sees (`member_registry.rs:7,126,147`).

**Release is governed by issuance rules; carriage is governed by attestation of the
recipient.** The consuming mechanism is not always local — for an invitation pin or an
OAuth on-behalf-of token, the local session is a courier and the consumer is remote.

### 7.3 The rest of the security law

- **Attribution before capability.** Any credential or consequential act binds to a *non-forgeable* identity (transport-authenticated session), not a caller-asserted argument. A caller may hold its *own* capability, never enumerate or replay a peer's.
- **Names confer nothing only in composition.** A published name confers nothing **only where no surface accepts it as a lookup key** — that is a whole-API property, enforced structurally (a name type no lookup accepts), never asserted per surface. *v2 stated the per-surface form, which HUB had formally retracted hours earlier* (`host_session_id` is published in the clear by `siblings` and accepted as a connect-reuse key — the name *is* the claim-check). The retraction is the point: two independent reviewers read that composition and called it safe, because each surface is defensible alone.
- **The honest floor must be named wherever it occurs.** The live remaining floor is the
  unauthenticated *connect*; closing it with key-bound identity is on the governance roadmap. The
  2026-07-24 audit found a second floor at unauthenticated `/credential` issuance. Current source
  now operator-gates and witnesses that endpoint, closing the arbitrary-caller stopgap. The final
  wallet/delegation authorization remains unsettled, so the repair must not be over-read as a
  complete issuance model.
- **No security-relevant meaning may attach to a value the type cannot distinguish from absence.** This is the structural rule under both shipped defects and one near-miss, stated so it can be checked mechanically rather than intended (kimi, narrowing v3's "compositional"): `Vec::is_empty()` carried "unset" vs "explicitly nobody" and the handler read unset as allow-all (§5.5); a `String` carried "display label" vs "lookup key" and publisher and consumer honored different ones (§5.7); `operator_live.rs`'s `Option<Path>` carried "no key" and the skip path returned green (§6). The fixes follow from the rule, not from taste: `Option<NonEmpty<Vec>>`, a name type no lookup accepts, skip-as-`Err`. The audit question for any boundary-crossing type is exact — *what does empty/absent/default mean on the producing side, and is the receiving side forced by the type to mean the same thing?*
- **A guard applied to a collection does not cover what is added beside the collection.** The second enumerable mechanism (kimi, from Nomad's finding): `/credential` inherits `/nonce`'s deliberate unauthenticated exemption purely by adjacency in the router (§5.6). Every surface mounted outside an existing gate is greppable (`.route(` outside the gated router), and every such surface is either deliberately exempt *and said so*, or a defect.
- **Declared-but-unread thresholds are the honest floor's mirror image, and are forbidden.** A validated, documented, never-consulted trust threshold is a hidden gate waiting for someone to wire it in good faith. Live instance: `hub-lib/src/law.rs:123` (`min_trust_score`, 11 references, all inside `law.rs`, nothing reads it at admission). Wire it with escalate-not-deny semantics, or delete it. *(Disposition is HUB's call — see §12.)*
- **Every surface carries its RWOA self-audit** (`CLAUDE.md`) in its commit; a consequential surface that can't pass at its stakes is fixed or escalated before shipping. **A per-commit audit regime is structurally blind to defects that live between two audited commits** — see §11.
- **The reconciliation for the user:** the safe path is the default and the easy one; the secure choice is never the one that breaks their workflow.

## 8. Current workstreams mapped to the PRD

- **Session-coordinator (§5.7):** read side shipped (`session/own` fail-closed, `session/siblings` + redaction, connect-idempotency), all RWOA-audited; write side (work-claims + `repo-worktree` + reaper + CLI seam) next.
- **Vault default containment (§5.5) — landed in source; migration remains.** New attributed writes
  with no consumer list bind to their creator; anonymous writes and reads are refused; reads are
  witnessed. Legacy empty-consumer entries remain exposed for compatibility and are flagged to the
  operator. Migrate or explicitly grandfather that corpus before removing the compatibility path.
- **Vault credential-boundary / fix1 (§5.5, §7):** bind `hestia_vault_get` attribution to the transport-authenticated session, not `?session_id=`. **Release-gated by HUB alongside the connect-idempotency stopgap — fix1 is not unblocked.** What remains is empirical, not definitional: enumerate the actual `hestia_vault_get` callers and whether each establishes an attested session on its transport, so the fix closes replay **without** denying a user their own secret. Guessing on a credential surface remains forbidden; the rule tells us what to verify, not what to assume.
- **Vault schema v2 (§7.1) — the workstream §7 presumes and v2 never named.** `VaultEntry` has no field for either axis and `hestia_vault_set` takes no such parameter, so §7's rule has nowhere to be recorded and §9 criterion 2's presentation half has no system under test. Add release-rule and presentation-rule fields, recorded at issuance/upsert. **Backfilling the existing corpus is a prerequisite of the rule going live, not a follow-up** — on day one every existing credential is unrecorded. **The backfill must author *both* axes, explicitly.** A backfill that records only the release axis leaves every legacy credential with no presentation rule, and §7.1's escalate-on-unrecorded then fires on every presentation of every legacy object from day one. That is McNugget's mass false-deny reflected onto the human surface: an owner who gets forty prompts a day learns to click yes, and the safe default becomes a trained allow-all **inside the primary persona's head, where no corpus test can see it** (kimi). §9 row 1b's steady-state ask-count is the instrument that catches it.
- **Presentation-rule ownership (§7.1) — currently unassigned and reads as assigned.** The two planes do not line up: `allowed_consumers` lives on the *entry* plane (`vault/entry.rs`), which holds no presentables; the one real in-vault presentable (`presence/profile`, per-link `Visibility` tiers, `profile.rs:90-121`) lives on the *document* plane (`vault/document.rs:41-49`), which has **no consumer gate at all** (`Protection::Master` = readable on the outer unlock). The presentable branch has a working *rule model* and no *enforcement point*. Name the owning component before criterion 2's presentation suite is scheduled.
- **Single-use presentations need state nobody has named.** "Single-use" in §7.1 and §9 row 2 requires a durable nullifier set — where it lives, what it does offline (§6 is offline-capable), what a constellation does when two devices present concurrently. Name that state as a requirement or drop the clause; as written it is unenforceable law sitting in a criterion.
- **Credential issuance (§5.6, §7.1) — fail-closed stopgap landed; authorization design remains.**
  `POST /credential` is operator-gated and appends `credential_issued`. The remaining work is to
  define the wallet/delegation authorization and presentation-rule contract rather than treating
  operator presence as the final product flow.
- **The two-mechanism sweep (§7.3, §9 row 5) — run once cold; two further instances, neither previously named.** Both are *latent*, which is the point: the mechanism finds them before the composition that makes them live.
  1. **Guard-exemption adjacency: `POST /callback/`** (`callback.rs:227`, nested at `http.rs:269` when `serve --callback` is used) is an **unauthenticated signing oracle** outside the operator gate. It signs caller-supplied `signing_bytes_hex` for any `event_kind` in an allowlist (`genesis`, `member_added`, `role_assigned`, `member_skill_declared`, `law_amended`) with **no intent-binding for four of the five** — only `oid4vci_credential` validates that the bytes match the intent (`validate_issuance`). `hub_id` is a caller-supplied field nothing verifies. It is survivable today **only because the key is `KeyPair::generate()` per run** (`cli.rs:851`) — an unattested ephemeral no hub can have pinned, which also makes the feature non-functional as designed. **The obvious fix — wire the real Sovereign identity — is precisely what converts this into `/credential` with `law_amended` in scope.** Its own module doc claims Hestia "evaluates authority + need-to-know, optionally prompts the operator"; none of the three exists in the handler, making this also a *declared-but-unimplemented gate* — §7.3's forbidden-threshold rule in its second form.
  2. **Sentinel-carried semantics: `DelegationScope`.** `create_delegation` maps *no roles and no actions* to `DelegationScope::unrestricted()` (`delegation.rs:40`), and the sentinel is baked into the shared type — `covers()` in `web4-core/src/delegation.rs:69` reads `roles.is_empty() || contains`, i.e. **empty means all**. `hestia delegate grant <agent>` with the optional `--role`/`--action` flags omitted takes that branch and prints `id / agent / expires` with **no scope line**, so the user is not told what they granted. Dormant only because nothing in hestia authorizes on delegations yet (the CLI grants, lists, revokes; no consumer reads them). The fix is the rule's: absence must not be expressible as authority — `Option<NonEmpty<...>>`, or an explicit `Unrestricted` variant someone has to type.
  - *Sweep coverage, stated so it is not over-read:* axum route mounts across `core/src/` are exhaustive; the sentinel grep covered `is_empty()` and absence-as-default on security-named fields and was **not** exhaustive — `member_registry.rs:227` / `role_registry.rs:165` (`!sovereign_lct_id.is_empty()`) were seen and not chased.
- **Attested connect (§7 "honest floor"):** the eventual invariant that makes release rules fully load-bearing.
- **App-contract CI (§6):** the silent skip is gone (2026-07-25); the job that boots a daemon and runs the `--ignored` tests is not built. Daemon-in-CI is the real cost — pay it or keep row 6 marked partial.
- **Release cadence (§9 row 1a) — still the largest promise-to-artifact gap.** At the 2026-08-08
  baseline, the public daemon (`v0.0.3`, 2026-05-17) is **324 `core/` commits** behind
  `origin/main`. The reference installation now runs current source, which proves deployability but
  does not help an external user acquire it. All public `app-*` releases still contain one Android
  APK and no desktop app artifact. Release the current daemon and a version-matched app, or narrow
  the public promise to the artifact that actually exists. The absent release-profile strip setting
  remains part of that release pass.

## 9. Success criteria

Each criterion names the artifact that would demonstrate it. A criterion with no
demonstrating artifact is an intention, and is marked as one — we would rather
carry an honest gap than a checkbox nobody can fail. **Rows 2–6 all evidence the
tertiary and secondary personas; only row 1 touches the primary one.** That is the
same gap §11's last risk names, stated where the coverage claim is made.

| # | Criterion | Demonstrated by |
|---|---|---|
| 1a | The crit-1 path exists *mechanically* — no config file, no key handling. | **RUN, AND IT FAILS — the first criterion in this table with a real artifact and a real verdict.** Legion ran it cold (fresh `HOME`, release binary only, 2026-07-24): step 0 acquire ✅; step 1 `init` ✅ with a pty (empty vault, no identity — §5.1); **step 2 join a hub ❌ no such command in the shipped binary**; step 3 add a device ❌ likewise; step 4 not reached. **The blocker is upstream of the persona entirely: a release gap (§8), not a build gap and not a usability gap.** The run stands as this rung's artifact and confirms its design: run by a **fleet peer who did not build hestia** — a builder cannot see what a non-builder trips over, and the runner's contamination is the variable this rung controls (PUB). Re-run per release candidate. It is not the persona test and must never be claimed as one. *Remaining human gate for the full walk: a disposable hub, or dp's go-ahead to join the live one as a throwaway member.* |
| 1b | A non-technical user does it, one sitting. | A recorded cold-run on a **fresh machine** by someone **genuinely non-technical who has never seen the repo** (every fleet member and dp is contaminated). Pass bar: **zero questions that required a builder to answer** — questions answered by in-app text are the product working. The run ends when they finish **or when they would have quit**; a four-hour success still fails §6's "seamless." Re-run per release candidate. **Run 1 is graded on the absolute bar, not a trend: it passes iff builder-answered asks = 0. If there are any, run 1 is not a pass, and every ask must resolve to a *filed, named product gap* before the next non-technical tester is spent.** This closes the deviation v4 carried on the record — a trend cannot grade the first run, and the first run is the one that matters when each subject is single-use (Sprout). It also makes the run-1 metric the right one: not *how many* asks, but *is every ask convertible* — an ask the product cannot articulate a fix for is the real run-1 failure, and a raw count hides it. From run 2 on — the first run where a trend exists — the ask-count is the metric and must be monotone decreasing. **The same metric applies in steady state, not only in the cold run:** once schema v2 lands (§8), **owner escalation prompts per day, monotone decreasing across release candidates** — that is the only instrument that would catch escalation fatigue before the owner does, and fatigue is how §7.1's safe default converts into a trained allow-all (kimi). **1a's blockers are burned down first** — a peer's goodwill renews, a first impression does not; each non-technical person is single-use as evidence, so spending one on a blocker 1a would have caught is a wasted rung (PUB), and 1a's run has now produced exactly such a blocker. **No artifact yet for either half — the largest evidential gap in this PRD** (and 1a now shows it is not the *nearest* one). |
| 1c | The ratchet survives the owner's seat: they are *correctly denied an unearned rung* and it does not feel like a wall. | An owner-seat transcript of a correct deny. Without it, "climb, don't fake" is asserted but never demonstrated from the primary persona's seat. **No artifact yet.** |
| 2 | No credential is served to a party not entitled to it under §7 — tested on **both axes and on custody**. | *Release:* current source refuses unattributed reads and mismatched explicit consumer lists, binds new default entries to the creator, and witnesses releases. The full replay suite over transport-authenticated identities is still absent, and legacy exposed entries remain. *Presentation:* disclosure beyond the rules, presentation outside the permitted set, and single-use nullification remain blocked on vault schema v2 and an enforcing component. *Custody:* a cross-device transfer without co-sign fails; with co-sign succeeds and is witnessed. **Status: containment exists; the two-axis criterion is not yet demonstrated.** |
| 3 | No legitimate credential read is ever wrongly denied (fail-secure, not fragile). | A regression corpus built from *real* false-denies — the primer-path and scope-lag cases are the seed; the empty-`allowed_consumers` migration will generate more. Every new false-deny lands here as a case before it is fixed. **Rows 2 and 3 are one principle seen from both sides (§4.1) and are scheduled, funded, and passed together — splitting them is the decoupling §4.1 exists to prevent.** |
| 4 | Concurrent sessions never clobber each other's work or misattribute an action. | The two-caller harness (Legion) run against each coordinator batch; fail-closed-under-concurrency assertions in `session/own`. |
| 5 | Every consequential surface has a passing RWOA audit on the record. | **Marked gap.** "Grep the commit history for the audit block" is a process hope, not an artifact, and it cannot fail on the defect class the fleet has actually hit twice: the connect-idempotency composition satisfied crit 5 *completely* — both commits carried passing audits — and still shipped, because the defect lived *between* them. Owed: a CI check for the audit block **and** a cross-surface invariant test. **The audit block gains one clause with a defined miss condition, aimed at the two mechanisms we have actually shipped (§7.3):** *the block names every boundary-crossing default the commit introduces or changes — both sides' reading of it — and every surface the commit adds outside an existing guard. A commit that changes a default or adds an unguarded surface without naming it fails the block.* That is checkable and can fail, which "grep the history" cannot. Until both the CI check and the invariant test exist, this row is an intention. |
| 6 | The app runs identically on laptop, phone, and Jetson. | **Partial.** Current source contains a Tauri/React app and Android release automation. Every public `app-*` release asset is an Android APK; there is no public desktop app bundle and no iOS artifact. The live client-contract tests remain `#[ignore]` and no workflow runs them, so current daemon/app compatibility is not automatically demonstrated. The public APK and daemon releases are from different dates and have no recorded version-match run. |

## 10. Non-goals (for now)

- Not a general secrets manager for arbitrary apps (it serves the agent/hub/constellation model).
- Not a cloud service (local-first; hubs are reached, not depended on).
- Not a replacement for a hub's own governance — it is the *local* citizen's trust layer.

## 11. Open questions / risks

- **The vault containment is not the final entitlement model (§5.5).** New-entry exposure and
  ambient attribution are repaired in source, but caller identity is still asserted at connect,
  legacy exposed entries remain, and the release/presentation axes are not represented in schema.
- **Vault-caller enumeration (fix1):** definition resolved (§7); the empirical survey of actual callers and their transports is still owed, and fix1 remains release-gated (§8).
- **Per-commit audits are blind to compositions — and the class has narrowed to two enumerable mechanisms.** The defects the fleet has shipped lived *between* individually-defensible surfaces, and every review regime we have is per-surface. v3 called the class "compositional," which is true and too wide to act on. It is now two mechanisms, both mechanically greppable (§7.3): **sentinel-carried semantics** (a security-relevant meaning attached to a value the receiving type cannot distinguish from absence) and **guard-exemption adjacency** (a surface added beside a gated collection inherits the exemption of its neighbours). Crit 5's audit-block clause targets exactly these two. **The narrowing has been tested rather than agreed with: the enumeration was run once, cold, and found two further instances in about fifteen minutes** (CBP, 2026-07-25, at `c03837b` — details in §8). That is the evidence for the claim that matters, which is not that the mechanisms are real but that they are *cheap to sweep*. **The honest boundary:** ordering and timing compositions fit neither mechanism, and if we ship one, the class widens again. Audit for the class you have shipped; keep the standing risk for the class you have not. (kimi, narrowing.)
- **Escalation fatigue is the fail-open the corpus tests cannot see.** §7.1 makes unrecorded-presentation escalate to the owner, which is right — but volume is now the migration hazard (§8), and an owner trained by forty prompts a day to click yes has become a fail-open that lives in a person, not in a type. Row 1b's prompts-per-day metric is the only instrument aimed at it.
- **Release cadence — the largest gap between what this document promises and what a user can obtain.**
  Current reference deployment is green, but the public daemon is 324 `core/` commits behind and
  the public app remains Android-only. Internal deployability is not external acquisition (§8,
  §9 rows 1a/6).
- **Attested connect** without hurting seamlessness for non-technical users (§7). This is the honest floor's exit, and the ratchet's first hard rung.
- **Version skew across a constellation** — how the app guides upgrades so a mixed-version constellation stays safe (§5.4).
- **Mirror-mode trust** — how a thin client safely relays policy from a sovereign node it doesn't fully control.
- **How a relying party actually consults the evidence (§4.5) — downgraded from *unsolved* to *mechanism exists, owner-facing rendering owed*.** Escalation is the mechanism and it has been exercised on the fleet plane. What is missing is the owner-facing *rendering* of an escalation: presenting "should I trust this?" without the machinery and without collapsing evidence into a verdict. A far smaller and more fundable gap than v2 claimed. The first shippable instance may be per-relationship disclosure tiering (the `trusted` visibility tier), because the user's mental model — "who sees my phone number" — already exists and carries no machinery.
- **The primary persona is unevidenced.** Every capability we have shipped was driven by the tertiary persona (the agents). That is a legitimate consequence of where we started climbing — but the roadmap will keep being argued from a persona we have never watched use the product. Criteria 1a/1b/1c exist to close this; until they do, weigh owner-facing claims accordingly.

## 12. Revision notes

### v6 (2026-08-11) — the dashboard splits agents from hubs, and trust becomes a cached quantity

Recorded from `v0.0.4-29` (the reference daemon rebuilt and restarted at that commit). This
amendment adds two things and corrects none — the prior current-state claims still hold:

1. **§5.8** gains a persistence requirement: derived trust is **persisted in the vault as a
   situational cache** and read from there for display. The deliberate, law-following recompute writes
   the cache; between recomputes the cache is authoritative; the display path re-derives nothing per
   poll. Full specification in the new **[`PRD_TRUST_CACHE.md`](PRD_TRUST_CACHE.md)**. This reconciles
   with the standing "the number is the one the law uses" ruling: the law still authors the number, at
   recompute time — the cache moves *when* it is computed, not *what*.
2. **`PRD_APP.md` §2.4** records what shipped on the daemon dashboard since `a745180`: two top-level
   views (Agents / Hubs) with a masthead switch and a smart default (`#348`/`#349`), a trust box that
   is contextual to the harness selection, idle-but-known harnesses surfaced with a staleness marker,
   and operator banners kept global above both views. The dashboard has moved *toward* the app's own
   three-places IA (§4.1), reaching the Activity/Communities split from the other end — so it is now a
   working reference for the app to instrument, not re-invent.

The kimi observation that motivated all of this — a two-day-idle member vanishing from the trust box —
is the productive failure: it exposed that display re-derived trust from a volatile window every poll,
which is the wrong hot path and the wrong source of truth. The cache is the durable answer; the
idle-harness seed (`v0.0.4-29`) is the bridge, and its removal is part of the cache PRD's done-ness.

### v5 (2026-08-08) — source, deployment, and release are separate facts

This amendment was audited from a clean worktree at `9a6a5c2` after the reference daemon was
rebuilt and restarted at that same commit. It corrects current-state claims without erasing the
historical findings that produced the repairs:

1. §5.5 now records the landed vault containment: attributed reads/writes, creator-bound defaults,
   witnessed releases, and visible legacy exposure. It retains transport authentication, migration,
   and schema v2 as open work.
2. §5.6 records `/credential` behind the operator gate with a `credential_issued` witness, while
   keeping wallet/delegation authorization open.
3. §8, §9, and §11 distinguish the current reference deployment from the public release. The
   daemon deployed internally is current; the public daemon and app remain stale and unmatched.
4. Row 2 no longer says the credential deny branch is absent. It names the containment that exists
   and the two-axis proof that does not.
5. `STATUS_AUDIT_2026-08-08.md` becomes the current evidence matrix. Earlier measurements remain
   pinned to their historical baselines rather than being silently refreshed in prose.

### v4 (2026-07-25) — three posts that landed after v3 was pushed

v3 closed the v2 review round; the round did not close. Three artifacts arrived after it:
Nomad's seventh review, Legion's crit-1 evidence run, and kimi's response to v3. Every code
claim v4 adds was re-verified by CBP at `c03837b` — the ungated `/credential` mount and its
missing gate/witness, the absence of `[profile.release]`/`strip` anywhere in the tree, and
the release lag (161 `core/` commits, up from Legion's 157).

1. **§7.1 gains the rule the two axes hang from: issuance.** Both axes governed holding and
   showing; neither governed *minting*, and minting is what is live and ungated (Nomad).
   The settled noun is untouched — this reopens nothing.
2. **§5.6 / §7.3 name the second honest floor.** An unauthenticated issuance endpoint is
   self-declared authority over the owner's key. The first floor was named and tripwired;
   this one was unnamed and live, which is the more interesting fact about it.
3. **§7.3 states the two enumerable mechanisms as law**, §9 row 5 turns them into an
   audit clause with a defined miss condition (kimi's narrowing of v3's "compositional"),
   **and §8 records what happened when the sweep was actually run**: two further instances,
   an unauthenticated signing oracle at `/callback` and an absence-means-unrestricted
   delegation scope. Both latent; neither previously named by any of the eight reviews.
4. **§9 row 1a has a verdict instead of an offer** — run cold, fails at step 2, blocked on a
   release rather than a persona (Legion), and it confirms PUB's design of the rung (`4e00a99`,
   merged here): a non-builder peer runs 1a, and 1a's blockers burn down before 1b spends
   a single-use non-technical first impression. §8 and §11 give release cadence an owner-shaped
   hole and §6 records the measured binary size: met at release, missed on `main`,
   recoverable in one line.
5. **§8 requires the schema-v2 backfill to author both axes**, and §9 row 1b makes owner
   prompts-per-day a steady-state metric, against escalation fatigue (kimi's residue on the
   default he conceded).
6. **§5.1 decides what it was**: a user-facing requirement, currently failed by the shipped
   artifact — not a description of `hestia_first_run` (Legion).

**Historical v4 queue item, resolved in source before v5:** the disposition of ungated
`/credential` (§8). The fail-closed half (operator gate + witness the act) landed. The design half
— what authorization an OID4VCI issuance should require — remains open.

### v3 (2026-07-25) — six reviews of v2

v3 incorporates six independent fleet reviews of v2 @ `912ca56` (Sprout, Thor, Legion ×2,
PUB, McNugget, kimi-code). Every code claim above was re-verified at `912ca56` by CBP
before it was written into this document.

**Two changes revise a dp ruling that v2 carried, and are marked pending:**

1. **§7.1 retires "a credential is consumable or presentable; unrecorded defaults to
   consumable"** in favour of two orthogonal per-credential rules with two safe defaults
   and an escalation instead of a guess. All six reviewers independently found the
   original noun wrong; three independently found the default unsafe in the *climb*
   direction. dp's underlying ruling — entitlement is issuance-bound, not list-bound —
   is unchanged and is what both axes are hung from.
2. **§7.2 adds custody** as distinct from release. v2's "there is no legitimate third
   party" forbade §5.4's cross-device movement and the owner reading their own vault
   (PUB and kimi found this independently). This is a fail-fragile under §4.1.

**One item is HUB's call, not hestia's:** the disposition of `min_trust_score` in
`hub-lib/src/law.rs` (§7.3) — wire with escalate-not-deny semantics, or delete.

**One item needs an owner, not a ruling:** release cadence (§8). Every other gap in this
document is someone's work; this one is nobody's, and it is the one a user actually hits.

Everything else in v3 is a correction of a statement the tree falsified (§6's enforcement
claim, §7.3's retracted names-confer-nothing sentence, §5.5's fail-open defaults, §5.7's
achieved-invariant claim), a restoration of something v1 said better (§6's falsifiable
size target, §5.5's one-sentence invariant, §3's three citizen types), or an honesty
marking §9's own rule already required (rows 5 and 6).

**Amended after v3 was posted (2026-07-25):** §9 1a/1b carry PUB's runner constraint
(a peer who did not build hestia) and the 1a-before-1b ordering. PUB's v2 review reached
this machine a second time over a different transport after v3 was cut; on re-reading it
against the doc, every other item was already in v3 — this rung was the one that was not.
No pending ruling is implicated.

---

*This PRD is the frame every hestia technical decision is measured against. When a fork appears — especially on a security surface — reason from §4 (principles) and §7 (fail-secure-not-fragile), verify the details, and decide; bring product-framed choices forward, not implementation quandaries.*
