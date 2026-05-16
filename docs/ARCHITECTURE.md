# Hestia Architecture

Phase 0 working architecture. Will refine as Phase 1 implementation reveals real constraints.

## The shape, top-down

```
┌─────────────────────────────────────────────────────────────────────┐
│                  USER'S MACHINE                                     │
│                                                                     │
│  ┌────────────────────────────────────────────────────────────┐    │
│  │                    Hestia (Tauri app)                      │    │
│  │                                                            │    │
│  │   Inspection UI (React + TS, opt-in viewing)               │    │
│  │      ↕  Tauri IPC                                          │    │
│  │   ┌───────────────────────────────────────────────────┐    │    │
│  │   │              Rust core                            │    │    │
│  │   │   ┌──────────┐  ┌──────────┐  ┌─────────────┐     │    │    │
│  │   │   │  Vault   │  │ MCP host │  │  Society    │     │    │    │
│  │   │   │ ChaCha20 │  │  + tools │  │  state mgr  │     │    │    │
│  │   │   │ Argon2id │  │ +resources│ │             │     │    │    │
│  │   │   └──────────┘  └──────────┘  └─────────────┘     │    │    │
│  │   │                                                   │    │    │
│  │   │   ┌───────────────────────────────────────────┐   │    │    │
│  │   │   │ web4-core + web4-trust-core v0.2.0        │   │    │    │
│  │   │   │ (Rust crates, already published)          │   │    │    │
│  │   │   └───────────────────────────────────────────┘   │    │    │
│  │   │                                                   │    │    │
│  │   │   Premium: TPM/YubiKey/cloud-backup modules      │    │    │
│  │   └───────────────────────────────────────────────────┘    │    │
│  │                                                            │    │
│  │                ↕   MCP (stdio + http)                      │    │
│  └────────────────┼───────────────────────────────────────────┘    │
│                   │                                                 │
│       ┌───────────┼───────────┬──────────┬──────────┐               │
│       │           │           │          │          │               │
│   ┌───▼────┐  ┌───▼────┐  ┌──▼────┐  ┌──▼────┐  ┌──▼────┐           │
│   │ Claude │  │OpenClaw│  │Cursor │  │ Cline │  │  ...  │           │
│   │  Code  │  │        │  │       │  │       │  │       │           │
│   └────────┘  └────────┘  └───────┘  └───────┘  └───────┘           │
│   (each agent client runs Hestia plugin = thin observer            │
│    emitting R6/R7 records to Hestia, querying for credentials      │
│    and policy decisions)                                           │
└─────────────────────────────────────────────────────────────────────┘
```

## Why this shape

### Why Tauri (not Electron)

- Bundle size ~10MB (vs ~100MB+ for Electron).
- Rust core matches the existing Web4 crate ecosystem (web4-core, web4-trust-core both Rust).
- WebView2/WKWebView for the UI is plenty for an inspection dashboard — we're not rendering anything fancy.
- Tauri 2.x is mature on Linux + macOS + Windows.
- Memory footprint target (<200MB resident) is achievable in Tauri; harder in Electron.

### Why MCP as the plugin protocol

- Every major agent client now speaks MCP: Claude Code, Cursor, Cline, ChatGPT desktop, Codex, OpenClaw, ruflo. Anthropic standardized it; OpenAI adopted it; most other clients implemented it through 2025-2026.
- We don't have to invent a protocol or convince anyone to support a custom one.
- Non-MCP clients (Ollama, LM Studio, Jan, Msty) need a shim — but only one per client, and the shim is a thin REST proxy.

### Why local-only by default

- The moment we host data on a server, we become a target and a liability.
- Local-first means we're an empowerment tool, not a custodian.
- The premium cloud-backup tier uses **envelope encryption** — encrypted client-side, the storage provider sees only ciphertext. We never hold the user's keys.

### Why plugins as thin observers (not self-contained governance)

This is the architectural shift from the three existing Web4 governance plugins:

**Today (each plugin):** Plugin runs inside an agent client. Plugin has its own R6 chain, its own Soft LCT, its own policy engine, its own ledger. Each agent client has a fully self-contained Web4 governance system. Net result: N independent trust states for N plugged-in agents.

