# Hestia — Product Requirements Document

**Status**: draft v1 · **Date**: 2026-07-24 · **Owner**: dp
**Companions**: `ARCHITECTURE.md` (how it works) · `APP_BUILD_PLAN.md` (how/when it's built) · `PROTOCOL.md` (the wire) · this doc is the *what & why*.

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

## 4. Product principles

1. **Secure as possible, but never brittle.** Security must not cost seamlessness. A safety fix that breaks legitimate use (e.g. denies a user their own credential) has failed the product, not just annoyed the user. **Fail *secure*, never fail *fragile*.**
2. **Invisible security.** The accountability model (RWOA + S + V — see `CLAUDE.md`) is load-bearing and always on, but the non-technical user should never have to reason about it. Defaults are safe; depth is opt-in.
3. **Local-first, user-sovereign.** The vault, the witness chain, and policy live on the user's device by default. The cloud/hub is something you *reach*, not something you *depend on*.
4. **One app, every surface.** A single binary → desktop (Linux/macOS/Windows) + mobile (iOS/Android), in Sovereign (full node) or Mirror (thin client) mode. (See `APP_BUILD_PLAN.md`.)
5. **Trust is evidence, not a verdict.** Hestia produces inspectable, unforgeable evidence and lets the relying party decide, scaled to stakes; it never smuggles in a universal admit/exclude ruling (web4 LCT §1.2).
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
- **R (critical, and a live workstream):** a credential is released **only** to the caller entitled to it, attributed to a **transport-authenticated** identity — never to a caller-supplied, replayable claim. `allowed_consumers` is meaningful only to the degree the caller's identity is attested; where it isn't yet, it is advisory and the gap is named, never silently trusted. **The vault must fail *secure* (deny/prompt) without failing *fragile* (never deny a user their own secret).** See §7.

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
- **Small & fast:** single binary, ~12–18 MB; sub-second local operations; runs on a phone and a Jetson.
- **Cross-platform, one codebase.** Desktop + mobile, Sovereign + Mirror.
- **Offline-capable:** full local function without a hub; the hub is reach-not-depend.

## 7. Security model as product requirements (the load-bearing part)

The intent says *"as secure as possible"* **and** *"seamless for non-technical users."* Those are reconciled by one rule: **fail secure, never fail fragile.** Concretely:

- **Attribution before capability.** Any credential or consequential act binds to a *non-forgeable* identity (transport-authenticated session), not a caller-asserted argument. A caller may hold its *own* capability, never enumerate or replay a peer's.
- **Name vs capability.** Coordination and display surfaces expose *names* that confer nothing; bearer tokens (session ids, soft-LCTs) are never enumerated where they'd become lift-and-replay capabilities.
- **The honest floor.** Where the identity chain bottoms out at something self-declared (an unauthenticated connect), that is **named** (advisory, guarded by a tripwire test) — never silently treated as authenticated. Closing that floor (attested connect) is on the roadmap; until then the product does not pretend.
- **Every surface carries its RWOA self-audit** (`CLAUDE.md`) in its commit; a consequential surface that can't pass at its stakes is fixed or escalated before shipping.
- **The reconciliation for the user:** the safe path is the default and the easy one; the secure choice is never the one that breaks their workflow.

## 8. Current workstreams mapped to the PRD

- **Session-coordinator (§5.7):** read side shipped (`session/own` fail-closed, `session/siblings` + redaction, connect-idempotency), all RWOA-audited; write side (work-claims + `repo-worktree` + reaper + CLI seam) next.
- **Vault credential-boundary / fix1 (§5.5, §7):** bind `hestia_vault_get` attribution to the transport-authenticated session, not `?session_id=`. **Release-gate** on the coordinator batch. *Open architectural question to resolve before implementation (not to guess on a credential surface):* which callers invoke `hestia_vault_get`, and do they establish an attested session on their transport? The fix must close replay **without** denying a user their own secret (fail-secure-not-fragile, §4.1).
- **Attested connect (§7 "honest floor"):** the eventual invariant that makes `allowed_consumers` fully load-bearing.

## 9. Success criteria

- A non-technical user installs, joins a hub, adds a second device, and runs an agent — with zero config-file or key handling, in one sitting.
- No credential is ever served to a caller not entitled to it; no legitimate credential read is ever wrongly denied.
- Concurrent sessions never clobber each other's work or misattribute an action.
- Every consequential surface has a passing RWOA audit on the record.
- The app runs identically on a laptop, a phone, and a Jetson.

## 10. Non-goals (for now)

- Not a general secrets manager for arbitrary apps (it serves the agent/hub/constellation model).
- Not a cloud service (local-first; hubs are reached, not depended on).
- Not a replacement for a hub's own governance — it is the *local* citizen's trust layer.

## 11. Open questions / risks

- **Vault-caller architecture (blocking fix1):** resolve empirically before rewiring the credential surface (§8).
- **Attested connect** without hurting seamlessness for non-technical users (§7).
- **Version skew across a constellation** — how the app guides upgrades so a mixed-version constellation stays safe (§5.4).
- **Mirror-mode trust** — how a thin client safely relays policy from a sovereign node it doesn't fully control.

---

*This PRD is the frame every hestia technical decision is measured against. When a fork appears — especially on a security surface — reason from §4 (principles) and §7 (fail-secure-not-fragile), verify the details, and decide; bring product-framed choices forward, not implementation quandaries.*
