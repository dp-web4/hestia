# Hestia

> Make your existing AI agents Web4-compliant.

Hestia is the open-source layer that adds **identity**, **trust**, and a **credential vault** to whatever AI agents you already use — Claude Code, OpenClaw, Cursor, Cline, ChatGPT desktop, ruflo, local LLMs. Plugin install. No workflow changes. Local-first.

> **Status:** Phase 0 (foundations). Not yet usable. This README describes the target.

## What Hestia is

Hestia is to agent ecosystems what TLS is to HTTP — a transparent layer that makes the thing you actually care about (your agent of choice) more trustworthy, without changing what you touch.

You keep using Claude Code. You keep using OpenClaw. You keep using whatever IDE plugin or chat UI you've already chosen. Hestia runs alongside and:

- **Holds your credentials securely.** One vault for all the API keys and tokens that are currently scattered across `.pypirc`, `.cargo/credentials.toml`, `.npmrc`, `.env` files, IDE config, environment variables. Encrypted at rest. Exposed to your agents through a controlled MCP interface, with witness chain (audit trail) of every access.
- **Gives each agent a cryptographic identity.** When Claude Code does work for you, it does so as a witnessed actor in your personal Web4 society. Same for OpenClaw, Cursor, anything you plug in.
- **Tracks reputation that evolves from observed behavior.** T3/V3 trust tensors per agent, with decay. Over time you can answer: "which of my agents is most reliable on Python tasks?" — from real data, not vibes.
- **Federates when you want it to.** Carry embers from your hearth to light another's: portable society state, inter-society protocol, teammate federation. (Phase 4.)

What Hestia is **not**:
- Not a replacement agent UI. Not a chat interface. Not an IDE. Not a workflow builder.
- Not a vendor cloud. Your trust state, witness chain, and credentials live on your machine.

## The metaphor (since the name asks for one)

**Hestia** is the Greek goddess of hearth, home, family — and the state. Every Greek household and every Greek city-state had a public hearth dedicated to her. When colonies were founded, embers from the mother city's hearth were carried to the new one to ignite it.

That's the product, more or less. Your local Web4 society is the hearth. Your agents are guests under your laws of hospitality (Greek *xenia*). You tend the trust state. When you federate with someone else, you carry embers.

## Repository layout

```
hestia/
├── plugin-sdk/           # The Plugin Authoring Kit (PAK)
│   ├── typescript/       # @hestia-tools/plugin-sdk on npm
│   ├── python/           # hestia-plugin-sdk on PyPI
│   └── rust/             # hestia-plugin-sdk on crates.io
├── core/                 # Rust core (vault, MCP host, society state)
├── app/                  # Tauri desktop app (the inspection UI)
├── plugins/              # First-party plugin implementations
│   ├── claude-code/      # Hestia plugin for Claude Code
│   ├── openclaw/         # Hestia plugin for OpenClaw
│   ├── ruflo/            # Hestia plugin for ruflo (formerly claude-flow)
│   └── ... more in Phase 2
├── docs/                 # Public documentation
│   ├── ARCHITECTURE.md
│   ├── PLUGIN_AUTHORING_GUIDE.md
│   └── DESIGN_DECISIONS/ # ADR-style decision records
└── examples/             # Worked examples for users
```

## Where this fits in the Web4 ecosystem

Hestia is built on the Web4 ontology:

```
Web4 = MCP + RDF + LCT + T3/V3*MRH + ATP/ADP
```

