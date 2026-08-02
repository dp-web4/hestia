# Hestia

> **Governance for multi-vendor AI agents — local-first, witnessed, and earned.**
> The road to universal Web4 presence for humans and AI. We are some way along it.

Hestia is the open-source local-first daemon that lets **AI agents from different vendors
share one machine under one law**: a single signed policy every agent transits, a
hash-chained record of what each one did, a human in the loop when an agent reaches for
something it should not have, and a trust score **derived from that record** rather than
asserted. Claude Code, Codex, Kimi, Gemini and Cursor plug into the same gate. No cloud
required.

That governance is what makes an agent **admissible to a Web4 hub**. A hub cannot verify
an agent it has no record of; Hestia is where the record is made, so the hub has something
to check. Governance is the key to hub access, not a feature beside it —
see [Hub membership](#hub-membership).

**On the headline.** This README used to open *"Universal Web4 presence — for humans and
AI."* That is the destination and the project is not there. What exists today and is
exercised daily is the governance layer above; the human-presence half (cross-platform
app, credential issuance, device constellation) is **built but thinly exercised**, and
federation is not started. The tables below separate *measured*, *plumbed but unexercised*
and *not built*, because a status page that flattens those three is the same defect this
codebase keeps finding in itself: a check that reports success while measuring nothing.

> **Status:** Phase 2 (connected presence). The core (vault, policy engine, witness chain, delegation, plugin SDK) and the cross-platform app are built and working. Hub integration works end-to-end: join a hub, push your profile, open an encrypted member↔hub channel, prove your device constellation, and exchange **end-to-end-sealed member↔member messages** through the hub with a **durable, crash-safe inbox** (accept-and-defer). EUDI-compatible credential issuance is wired. See [Honest Status](#honest-status) below.

> ### ⚠️ The gate stops accidents, not adversaries
>
> Hestia's policy gate is an **early prototype**. It reliably stops simple erroneous or
> accidentally-destructive commands, and it produces an accountability record. It **does
> not** — and is not intended to — stop a sophisticated agent from routing around or
> gaming it. A heuristic gate always plays whack-a-mole with a general reasoner.
>
> **Read [issue #49](https://github.com/dp-web4/hestia/issues/49) before relying on it.**
> It states the honest scope, the measured bypasses (two environment variables suffice
> today), a demonstrated third-party reputation-poisoning class, and the planned hardening:
> an agentic heterogeneous policy entity, better heuristics, relying parties that demand
> policy-signed actions, and ultimately OS-kernel-level enforcement.

> **A living example.** The lab that builds and runs Hestia is itself a live Web4 society — a public fleet of autonomous agents that hold roles and witness each other's work. Its members are published at **[4-lab.io/fleet](https://4-lab.io/fleet)**. Presence over privacy: a society that isn't witnessed has no presence to trust, so the collective is visible by design. (Secrets stay in the vault; presence stays in the open — the same split Hestia draws in code.)

## What Hestia does

### For humans

**The app is the front door** — a cross-platform desktop app (Tauri 2) with
dashboard, vault, witness chain, delegations, hubs, policy, fleet, and
settings views. Everything below is also available in the app; the CLI is the
same engine for terminal people:

- `hestia init` → encrypted vault + Web4 LCT identity on your machine
- `hestia vault add` → store API keys, tokens, secrets (ChaCha20-Poly1305 + Argon2id)
- `hestia delegate grant <agent-id> --role administrator --expires 24` → give an AI agent scoped authority, cryptographically signed, revocable
- `hestia delegate list` / `hestia delegate revoke` → manage what your agents can do
- `hestia connect-hub <url>` → join a Web4 hub (community, team, org) with your identity
- `hestia constellation add|list|remove|proof` → link your devices into a verifying constellation — multi-device proof is your MFA
- Profile with tiered visibility → declare skills and presence links; push to hubs on your terms

### For AI agents
- Plugin SDK (Rust, TypeScript, Python) → connect to the local Hestia daemon
- `beginAction()` / `recordOutcome()` → witnessed audit trail of every tool call
- `vaultGet()` / `vaultSet()` → access credentials through controlled MCP interface
- `queryPolicy()` → check what you're allowed to do before doing it
- Delegated authority from human owner → act within scoped permissions

### For the Web4 ecosystem
- Each Hestia instance is a full Web4 presence: LCT identity, T3/V3 trust tensors, witness chain
- Hub integration: join hubs, push member-tier profiles, query and act over an end-to-end encrypted member↔hub channel
- Constellation attestation: challenge-bound multi-device proof carried in the hub handshake *(plumbed, unexercised)*
- Credential issuance: OID4VCI issuer endpoints (SD-JWT-VC) — person-scale, EUDI-wallet compatible *(plumbed, unexercised)*
- Federation: portable society state between instances *(Phase 4, not started)*

## Hub membership

**Governance is the entry condition for hub access, not a feature beside it.**

A hub is asked to accept acts from an agent it cannot see. It has three questions and no
way to answer them alone: *who is this, what may it do, and what has it done?* An agent
with no local governance can only answer by assertion — and an assertion is exactly what a
hub must not accept, because anything the agent can say, a compromised or careless agent
can say identically.

Hestia is where those answers are *made*, so the hub has something to check:

| Hub asks | Hestia supplies |
|---|---|
| who is this? | an LCT identity with a key, plus the roles it actually holds |
| what may it do? | the composed law it operates under — readable by the agent itself, and hashed, so both sides can name the same law |
| what has it done? | a hash-chained record of its acts, including the ones it was refused and what it did next |
| should we believe the score? | a trust tensor **derived** from that chain at read time, shipping its receipts — not a number the agent reports about itself |

That last row is the load-bearing one. A self-reported reputation is worth nothing to a
relying party. A derived one can be recomputed by anyone holding the chain, which is what
makes it evidence rather than a claim.

**What this does not mean.** A hub should not treat Hestia's word as proof. At A1 the gate
is cooperative and same-UID: the record is unforgeable-ish and *inspectable*, which is the
actual product. Web4's own norm applies — a surface makes evidence checkable and never
encodes a universal trust threshold; how much to trust it stays the relying party's call,
scaled to stakes. A hub that demands more should require policy-signed acts and an
assurance profile above A1, and Hestia should be able to say honestly that it does not
have one yet.

## What Hestia is not

- Not a chat interface, IDE, or workflow builder — Hestia has its own app, but it's the home for your *presence*, not a replacement for your working tools
- Not a vendor cloud — everything lives on your machine
- Not just for AI agents — humans are first-class (the "universal" in universal presence)

## The metaphor

**Hestia** is the Greek goddess of hearth. Every household and city-state had a public hearth dedicated to her. When colonies were founded, embers from the mother city's hearth were carried to light the new one. That's the product: your local Web4 society is the hearth. Your agents are guests under your laws of hospitality. When you connect to a hub, you carry embers.

## Honest status

*Audited against the running system on 2026-08-01 — method and evidence in
[`docs/STATUS_AUDIT_2026-08-01.md`](docs/STATUS_AUDIT_2026-08-01.md). Three tiers, kept
apart on purpose:*

- **Measured** — exercised on a live system, with chain entries or a live probe behind it.
- **Plumbed** — code and tests exist, the path has not been driven end to end in anger.
  Not a euphemism for broken; it means nobody has yet found out.
- **Not built** — stated so it cannot be inferred from silence.

### The governance layer — measured

This is the part that runs every day and has the scars to prove it.

| Component | Status | Evidence |
|-----------|--------|----------|
| **Policy gate, multi-vendor** | Measured | One gate, six vendor surfaces (`claude-code`, `codex`, `kimi`, `gemini`, `cursor`, `openclaw`). Claude-lineage hook engines fail OPEN on error, so each adapter is fail-closed by construction. |
| **Witness chain** | Measured | Hash-linked SQLCipher; every tool call lands. ~86k entries on the reference box. |
| **Human escalation** | Measured | A refused governance write is offered to a human: dashboard notice, `hestia gate approve/deny`, or an operator-authenticated HTTP decision. Single-use, expiring, witnessed both ends. Store is **rehydrated from the chain**, so a deploy no longer destroys a ruling. |
| **Peer arbitration** | Measured | A NOT-SAME peer can rule an escalation; `arbiter::eligibility` enforces independence server-side, cross-vendor ranked above cross-member. |
| **Per-member policy** | Measured | Loosen or tighten ONE agent without moving the society. Tightening persists (vault); loosening is memory-only and dies with the daemon. Operator-only — no MCP tool can set it, asserted by test. |
| **Trust derivation (T3/V3)** | Measured | Pure read-time function over the chain, versioned, ships its receipts. Temperament scores conduct after a deny: re-running 0.0, adapting 0.85, escalating and being upheld 1.0. Unmeasured renders *unmeasured*, never a default prior. |
| **Vault** | Measured | ChaCha20-Poly1305 + Argon2id, passphrase-first. |
| **MCP server** | Measured | **29 tools** over rmcp + Axum. (This table said 12 for months; it was stale, which is why this audit exists.) |
| **Web dashboard** | Measured | Served by the daemon at `/`; the interface actually used daily. Operator-gated behind an Ed25519 challenge-signed session. |
| **Delegation** | Measured | Scoped by role+action, signed, revocable. |
| **Plugin SDK** | Measured | Rust, TypeScript, Python — same interface. |

**Assurance ceiling, stated with it:** all of the above is profile **A1** — a cooperative
gate running as the same UID as the operator. Tamper-**evident**, not tamper-proof.
[`docs/GATE_BYPASS_CATALOG.md`](docs/GATE_BYPASS_CATALOG.md) catalogues the ways around it,
including two environment variables that suffice today. Enforcement against a determined
agent needs A2+ (separate UID) and is not available now.

### Built but thinly exercised — *plumbed*

Real code, real tests, not yet driven in anger. Believe the code; do not yet believe the
uptime.

| Component | Status | What is untested |
|-----------|--------|------------------|
| **Cross-platform app (Tauri 2)** | Plumbed | 374 source files, last substantive commit 2026-07-24. The README called it "the primary human interface"; in practice the **web dashboard is what gets used**, and the app has not been exercised alongside recent daemon changes. |
| **Device constellation** | Plumbed | 1,183 lines, 21 unit tests, wired into the hub handshake as multi-device proof. **Zero constellation events in the live chain window** — the path has never been driven on a real second device. |
| **Credential issuance (OID4VCI / SD-JWT-VC)** | Plumbed | Endpoints exist and are gated; no wallet has completed a round trip here. |
| **Member↔member sealed channels + durable inbox** | Plumbed | Exercised in tests and in fleet mesh traffic; not under adversarial or multi-hub conditions. |
| **AI variant (agent-owned vault)** | Plumbed | `--ai` flag exists; ownership model still maturing. |

### Not built

| Component | Status | Blocked on |
|-----------|--------|------------|
| **Federation** | Not started | Phase 4 |
| **Multi-hub connector** | Not started | single-hub works |
| **Hardware binding** (TPM/YubiKey/SE) | Trait contracts only | Hardbound enterprise tier |
| **Vault credential injection** | Not started | SDK surface exists |
| **A2+ enforcement** (separate UID) | Not started | the honest ceiling on everything above |

### Superseded status table (retained for reference)

| Component | Status | Notes |
|-----------|--------|-------|
| **Vault** | Working | ChaCha20-Poly1305 + Argon2id, passphrase-first. CLI: init, add, get, list, remove. |
| **Policy engine** | Working | 4 presets (permissive/safety/strict/audit-only), custom rules, rate limiting, glob+regex matchers. |
| **Witness chain** | Working | SQLite-backed, hash-linked entries, integrated with web4-trust-core. |
| **Trust evolution** | Working | T3/V3 per agent, fed from tool call outcomes. |
| **Delegation** | Working | DelegatedAuthority (web4-core U2), scoped by role+action, signed, revocable. CLI: grant, list, revoke. |
| **MCP server** | Working | 12 tools exposed via rmcp + Axum HTTP. |
| **Plugin SDK** | Working | Rust, TypeScript, Python — identical interface. |
| **Claude Code plugin** | Working | PostToolUse witness hook, policy gating. Deployed on 4 machines. |
| **CLI** | Working | vault, policy, delegation, constellation, serve, dashboard, info, init. |
| **TUI dashboard** | Working | ratatui terminal UI against running daemon. |
| **Cross-platform app** | Working | Tauri 2. Dashboard, Vault, Chain, Delegations, Hubs, Policy, Fleet, Settings — served by the daemon's REST API. This is the primary human interface. |
| **Hub connection** | Working | Join a hub (member self-add), push member-tier profile, signed callbacks. |
| **Member↔hub channel** | Working | End-to-end encrypted (sealed channel) with HTTP transport — queries and acts off plaintext. |
| **Paired member↔member channels** | Working | Request/confirm a pair and exchange end-to-end-sealed messages through the hub (X25519 + ChaCha20-Poly1305); the peer's static channel key is resolved from the hub's pinned-pubkey endpoint. The hub relays ciphertext content-blind. |
| **Durable inbox (accept-and-defer)** | Working | SQLCipher-encrypted inbound mailbox (`inbox.db`): `hestia_notify --defer` parks a sealed notice, drained later by `hestia_inbox` / `hestia_pair_inbox` with consume-once, at-least-once semantics (mcp-protocol §7.8). Survives a daemon restart. |
| **Constellation** | Working | Link devices into a verifying constellation; challenge-bound attestation in the hub handshake (multi-device proof as MFA). |
| **Profile** | Working | Skills + social/professional presence links with tiered visibility. |
| **Credential issuance** | Working | OID4VCI issuer endpoints, SD-JWT-VC — EUDI-wallet-compatible, person-scale. |
| **PreToolUse policy gating** | Working | Synchronous policy gate in the Claude Code plugin — daemon-decided verdict (allow/warn/deny via exit code), wait protocol for slow policy entities, legacy-engine fallback, pairs with the PostToolUse witness. |
| **AI variant** (autonomous vault) | Initial | `--ai` flag for agent-owned vaults; ownership model still maturing. |

### Not yet built (Phase 3+)

| Component | Status | Dependency |
|-----------|--------|------------|
| **Multi-hub connector** | Not started | Single-hub connection (done) |
| **Vault credential injection** | Not started | Plugin SDK surface exists |
| **Hardware binding** (TPM/YubiKey/SE) | Trait contracts only | Hardbound enterprise tier |
| **Federation** | Not started | Phase 4 |

### What changed from the original plan

The original README (April 2026) described Hestia as an agent-tracking layer — "make your existing AI agents Web4-compliant." That's still true but undersells it. As of the V2 architecture work (June 2026), Hestia is the **universal Web4 presence primitive** for both humans and AI:

- Humans use Hestia to manage their Web4 identity, join hubs, and delegate authority to agents
- AI agents use Hestia to hold credentials, act under delegation, and build witnessed trust records
- Hubs verify Hestia-signed requests for both humans and AI

The vault + delegation + witness chain serve both roles. The "agent tracking" framing was Phase 0 thinking; the V2 architecture elevates Hestia to the presence substrate for the entire Web4 ecosystem.

## Repository layout

```
hestia/
├── core/                 # Rust core (vault, MCP host, delegation, policy, witness chain)
├── plugin-sdk/           # Plugin Authoring Kit
│   ├── rust/             # hestia-plugin-sdk (crates.io)
│   ├── typescript/       # @hestia-tools/plugin-sdk (npm)
│   └── python/           # hestia-plugin-sdk (PyPI)
├── plugins/              # First-party plugin implementations
│   ├── claude-code/      # Claude Code witness + policy hooks
│   └── openclaw/         # OpenClaw integration
├── hardbound-pak/        # Enterprise trait contracts (TPM/YubiKey/SE)
├── app/                  # Tauri 2 cross-platform app — the primary human interface
├── docs/                 # Architecture, plugin guide, ADRs
│   └── DESIGN_DECISIONS/ # ADR-style decision records
└── demo/                 # Worked examples (consumer + enterprise)
```

## Witnessed law

Hestia is **policy-neutral**: it doesn't dictate how you run your own identity or
device constellation — *you* set the rules (which devices belong, what each may
do, what requires your presence, what your agents are delegated), and Hestia
**enforces those rules and records adherence**. Every consequential act runs
through your **policy engine** and is recorded in your local **witness chain**;
delegations are scoped and revocable; nothing acts outside the authority you
granted. This is the Web4 posture (web4's "Law is witnessed, not dictated") at
*personal / constellation* scale — the same shape a hub has at society scale:
the system doesn't mandate the policy, it insists that whatever your policy is,
is followed verifiably. Convenience is your choice; the audit trail is not.

## Web4 foundation

```
Web4 = MCP + RDF + LCT + T3/V3*MRH + ATP/ADP
```

Hestia uses [`web4-core`](https://github.com/dp-web4/web4/tree/main/web4-core) for LCT identity, delegation, role assignment, and crypto. Uses [`web4-trust-core`](https://github.com/dp-web4/web4/tree/main/web4-trust-core) for witness chain persistence and trust state.

## Tiers

- **Open source (this repo) — Free, AGPL-3.0-or-later.** Vault, delegation, witness chain, trust evolution, policy engine, plugin SDK, CLI, TUI, MCP server. Complete and real.
- **Premium individual — TBD.** Hardware binding (TPM/YubiKey/SE) + cloud backup with envelope encryption.
- **Commercial seat — TBD.** Commercial license (escape AGPL) + team admin + audit export.
- **Enterprise — Custom.** On-prem admin + SSO/SCIM + compliance attestation. (Hardbound integration.)

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Plugin authors: see [docs/PLUGIN_AUTHORING_GUIDE.md](docs/PLUGIN_AUTHORING_GUIDE.md).

## What hestia is not

**Pretty good governance, not a bulletproof sandbox.** The gate runs as a child of the
agent, with the agent's privileges, reading the agent's environment — it lives inside the
blast radius it is meant to bound. It buys a speed bump against the efficient path, an
accountability record, and a tripwire. It does not buy containment.

Start with **[issue #49](https://github.com/dp-web4/hestia/issues/49)** for the honest
scope and the hardening roadmap, then
**[docs/GATE_BYPASS_CATALOG.md](docs/GATE_BYPASS_CATALOG.md)** —
a catalogue of the ways around the gate, which of them we can detect, and the two we
honestly cannot. It includes measured full bypasses (two environment variables suffice
today) and the one-variable mitigation that closes them.

## License

[AGPL-3.0-or-later](LICENSE). Commercial license available for closed-source use.
