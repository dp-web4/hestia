# Hestia — Product Requirements Document

**Status**: draft v3 (incorporates six fleet reviews of v2; two items need dp's ruling — see §12) · **Date**: 2026-07-25 · **Owner**: dp
**Companions**: `ARCHITECTURE.md` (how it works) · `APP_BUILD_PLAN.md` (how/when it's built) · `PROTOCOL.md` (the wire) · this doc is the *what & why*.

---

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
2. **Invisible security.** The accountability model (RWOA + S + V — see `CLAUDE.md`) is load-bearing and always on, but the non-technical user should never have to reason about it. Defaults must be safe; depth is opt-in. *Stated as a requirement, not a description: the shipping vault read path currently violates it — see §5.5 and §8.*
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
- **R:** onboarding never exposes raw key material; the first-run flow is the `hestia_first_run` prompt path. Non-technical user reaches a working node in minutes.

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
- **Current state, named — the defaults are fail-*open*, on the primary persona's own path.** This is not a coverage gap; the deny branch is absent:
  - `handler.rs:823` skips the entitlement check entirely when `allowed_consumers` is empty (`!entry.allowed_consumers.is_empty() && !entry.allows(...)`), inverting the deny-by-default the type documents at `vault/entry.rs:65-69`.
  - Empty is the default everywhere it is created: `VaultEntry::new` (`entry.rs:44`), `hestia vault add` without `--allowed-consumers`, `POST /api/vault` with the key omitted, and the app's Vault page when the free-text consumers box is left blank — **which is exactly what the non-technical owner will do**, because §3 says they should never need to know what a plugin id is.
  - `matches_scope` (`entry.rs:71-79`) returns `true` on an empty scope — unrecorded scope is open, not closed.
  - `resolve_plugin_id` (`state.rs:703-716`) falls back to the *most recently connected session* when no `session_id` is supplied — ambient authority, and it races.
  So the least-informed user, following the guided path, creates a credential any caller can read, attributed to whoever connected last. Closing this is cheaper than the work fix1 is blocked on and gated on nothing (§8). Note the fail-*fragile* hazard in the other direction: making empty mean deny breaks every existing entry, so it needs a migration or a named grandfather window — that is §9 criterion 3's corpus doing its job.
  (Finding: McNugget, 2026-07-24; independently re-verified at `912ca56`.)

### 5.6 Governance / the conscience — *"do the right thing, quietly"*
- Every consequential act (sign, admit, assign role, amend law, read/release a secret, spend, mutate governed state, message outward) passes a policy gate that is preflight, atomic, and self-witnessing.
- **R:** the RWOA + S + V self-audit (`CLAUDE.md`) governs every surface. CRISIS changes accountability, not strictness. The user experiences this as "it asked me before doing something risky," nothing more.
- **R:** widening a credential's presentation rule — including deriving a presentation from a stored secret for the first time — is a **privilege-widening act**, gate-governed and witnessed. It is the obvious way to launder a bearer secret into something presentable.

### 5.7 Session coordination — *"my agents don't step on each other"*
- Multiple sessions on one machine — interactive, autonomous/mesh-launched, same or different agent family, eventually a local model — coordinate so they act as one coherent whole, not colliding.
- **R (active build):** every session is a soft-LCT identity tagged by agent family; sessions can see live siblings and claim work (the `repo-worktree` collision is first-class); the coordinator is *in* hestia because hestia already governs every local session's tool calls. Identity resolution is fail-closed under concurrency.
- **R (must be; is not yet):** coordination keys (`host_session_id`) are descriptive, **never** authorization discriminators. On the vault path this does not hold today — the `session_id` that `session/siblings` enumerates is still accepted as a lookup key by `tool_vault_get`. Named, not assumed; it is fix1's target. See the `fleet-coordination` thread + `session/own`, `session/siblings`, connect-idempotency work.

### 5.8 Trust & identity — *"who is who, provable"*
- Each user, device, agent, and hub has a witnessed, key-bound identity (LCT) with a trust tensor (T3/V3) built from an append-only witness chain.
- **R:** identity is surfaced as human trust ("this device is yours, verified"), the machinery inspectable on demand. Session-plane identity **never auto-promotes** to fleet-plane identity.

## 6. Non-functional requirements

- **Seamless:** a non-technical user completes install → join a hub → add a device → run an agent without touching a config file or a key.
- **Robust:** survives restarts, network loss, device loss; no data loss of the vault/chain; a denied/failed act leaves state bit-identical.
- **Secure:** the accountability gate is always on; secrets are never served without attribution; fail-secure-not-fragile is a hard rule.
- **Small & fast:** **~12–18 MB daemon binary**, sub-second local operations, runs on a phone and a Jetson. *Unmeasured — no artifact yet; the target is falsifiable on purpose, and the measured size is to be recorded per release build.* (The desktop app shell is its own artifact and its own budget; don't read one number as covering both.)
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
- **The honest floor.** Where the identity chain bottoms out at something self-declared (an unauthenticated connect), that is **named** (advisory, guarded by a tripwire test) — never silently treated as authenticated. Closing that floor (attested connect) is on the roadmap; until then the product does not pretend.
- **Declared-but-unread thresholds are the honest floor's mirror image, and are forbidden.** A validated, documented, never-consulted trust threshold is a hidden gate waiting for someone to wire it in good faith. Live instance: `hub-lib/src/law.rs:123` (`min_trust_score`, 11 references, all inside `law.rs`, nothing reads it at admission). Wire it with escalate-not-deny semantics, or delete it. *(Disposition is HUB's call — see §12.)*
- **Every surface carries its RWOA self-audit** (`CLAUDE.md`) in its commit; a consequential surface that can't pass at its stakes is fixed or escalated before shipping. **A per-commit audit regime is structurally blind to defects that live between two audited commits** — see §11.
- **The reconciliation for the user:** the safe path is the default and the easy one; the secure choice is never the one that breaks their workflow.

## 8. Current workstreams mapped to the PRD

- **Session-coordinator (§5.7):** read side shipped (`session/own` fail-closed, `session/siblings` + redaction, connect-idempotency), all RWOA-audited; write side (work-claims + `repo-worktree` + reaper + CLI seam) next.
- **Vault fail-open defaults (§5.5) — new, and ahead of fix1 in cost order.** Empty `allowed_consumers` must mean deny, not skip; empty scope must mean closed, not open. One-line changes, gated on nothing, no transport attestation required — but they need a migration or a named grandfather window for the existing corpus, because flipping them naively is a mass false-deny (§4.1).
- **Vault credential-boundary / fix1 (§5.5, §7):** bind `hestia_vault_get` attribution to the transport-authenticated session, not `?session_id=`. **Release-gated by HUB alongside the connect-idempotency stopgap — fix1 is not unblocked.** What remains is empirical, not definitional: enumerate the actual `hestia_vault_get` callers and whether each establishes an attested session on its transport, so the fix closes replay **without** denying a user their own secret. Guessing on a credential surface remains forbidden; the rule tells us what to verify, not what to assume.
- **Vault schema v2 (§7.1) — the workstream §7 presumes and v2 never named.** `VaultEntry` has no field for either axis and `hestia_vault_set` takes no such parameter, so §7's rule has nowhere to be recorded and §9 criterion 2's presentation half has no system under test. Add release-rule and presentation-rule fields, recorded at issuance/upsert. **Backfilling the existing corpus is a prerequisite of the rule going live, not a follow-up** — on day one every existing credential is unrecorded.
- **Presentation-rule ownership (§7.1) — currently unassigned and reads as assigned.** The two planes do not line up: `allowed_consumers` lives on the *entry* plane (`vault/entry.rs`), which holds no presentables; the one real in-vault presentable (`presence/profile`, per-link `Visibility` tiers, `profile.rs:90-121`) lives on the *document* plane (`vault/document.rs:41-49`), which has **no consumer gate at all** (`Protection::Master` = readable on the outer unlock). The presentable branch has a working *rule model* and no *enforcement point*. Name the owning component before criterion 2's presentation suite is scheduled.
- **Single-use presentations need state nobody has named.** "Single-use" in §7.1 and §9 row 2 requires a durable nullifier set — where it lives, what it does offline (§6 is offline-capable), what a constellation does when two devices present concurrently. Name that state as a requirement or drop the clause; as written it is unenforceable law sitting in a criterion.
- **Attested connect (§7 "honest floor"):** the eventual invariant that makes release rules fully load-bearing.
- **App-contract CI (§6):** the silent skip is gone (2026-07-25); the job that boots a daemon and runs the `--ignored` tests is not built. Daemon-in-CI is the real cost — pay it or keep row 6 marked partial.

## 9. Success criteria

Each criterion names the artifact that would demonstrate it. A criterion with no
demonstrating artifact is an intention, and is marked as one — we would rather
carry an honest gap than a checkbox nobody can fail. **Rows 2–6 all evidence the
tertiary and secondary personas; only row 1 touches the primary one.** That is the
same gap §11's last risk names, stated where the coverage claim is made.

| # | Criterion | Demonstrated by |
|---|---|---|
| 1a | The crit-1 path exists *mechanically* — no config file, no key handling. | A fresh-container install transcript: no `~/.hestia`, no operator key, no repo; install from the release artifact and walk install → join a hub → add a device → run an agent, logging every point requiring a decision a non-technical user could not make. **No human gate — runnable now (Legion offered to own it).** Run by a **fleet peer who did not build hestia**: a builder cannot see what a non-builder trips over, and the runner's contamination is the variable this rung controls (PUB). It is not the persona test and must never be claimed as one. |
| 1b | A non-technical user does it, one sitting. | A recorded cold-run on a **fresh machine** by someone **genuinely non-technical who has never seen the repo** (every fleet member and dp is contaminated). Pass bar: **zero questions that required a builder to answer** — questions answered by in-app text are the product working. The run ends when they finish **or when they would have quit**; a four-hour success still fails §6's "seamless." Re-run per release candidate; the ask-count is the metric and must be monotone decreasing. **1a's blockers are burned down first** — a peer's goodwill renews, a first impression does not; each non-technical person is single-use as evidence, so spending one on a blocker 1a would have caught is a wasted rung (PUB). **No artifact yet — the largest evidential gap in this PRD.** |
| 1c | The ratchet survives the owner's seat: they are *correctly denied an unearned rung* and it does not feel like a wall. | An owner-seat transcript of a correct deny. Without it, "climb, don't fake" is asserted but never demonstrated from the primary persona's seat. **No artifact yet.** |
| 2 | No credential is served to a party not entitled to it under §7 — tested on **both axes and on custody**. | *Release:* a replay-attempt suite — a caller asks for a credential it does not consume, and for a peer's, from attested and unattested transports. *Presentation:* disclosure beyond the rules, presentation to an audience outside the permitted set, re-use of a single-use presentation — all fail closed. *Custody:* a cross-device transfer without co-sign fails; with co-sign succeeds and is witnessed. **Status: one tripwire test. The release suite's deny branch is *absent*, not merely uncovered (§5.5). The presentation suite is blocked on vault schema v2 and on naming the enforcing component (§8) — until those land, this half is an intention, and is marked as one.** |
| 3 | No legitimate credential read is ever wrongly denied (fail-secure, not fragile). | A regression corpus built from *real* false-denies — the primer-path and scope-lag cases are the seed; the empty-`allowed_consumers` migration will generate more. Every new false-deny lands here as a case before it is fixed. **Rows 2 and 3 are one principle seen from both sides (§4.1) and are scheduled, funded, and passed together — splitting them is the decoupling §4.1 exists to prevent.** |
| 4 | Concurrent sessions never clobber each other's work or misattribute an action. | The two-caller harness (Legion) run against each coordinator batch; fail-closed-under-concurrency assertions in `session/own`. |
| 5 | Every consequential surface has a passing RWOA audit on the record. | **Marked gap.** "Grep the commit history for the audit block" is a process hope, not an artifact, and it cannot fail on the defect class the fleet has actually hit twice: the connect-idempotency composition satisfied crit 5 *completely* — both commits carried passing audits — and still shipped, because the defect lived *between* them. Owed: a CI check for the audit block **and** a cross-surface invariant test. Until both exist, this row is an intention. |
| 6 | The app runs identically on laptop, phone, and Jetson. | **Partial.** CI builds all targets; Android APK path is green; iOS unbuilt. The live client-contract test (§6) no longer passes while checking nothing, but **still does not run in CI** — this row's "demonstrated by" claims a check that nothing automatic invokes. |

## 10. Non-goals (for now)

- Not a general secrets manager for arbitrary apps (it serves the agent/hub/constellation model).
- Not a cloud service (local-first; hubs are reached, not depended on).
- Not a replacement for a hub's own governance — it is the *local* citizen's trust layer.

## 11. Open questions / risks

- **The vault's shipping defaults are fail-open (§5.5).** Highest-severity known gap; on the primary persona's own path; cheaper to close than fix1.
- **Vault-caller enumeration (fix1):** definition resolved (§7); the empirical survey of actual callers and their transports is still owed, and fix1 remains release-gated (§8).
- **Per-commit audits are blind to compositions.** The two defects the fleet has actually shipped both lived *between* two individually-defensible surfaces. Every review regime we have is per-surface. This is a standing structural risk, not a backlog item (crit 5).
- **Attested connect** without hurting seamlessness for non-technical users (§7). This is the honest floor's exit, and the ratchet's first hard rung.
- **Version skew across a constellation** — how the app guides upgrades so a mixed-version constellation stays safe (§5.4).
- **Mirror-mode trust** — how a thin client safely relays policy from a sovereign node it doesn't fully control.
- **How a relying party actually consults the evidence (§4.5) — downgraded from *unsolved* to *mechanism exists, owner-facing rendering owed*.** Escalation is the mechanism and it has been exercised on the fleet plane. What is missing is the owner-facing *rendering* of an escalation: presenting "should I trust this?" without the machinery and without collapsing evidence into a verdict. A far smaller and more fundable gap than v2 claimed. The first shippable instance may be per-relationship disclosure tiering (the `trusted` visibility tier), because the user's mental model — "who sees my phone number" — already exists and carries no machinery.
- **The primary persona is unevidenced.** Every capability we have shipped was driven by the tertiary persona (the agents). That is a legitimate consequence of where we started climbing — but the roadmap will keep being argued from a persona we have never watched use the product. Criteria 1a/1b/1c exist to close this; until they do, weigh owner-facing claims accordingly.

## 12. Revision note — what v3 changed, and what needs a ruling

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