We use [`web4-core`](https://crates.io/crates/web4-core), [`web4-trust-core`](https://crates.io/crates/web4-trust-core), and [`web4-sdk`](https://pypi.org/project/web4-sdk/) (all currently at v0.2.0 / v0.27.0) for the underlying primitives. Hestia adds the local-first credential vault, the MCP plugin host, the inspection UI, and the user-sovereign packaging.

Spec: [github.com/dp-web4/web4](https://github.com/dp-web4/web4)

## Comparing Hestia to existing tools

| | Hestia | Conductor | Claude Code Agent View | Microsoft AGT | OpenClaw / Cline / Cursor | 1Password / Bitwarden |
|---|---|---|---|---|---|---|
| **Replaces your agent UI** | No | Yes (Mac) | Yes (Claude only) | No | Themselves | No |
| **Multi-vendor (cross-tool)** | ✓ | Coding only | Claude only | Enterprise-shaped | One tool each | No (humans only) |
| **Local-first / sovereign** | ✓ | ✓ | ✓ | Partial | Mixed | ✓ |
| **Credential vault** | ✓ | — | — | — | — | ✓ (human-only) |
| **Cryptographic agent identity** | ✓ | — | — | ✓ DID | — | — |
| **Evolving trust state** | ✓ T3/V3 | — | — | ✓ 0-1000 | — | — |
| **Hardware binding (premium)** | ✓ | — | — | — | — | ✓ |
| **Open source** | ✓ AGPL | Mac app | Anthropic's | ✓ MIT | Most | Bitwarden free / 1P paid |

We don't compete with the agents (we make them Web4-compliant). We don't compete with dashboards (we're alongside, not instead). We complement password managers (we're for agents; they're for humans). Where we overlap with Microsoft's Agent Governance Toolkit, the difference is *who's in charge*: MAGT is enterprise governance imposed top-down; Hestia is user-sovereignty over agents you chose.

## Tiers

- **Open source (this repo) — Free, AGPL-3.0-or-later.** Everything except hardware binding + commercial license. Encrypted local-file vault, full Web4 society, plugins, MCP host, inspection UI. Use forever, no payment, no signup.
- **Premium individual — TBD pricing.** Hardware binding to TPM / YubiKey + password recovery + cloud backup with envelope encryption.
- **Commercial seat — TBD pricing.** Above + commercial license (escape AGPL for closed-source integration) + team admin console + audit log export.
- **Enterprise — Custom.** On-prem central admin + SSO/SCIM + compliance attestation kit. (Hardbound integration.)

The open-source tier is real and complete. Not crippleware.

## Status — Phase 0

This repository is being bootstrapped. The plan:

- **Phase 0 (2-3 weeks):** Foundations + Plugin Authoring Kit extraction from the three existing Web4 governance plugins (`web4/claude-code-plugin`, `moltbot/extensions/web4-governance`, `claude-flow/v3/plugins/web4-governance` — now `ruvnet/ruflo`).
- **Phase 1 (4-6 weeks):** Vault MVP + refactor first plugin (OpenClaw) against the PAK.
- **Phase 2 (6-8 weeks):** New plugin adapters (Cursor, Cline, ChatGPT desktop) + inspection UI.
- **Phase 3 (4 weeks):** Premium tier launch (hardware binding).
- **Phase 4 (8-12 weeks):** Federation + commercial tier.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) and [docs/PLUGIN_AUTHORING_GUIDE.md](docs/PLUGIN_AUTHORING_GUIDE.md) for the technical shape.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Plugin authors: see [docs/PLUGIN_AUTHORING_GUIDE.md](docs/PLUGIN_AUTHORING_GUIDE.md). This is research-stage work; the API surface will change as we learn from design partners.

## License

[AGPL-3.0-or-later](LICENSE). Commercial license available for closed-source use — see the commercial tier above.

## Acknowledgments

Hestia stands on the existing Web4 governance plugins. Three independent implementations of the same core surface gave us the pattern that the Plugin Authoring Kit crystallizes:

- [`web4/claude-code-plugin`](https://github.com/dp-web4/web4/tree/main/claude-code-plugin) (open PR [anthropics/claude-code#20448](https://github.com/anthropics/claude-code/pull/20448))
- [`moltbot/extensions/web4-governance`](https://github.com/getclawdbot/moltbot/) (OpenClaw, formerly Moltbot — renamed after Anthropic trademark complaint)
- [`claude-flow/v3/plugins/web4-governance`](https://github.com/ruvnet/ruflo/tree/main/v3/plugins/web4-governance) (ruflo, formerly claude-flow — rebranded by ruvnet per their ADR-046)

All three credit-back to dp-web4 / dp@metalinxx.io.