**With Hestia:** Plugin still runs inside the agent client, but the heavy state moves OUT of the plugin and INTO Hestia. The plugin's job shrinks to:

1. Hook into the agent's tool-call lifecycle.
2. Use the Hestia Plugin SDK to build an R6/R7 record for each tool call.
3. Emit the record to Hestia over MCP.
4. (Optional) Query Hestia for a policy decision; honor it.
5. (Optional) Request scoped credentials from Hestia's vault when needed.

The user has **one trust state across all their agents.** Cross-agent reputation becomes possible (Claude Code's outcomes feed the same T3/V3 that OpenClaw and ruflo write to). Policy decisions become user-level.

This is a clean upstream-acceptable refactor for the existing plugins: strip the embedded governance code → it goes to Hestia; replace with thin SDK calls → emit events, query policy. The plugin's footprint shrinks dramatically. Each plugin can claim "minimal-impact integration" to upstream maintainers — much more likely to be merged.

## The core types (Phase 0 sketch, subject to refinement)

These are the load-bearing types Hestia core exposes via MCP. The Plugin Authoring Kit gives ergonomic wrappers around them.

### R6 record (the structured action format)

```rust
pub struct R6Record {
    pub rules: RulesRef,        // hash of the policy in force
    pub role: RoleRef,          // calling agent's role + LCT
    pub request: ToolRequest,   // the tool call: what, target, params, nonce
    pub reference: Reference,   // MRH depth, precedent records, witnesses
    pub resource: ResourceCost, // required ATP, available ATP, compute
    pub result: Option<Outcome>,// filled in post-execution; success/failure/abandoned + magnitude
}
```

R7 = R6 with an explicit reputation back-propagation (consequential action).

### Soft LCT (session identity)

```rust
pub struct SoftLct {
    pub session_id: Uuid,
    pub agent_id: Uuid,         // which plugged-in client
    pub bound_at: DateTime<Utc>,
    pub ephemeral_keypair: Ed25519KeyPair,
    pub witnessed_by: Vec<LctRef>,  // the user's society LCT(s) that witnessed this session start
}
```

Soft because no hardware binding (premium tier upgrades to hard LCT with TPM/YubiKey).

### Witness chain entry

```rust
pub struct WitnessEntry {
    pub prev_hash: [u8; 32],
    pub timestamp: DateTime<Utc>,
    pub event: WitnessEvent,    // r6_record / credential_access / policy_decision / etc.
    pub signer_lct: LctRef,
    pub signature: Ed25519Signature,
}
```

Hash-chained, append-only, persisted in the society's ledger.

### Society state

```rust
pub struct Society {
    pub sovereign_lct: LctRef,           // the user
    pub roles: HashMap<LctRef, SocietyRole>, // 7 base-mandatory + custom
    pub members: HashMap<LctRef, RoleAssignment>,
    pub trust_states: HashMap<LctRef, TrustState>,  // T3/V3 per agent
    pub witness_chain: Vec<WitnessEntry>,
    pub treasury: AtpAccount,
    pub charter_hash: [u8; 32],
}
```

Uses `web4_trust_core::Society` directly (already implemented).

### Vault entry

```rust
pub struct VaultEntry {
    pub name: String,
    pub scope: Vec<String>,       // "publish", "infer", "billing", etc.
    pub tags: Vec<String>,        // user-applied
    pub secret: EncryptedSecret,  // ChaCha20-Poly1305 with key from Argon2id(user passphrase)
    pub created_at: DateTime<Utc>,
    pub last_rotated: Option<DateTime<Utc>>,
    pub allowed_consumers: Vec<AgentId>,  // which plugins can request this
}
```

## MCP surface (what Hestia exposes to plugged-in agents)

### Resources

| URI | Description |
|---|---|
| `hestia://vault/{name}` | Read a credential by name (gated by `allowed_consumers`) |
| `hestia://society/state` | Read society state (members, roles, trust scores) |
| `hestia://society/trust/{agent_id}` | Read trust state for a specific agent |
| `hestia://witness/recent` | Read recent witness events |
| `hestia://context/shared` | The user's optional cross-agent shared context |

### Tools

| Tool | Description |
|---|---|
| `hestia_vault_get(name, scope)` | Request a credential; may prompt user for approval |
| `hestia_vault_set(name, scope, value)` | Store a new credential; always requires user approval |
| `hestia_record_outcome(r6_id, outcome, magnitude)` | Submit an R6/R7 outcome record |
| `hestia_request_witness(event)` | Add a witness chain entry |
| `hestia_query_policy(action, context)` | Query: allow / deny / warn |
| `hestia_query_history(filter)` | Read prior actions from the witness chain |

### Prompts

| Prompt | Description |
|---|---|
| `hestia_first_run` | Onboarding wizard for new users |
| `hestia_recipe_template` | Generate a recipe (set of agent + roles + initial credentials) |
| `hestia_federation_handshake` | (Phase 4) Initiate federation with another society |

## Cryptography

Phase 0 baseline. Premium tier upgrades to hardware-bound key material.

| Need | Algorithm | Rationale |
|---|---|---|
| Key derivation from passphrase | **Argon2id** (m=64MB, t=3, p=4) | Modern memory-hard KDF; OWASP recommended |
| Symmetric encryption (vault entries) | **ChaCha20-Poly1305** (AEAD) | Fast, side-channel-resistant; libsodium / RustCrypto |
| Asymmetric signing (LCTs, witness chain) | **Ed25519** | Matches Web4 spec; matches MAGT's choice; matches existing web4-core |
| Hash chain | **SHA-256** | Standard; matches existing plugins |
| Random | OS CSPRNG via `getrandom` | Trivial; never hand-rolled |

Premium tier:
- TPM 2.0 binding wraps the Argon2id-derived key, so unlock requires TPM presence
- YubiKey 5+ can be a second factor or sole unlock factor (FIDO2 / HMAC challenge-response)
- Shamir secret sharing for recovery: split a recovery secret across N trusted contacts; threshold K reconstructs it

## Plugin model — see PLUGIN_AUTHORING_GUIDE.md

The Plugin Authoring Kit (PAK) is the load-bearing deliverable. The PAK extracts the shared pattern from three independent existing Web4 governance plugins into a publishable SDK:

```
@hestia/plugin-sdk      (npm)        TypeScript reference
hestia-plugin-sdk       (PyPI)        Python parity
hestia-plugin-sdk       (crates.io)   Rust parity
```

See [PLUGIN_AUTHORING_GUIDE.md](PLUGIN_AUTHORING_GUIDE.md) for the contract a plugin author satisfies.

## Open questions (Phase 0 deliverables)

These need concrete answers before Phase 1 implementation starts.

1. **Vault file format.** Single encrypted blob? Per-entry encrypted file? SQLite + envelope-encrypted column? Tradeoff: simplicity vs partial-update / corruption resistance.
2. **Import format adapters.** Each tool's credential file is different (`.pypirc` INI, `.cargo/credentials.toml` TOML, `.npmrc` flat KV, `.env` shell-ish). Define parsers and a canonical internal representation.
3. **MCP server transport.** stdio (per-client process) or single shared HTTP server on localhost (multiple clients reuse)? HTTP is more flexible; stdio is more secure (per-process isolation).
4. **Per-credential approval flow.** "Always allow this plugin to read this credential" vs "ask each time" vs "ask once per session" — UX design decision.
5. **Society state ↔ plugin authentication.** How does Hestia know which plugin is asking for what? Initial: per-plugin install token at registration time; revisit if real adversarial scenarios emerge.
6. **Witness chain persistence.** Append-only file vs SQLite vs custom format. SQLite probably wins for queryability.

These get answered in Phase 0 ADRs (in `docs/DESIGN_DECISIONS/`).

## Non-functional targets

| Property | Target |
|---|---|
| Cold start | < 2 seconds |
| Resident memory | < 200 MB |
| First-run-to-first-credential-imported | < 5 minutes |
| Vault lookup (cached) | < 10 ms |
| MCP response 90th percentile | < 50 ms |
| Cross-platform | Linux (Ubuntu 22.04+, Fedora 38+, Arch), macOS 12+, Windows 10/11 |
| Offline-capable | Full functionality without internet (cloud backup excepted) |
| Telemetry | Opt-in only; never includes credential names or contents |
