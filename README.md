# Hestia

> Universal Web4 presence — for humans and AI.

Hestia is the open-source local-first layer that gives any entity — human user, AI agent, autonomous service — a **cryptographic identity**, an **encrypted vault**, **delegation authority**, and a **trust record** in the Web4 ecosystem. Plugin install for AI agents. CLI for humans. No cloud required.

> **Status:** Phase 1 (functional core). Vault, policy engine, witness chain, delegation, plugin SDK, and CLI are built and working. Hub integration (Phase 2) in progress. See [Honest Status](#honest-status) below.

## What Hestia does

### For humans
- `hestia init` → encrypted vault + Web4 LCT identity on your machine
- `hestia vault add` → store API keys, tokens, secrets (ChaCha20-Poly1305 + Argon2id)
- `hestia delegate grant <agent-id> --role administrator --expires 24` → give an AI agent scoped authority, cryptographically signed, revocable
- `hestia delegate list` / `hestia delegate revoke` → manage what your agents can do
- `hestia connect-hub <url>` → join a Web4 hub (community, team, org) with your identity *(in progress)*

### For AI agents
- Plugin SDK (Rust, TypeScript, Python) → connect to the local Hestia daemon
- `beginAction()` / `recordOutcome()` → witnessed audit trail of every tool call
- `vaultGet()` / `vaultSet()` → access credentials through controlled MCP interface
- `queryPolicy()` → check what you're allowed to do before doing it
- Delegated authority from human owner → act within scoped permissions

### For the Web4 ecosystem
- Each Hestia instance is a full Web4 presence: LCT identity, T3/V3 trust tensors, witness chain
- Hub integration: present your identity to communities, sign requests, carry trust
- Federation: portable society state between instances *(Phase 4)*

## What Hestia is not

- Not a replacement agent UI, chat interface, IDE, or workflow builder
- Not a vendor cloud — everything lives on your machine
- Not just for AI agents — humans are first-class (the "universal" in universal presence)

## The metaphor

**Hestia** is the Greek goddess of hearth. Every household and city-state had a public hearth dedicated to her. When colonies were founded, embers from the mother city's hearth were carried to light the new one. That's the product: your local Web4 society is the hearth. Your agents are guests under your laws of hospitality. When you connect to a hub, you carry embers.

## Honest status

### Built and working (Phase 1)

| Component | Status | Notes |
|-----------|--------|-------|
| **Vault** | Working | ChaCha20-Poly1305 + Argon2id, passphrase-first. CLI: init, add, get, list, remove. |
| **Policy engine** | Working | 4 presets (permissive/safety/strict/audit-only), custom rules, rate limiting, glob+regex matchers. |
| **Witness chain** | Working | SQLite-backed, hash-linked entries, integrated with web4-trust-core. |
| **Trust evolution** | Working | T3/V3 per agent, fed from tool call outcomes. |
| **Delegation** | Working | DelegatedAuthority (web4-core U2), scoped by role+action, signed, revocable. CLI: grant, list, revoke. |
| **MCP server** | Working | 8 tools exposed via rmcp + Axum HTTP. |
| **Plugin SDK** | Working | Rust, TypeScript, Python — identical interface. |
| **Claude Code plugin** | Working | PostToolUse witness hook, policy gating. Deployed on 4 machines. |
| **CLI** | Working | vault, policy, delegation, serve, dashboard, info, init. |
| **TUI dashboard** | Working | ratatui terminal UI against running daemon. |
| **Desktop app** | Scaffolded | Tauri 2 cross-platform. Framework ready, UI incomplete. |

### Not yet built (Phase 2+)

| Component | Status | Dependency |
|-----------|--------|------------|
| **Hub connection** (`connect-hub`, `list-hubs`, `sign-request`) | In progress | Hub API surface (Track B) |
| **Multi-hub connector** | Not started | Hub connection |
| **AI variant** (autonomous vault) | Design decision | Same code, different ownership model |
| **PreToolUse policy gating** | Not started | Policy engine is ready; hook wiring needed |
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
├── app/                  # Tauri 2 desktop app (inspection UI)
├── docs/                 # Architecture, plugin guide, ADRs
│   └── DESIGN_DECISIONS/ # ADR-style decision records
└── demo/                 # Worked examples (consumer + enterprise)
```

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

## License

[AGPL-3.0-or-later](LICENSE). Commercial license available for closed-source use.
