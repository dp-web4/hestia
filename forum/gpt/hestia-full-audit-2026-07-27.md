# Hestia Full Architecture and Security Audit

**Repository:** `dp-web4/hestia`  
**Branch:** `main`  
**Pinned commit:** `83b07f2904e8c85860dc969993a21f241bc6bdb6`  
**Audit date:** 2026-07-27  
**Method:** Source-level review of the current GitHub repository, architecture/PRD comparison, trust-boundary tracing, and compositional attack analysis.

## Executive assessment

Hestia has evolved into a substantial local trust runtime rather than the small MCP vault suggested by its earliest architecture document. Its conceptual architecture is strong: a locally sovereign encrypted vault, layered policy, an append-only evidence plane, operator authentication, role-scoped trust, hub relationships, paired channels, and agent adapters form a coherent system.

The implementation, however, currently has a contradiction at its center:

> Hestia is designed to govern partially trusted agents, but its most sensitive daemon surfaces and secrets still rely on those agents being benign processes under the same local user account.

That contradiction produces three release-blocking classes of compromise:

1. **The unauthenticated MCP plane can disclose and overwrite vault credentials under ordinary defaults.**
2. **The optional sovereign callback is an unauthenticated signing oracle for most approved event kinds.**
3. **The service passphrase is placed in the daemon environment and inherited by a helper executable selected from user-writable paths.**

The codebase deserves credit for unusually honest internal documentation: the current PRD already names several of the vault, issuance, session, and app-contract gaps. The remaining danger is compositional. Controls that look defensible in isolation share an unauthenticated MCP plane, caller-asserted identity, bearer session IDs, and a same-UID process boundary. Combined, those seams defeat stronger cryptography and policy elsewhere.

### Overall rating

- **Architecture:** strong concept, rapidly maturing implementation
- **Cryptography primitives:** generally sound choices and reuse
- **Authorization model:** incomplete at the plugin/MCP boundary
- **Local isolation:** insufficient for the actual adversary model
- **Evidence integrity:** useful but not yet independently trustworthy
- **Release readiness:** **not ready for security-sensitive credential or sovereign-signing use without immediate containment**

## Scope and limitations

The audit is anchored to the commit above. The local execution environment could not reach GitHub to obtain a complete byte-for-byte checkout, so I could not run `cargo test`, `cargo clippy`, `cargo audit`, frontend builds, or live exploit probes. The repository also depends on sibling `web4` path dependencies, which makes an isolated Hestia build incomplete by design. Findings below are therefore static-source findings, not claims that the current test suite passes or fails.

## Architecture as implemented

### 1. Sovereign local state

The daemon unlocks a passphrase-encrypted vault containing credentials, policy, protected documents, policy lists, and gate expectations. The same passphrase derives a stable storage key for the SQLCipher witness/inbox databases and sealed trust files.

### 2. Policy and governance plane

Actions are evaluated through a strictest-wins fold of:

- machine-local base policy,
- role policy,
- per-instance/role policy,
- optional hub law.

Agent adapters add another layer of host-specific scope and egress checking before delegating consequential actions to the daemon policy gate.

### 3. Plugin/MCP plane

The daemon exposes a stateful MCP Streamable HTTP service at `/mcp`. Plugins can connect, create sessions, begin actions, ask for policy decisions, record outcomes, query history, request credentials, write credentials, communicate with peers, and contribute evidence.

This plane is the largest unresolved trust boundary. The current transport does not authenticate the connecting process. `plugin_id`, host agent, role, and host session identifiers are supplied by the caller.

### 4. Operator plane

The dashboard/API plane is protected by an Ed25519 challenge-response flow. A successful challenge produces an opaque one-hour bearer token. The desktop shell keeps the private key and bearer token outside the webview, which is a good boundary.

### 5. Evidence and trust plane

Events are appended to a SQLCipher-backed hash-linked chain. Trust state is maintained per instance/role and bridged toward hub reputation. The chain is tamper-evident relative to a trusted head, but entries are not yet cryptographically signed and the head is not externally anchored.

### 6. Hub and constellation plane

Hub operations use challenge-response signed envelopes. Pair channels correctly reuse shared Web4 cryptographic primitives, combining static and ephemeral keys for authenticated, forward-secret channels. Pairing secrets are vault-sealed at rest.

### 7. Desktop application

A Tauri shell provides the human/operator surface. Sensitive operator material stays in Rust state, while the webview invokes narrow commands. The app can also target configurable remote daemon/dashboard URLs.

## Severity summary

| ID | Severity | Finding |
|---|---|---|
| HST-001 | Critical | Unauthenticated MCP credential disclosure and overwrite |
| HST-002 | Critical | Sovereign callback is an unauthenticated signing oracle |
| HST-003 | Critical | Daemon passphrase inherited by user-writable helper executable |
| HST-004 | High | Legacy plaintext trust fallback permits trust-state forgery |
| HST-005 | High | Plugin identity and session capabilities are caller-asserted/bearer-only |
| HST-006 | High | Operator client signs arbitrary remote challenges without origin binding |
| HST-007 | High | Non-loopback bind exposes plaintext MCP/operator/callback surfaces |
| HST-008 | High | Witness chain is unsigned, unanchored, and writes often fail open |
| HST-009 | High | Same-UID agents can read operator/bootstrap and channel key material |
| HST-010 | High | Vault persistence lacks interprocess serialization and durable atomicity |
| HST-011 | Medium | Absent hub-law file silently removes the third policy input |
| HST-012 | Medium | Empty delegation scope means unrestricted authority |
| HST-013 | Medium | Secret-bearing types are cloneable/debuggable and not zeroized |
| HST-014 | Medium | Operator stakes classification is route-string based; dev override defaults unsafe |
| HST-015 | Medium | Request limits, timeouts, and rate limits are incomplete |
| HST-016 | Medium | Desktop remote fetches create SSRF/origin and availability risk |
| HST-017 | Medium | Build/release pipeline is not self-contained or security-gated |
| HST-018 | Medium | Windows release appears blocked by unconditional Unix API use |
| HST-019 | Medium | Global mutable state lock and handler monolith amplify failure coupling |
| HST-020 | Medium | Documentation and product-version state have drifted |

---

## Detailed findings

## HST-001 — Unauthenticated MCP credential disclosure and overwrite

**Severity: Critical**

### Evidence

- `/mcp` is mounted outside the operator-authenticated router.
- `hestia_connect` accepts caller-provided `plugin_id`, host identity, and role without transport authentication.
- `hestia_vault_get` uses the default policy gate, then returns the secret.
- The default `safety` policy is allow-by-default and only blocks credential targets matching secret-like path patterns.
- `VaultEntry` documents empty `allowed_consumers` as “nobody,” but the handler enforces the list only when it is non-empty.
- Empty credential scope matches every requested scope.
- `hestia_query_history` is callable on the same MCP plane and returns event data, including recent `vault_set` credential names.
- `hestia_vault_set` can overwrite credentials through the same unauthenticated plane.

### Practical attack chain

A local process can:

1. Initialize an MCP connection.
2. Query recent history to discover credential names.
3. Request a credential with no session ID when its consumer list is empty; or connect under an allowed plugin name and use the resulting session ID.
4. Replace an existing credential using `hestia_vault_set`.

This is not defeated by encryption at rest: the attacker asks the already-unlocked daemon to decrypt or mutate the data.

### Impact

- API-key and credential theft
- Credential substitution and durable persistence
- Supply-chain compromise through replaced publish/deploy tokens
- False attribution to a spoofed plugin identity

### Required fix

- Immediately disable `hestia_vault_get` and `hestia_vault_set` on unauthenticated MCP transports.
- Make empty consumer and scope states explicit typed values, not overloaded empty vectors.
- Bind every MCP call to server-established authenticated transport identity; never accept `session_id` as an authority-bearing argument.
- Separate owner custody reads from plugin releases.
- Add a migration for existing empty-list entries; do not silently reinterpret them.
- Make credential names non-enumerable to unentitled callers and witness successful releases.

**Primary anchors:**
- `core/src/server/http.rs:222-281`
- `core/src/server/handler.rs` (`tool_connect`, `tool_vault_get`, `tool_vault_set`, `tool_query_history`)
- `core/src/vault/entry.rs:28-29,67-80`
- `core/src/policy/presets.rs:191-247`

## HST-002 — Sovereign callback is an unauthenticated signing oracle

**Severity: Critical**

### Evidence

When callback mode is enabled, `/callback` accepts a caller-supplied intent and arbitrary `signing_bytes_hex`. It approves requests based on an event-kind allowlist. Only `oid4vci_credential` binds the supplied bytes to the human-readable intent. For `genesis`, `member_added`, `role_assigned`, `member_skill_declared`, and `law_amended`, the handler signs the exact bytes supplied by the caller.

There is no hub authentication, signed request envelope, mTLS, nonce replay protection, audience binding, or per-hub authorization on this route.

### Impact

- Chosen-message signatures under the sovereign key
- Forged governance events if another protocol accepts those signatures
- Cross-protocol signature reuse
- Unreviewed law/member/role acts attributed to the sovereign

### Required fix

- Disable callback mode until the route is authenticated.
- Authenticate the hub with a pinned LCT key and a signed, nonce-bound request envelope.
- Sign a domain-separated canonical transcript, not arbitrary caller bytes.
- Verify that the transcript commits to event kind, hub identity, actor, ledger position, payload hash, expiration, and nonce.
- Maintain per-hub authorization and replay state.
- Require explicit policy evaluation for every event kind; an event-kind allowlist is not authorization.

**Primary anchors:** `core/src/callback.rs:30-50,74-107,158-239`; `core/src/server/http.rs:283-286`.

## HST-003 — Passphrase inherited by a user-writable helper

**Severity: Critical**

### Evidence

The systemd user unit reads `~/.hestia/.passphrase` and places it in `HESTIA_PASSPHRASE` for the daemon process. The agent-inventory dashboard path chooses an executable from:

- `~/.local/bin/hestia-agent-inventory`, or
- `$HESTIA_WORKSPACE/hestia/plugins/agent-inventory/inventory.py`.

Both are ordinarily writable by the same local user as governed agents. `Command::new(...).output()` inherits the daemon environment by default. Therefore, replacing that helper causes the daemon to execute attacker-controlled code with the unlocked vault passphrase in its environment.

### Impact

Full offline compromise of:

- vault credentials and policy,
- trust state,
- SQLCipher witness and inbox databases,
- protected documents and pairing state.

### Required fix

- Remove the passphrase from the daemon environment entirely.
- Use an inherited file descriptor, systemd credential, OS keyring, TPM unsealing, or another non-environment secret channel.
- Execute only package-owned, integrity-pinned helpers.
- Use `env_clear()` and explicitly add a minimal environment for every helper.
- Run helpers under a less-privileged separate UID or sandbox.
- Prefer an in-process library or a narrow authenticated IPC service for inventory.

**Primary anchors:** `deploy/templates/hestia.service:76-93`; `core/src/server/agents.rs:31-42,49-84`.

## HST-004 — Trust-state forgery through plaintext fallback

**Severity: High**

### Evidence

Trust files are normally AEAD-sealed. On any decryption/authentication failure, however, the loader treats the raw bytes as legacy plaintext JSON. The filename is a deterministic truncated hash of the entity ID.

A same-UID attacker can replace a sealed trust blob with valid plaintext `EntityTrust` JSON. AEAD authentication fails, the fallback accepts the plaintext, and the forged trust state becomes authoritative.

### Required fix

- Remove opportunistic plaintext fallback from normal reads.
- Perform migration only from a positively identified legacy format/location.
- Ratchet a persistent “sealed-format required” version after migration.
- Make migration one-shot, atomic, backed up, and witnessed.
- Authenticate metadata including entity ID and format version as AEAD associated data.

**Primary anchor:** `core/src/storage/trust.rs:52-94,153-184`.

## HST-005 — Caller-asserted plugin identity and bearer session capabilities

**Severity: High**

### Evidence

`hestia_connect` mints a session from caller-supplied identity fields. `host_session_id` reuse searches globally and returns the existing session ID and soft LCT without requiring that the reconnecting caller match the original plugin or host agent. Direct tools accept the session UUID in their JSON arguments.

The recent `resolve_plugin_id` fail-closed change correctly removed the “latest connected session” fallback, but it does not make the session authenticated or transport-bound.

### Impact

- Identity spoofing
- Session theft after identifier disclosure/collision
- Reputation poisoning under another member’s name
- Vault entitlement bypass where plugin names are used as principals

### Required fix

- Attest connect using a per-plugin key/capability, Unix-domain peer credentials, mTLS, or a launcher-provisioned one-time token.
- Store caller identity in the transport/session context; tool handlers must not accept identity or session as authority-bearing arguments.
- Scope reconnect keys to `(authenticated principal, host agent, host session)`.
- Never return an existing session capability to a newly unauthenticated connection.
- Quarantine local reputation from fleet reputation until identity is attested.

**Primary anchors:** `core/src/server/handler.rs` (`tool_connect`); `core/src/server/state.rs` (`resolve_plugin_id`, `issue_soft_lct`, `member_lct`).

## HST-006 — Operator app is a chosen-message signing oracle

**Severity: High**

### Evidence

The desktop app accepts a configurable HTTP(S) daemon URL. During authentication it downloads a challenge from that URL, signs the raw challenge bytes with the operator Ed25519 key, and returns the signature to the same endpoint. The signature does not commit to Hestia protocol version, daemon origin, server identity, action, or expiration.

A malicious or mistyped remote URL can obtain operator signatures over chosen bytes.

### Required fix

Sign a transcript such as:

`HestiaOperatorAuthV1 || canonical_origin || server_instance_lct || challenge || issued_at || expires_at`

Also:

- refuse redirects during authentication,
- default to loopback only,
- require pinned TLS/server identity for remote endpoints,
- show an explicit origin-trust prompt,
- add request timeouts and body limits.

**Primary anchors:** `app/src-tauri/src/operator.rs:94-154`; app settings daemon URL validation.

## HST-007 — Remote bind exposes plaintext sensitive surfaces

**Severity: High**

### Evidence

The default bind is loopback, but the CLI/server accepts any `SocketAddr` and does not enforce loopback or TLS. The same listener can expose:

- unauthenticated MCP,
- operator bearer-token APIs over HTTP,
- optional callback signing,
- dashboard shell and OID4VCI discovery.

### Required fix

- Refuse non-loopback binding by default.
- Require an explicit unsafe development flag for plaintext remote bind.
- For supported remote operation, use TLS with pinned server identity and authenticated clients.
- Split MCP, operator, and callback onto separate listeners and policies.

**Primary anchor:** `core/src/server/http.rs:32,189-220,264-291`.

## HST-008 — Evidence is not yet independently trustworthy

**Severity: High**

### Evidence

The witness chain hashes `prev_hash`, timestamp, event type, and JSON data, but the entry contains only a `signer_lct` string; it does not carry a signature. The append implementation explicitly notes future signing. A holder of the database key can rewrite the entire chain and recompute hashes unless a trusted head is anchored elsewhere.

Additionally, many consequential paths use `let _ = append_chain(...)`, allowing the governed act to succeed when evidence persistence fails.

### Impact

- Whole-history rewrite after local compromise
- Acts without evidence despite “self-witnessing” claims
- Divergence between state and audit record

### Required fix

- Sign every entry or signed checkpoint with the sovereign key.
- Anchor heads externally to a hub, witness quorum, or transparency service.
- Verify the chain and signatures at startup and on export.
- Make state mutation and evidence append atomic through a transaction/outbox.
- Treat evidence-write failure as failure or explicit quarantined/pending state for consequential acts.

**Primary anchors:** `core/src/storage/chain.rs:3-8,18-29,147-200`; `core/src/server/http.rs` and `handler.rs` ignored append results.

## HST-009 — Same-UID key custody is not an agent boundary

**Severity: High**

### Evidence

Genesis writes `operator.key` as a plaintext Ed25519 seed with mode `0600`. Channel-key files and the passphrase file use the same owner-only model. That protects against other operating-system users, not agents running as the same user.

The operator key is also written before the public policy is persisted, creating a crash window and non-atomic bootstrap state.

### Required fix

- Put operator keys in OS keystore/TPM/hardware-backed storage.
- Run governed agents under distinct UIDs or containers.
- Use atomic `O_EXCL`, mode-at-create, fsync-file, fsync-directory bootstrap.
- Design explicit operator-key rotation and recovery.

**Primary anchor:** `core/src/server/state.rs:67-128`.

## HST-010 — Vault persistence and concurrency weaknesses

**Severity: High**

### Evidence

The entire vault is serialized as plaintext JSON in memory, encrypted, and written via a fixed `.enc.tmp` path followed by rename. There is no visible interprocess lock or compare-and-swap version. CLI and daemon writers can therefore race and lose updates. The temporary path is not opened with `create_new`/nofollow, directory metadata is not fsynced after rename, and permissions are tightened only after replacement.

The vault is also a single failure domain for credentials, policy, protected documents, policy lists, and gate expectations.

### Required fix

- Introduce a process-wide/interprocess write lock and monotonic revision/CAS.
- Use a unique same-directory temporary file opened atomically with mode `0600` and no symlink following.
- fsync the file and containing directory.
- Keep encrypted backups or a journal with tested recovery.
- Domain-separate per-store keys through HKDF.
- Zeroize passphrases and plaintext buffers.

**Primary anchors:** `core/src/vault/storage.rs:136-178`; `core/src/vault/mod.rs:28-43,95-120`.

## HST-011 — Hub law can be removed rather than corrupted

**Severity: Medium**

An invalid present hub-law file fails closed, which is good. An absent file, however, means “no third input.” Once a device has enrolled under hub law, a same-UID attacker can delete the file and silently weaken policy.

### Fix

Persist the expected law identity/hash in protected vault state. After enrollment, absence or rollback must fail closed. Updates should be signed, atomic, monotonic, and witnessed.

**Primary anchor:** `core/src/policy/law_gate.rs:21-27,53-81`.

## HST-012 — Empty delegation means unrestricted

**Severity: Medium**

Creating a delegation with no roles and no actions maps to `DelegationScope::unrestricted()`. This repeats the security-significant empty/default ambiguity already identified in the PRD.

### Fix

Make unrestricted scope an explicit enum variant or required CLI/API flag, with stronger authorization. Empty input should be rejected or mean no authority.

**Primary anchor:** `core/src/delegation.rs:33-50`.

## HST-013 — Secret-bearing values leak through ordinary Rust traits

**Severity: Medium**

Examples include:

- `VaultEntry` deriving `Debug, Clone` while containing `secret: String`;
- `OperatorKeyFile` and `OperatorSession` deriving `Debug, Clone` while containing key/token material;
- `Pairing` and `SecretEnvelope` deriving `Debug, Clone` while containing ephemeral secrets or secret hex;
- removal from collections without explicit zeroization.

### Fix

Use secrecy/zeroizing wrappers, redacted `Debug`, minimal cloning, and zeroize-on-drop. Keep key material in bounded byte arrays rather than long-lived strings.

## HST-014 — Operator classification and dev override are configuration-brittle

**Severity: Medium**

Stakes are inferred from HTTP method and path strings. Unknown GETs default low. The developer bearer override is allowed unless `HESTIA_PROFILE` is exactly `production`; an unset or misspelled profile is treated as non-production.

### Fix

Attach stakes metadata directly to route definitions/typed commands. Deny unknown routes. Enable the development override only when an explicit development build and explicit unsafe flag are both present.

**Primary anchors:** `core/src/server/operator_auth.rs:171-210`; `core/src/server/http.rs:99-186`.

## HST-015 — Request hardening is incomplete

**Severity: Medium**

The top-level Axum router does not visibly apply global body-size, request timeout, concurrency, or rate-limit layers. Several handlers accept caller strings/JSON with only local ad hoc limits. Challenge/session maps rely on opportunistic cleanup.

### Fix

Add global and per-route limits, connection/request timeouts, concurrency caps, rate limits, strict schemas, and bounded identifiers/values. Run fuzz/property tests against MCP and HTTP parsers.

## HST-016 — Desktop remote fetches create SSRF and availability risk

**Severity: Medium**

The Tauri shell fetches an arbitrary remote dashboard URL and appends `/api/dashboard`. It does not visibly restrict loopback/private metadata destinations, enforce response status/size, or set a timeout. The daemon client similarly creates a new HTTP client per request without a configured timeout.

### Fix

Use a shared hardened client, URL parser, allowlist/pinning, redirect policy, private-address policy, timeouts, and response-size caps. Treat remote endpoints as explicit trust relationships rather than free-form strings.

**Primary anchors:** `app/src-tauri/src/commands/remote.rs:32-48`; `app/src-tauri/src/daemon.rs:39-114`.

## HST-017 — Build and release are not self-contained or security-gated

**Severity: Medium**

- `core/Cargo.toml` depends on sibling `../../web4/...` paths.
- The release workflow checks out only Hestia and immediately builds `core`, so a clean hosted runner lacks those dependencies unless another unshown mechanism supplies them.
- Release builds do not visibly run tests, formatting, clippy, dependency audit, live app contract tests, or security probes first.
- Workflow actions are referenced by mutable tags, not immutable SHAs.
- Artifacts are checksumed inconsistently and are not signed; no SBOM/provenance is emitted.
- The app’s live operator tests are ignored and not run by CI, as the PRD itself notes.

### Fix

Make the source graph reproducible through a workspace/monorepo or pinned git/crate dependencies. Add mandatory test/check/clippy/fmt/audit/deny, live daemon/app contract tests, action SHA pinning, artifact signing, SBOM, and provenance.

**Primary anchors:** `core/Cargo.toml:70-83`; `.github/workflows/release.yml`; `docs/PRD.md` app-contract section.

## HST-018 — Windows release appears to have a compile blocker

**Severity: Medium**

`bootstrap_operator_if_genesis` unconditionally imports `std::os::unix::fs::PermissionsExt`, while the release matrix includes Windows. Unless this code is excluded through a build configuration not visible at the function, the Windows target cannot compile.

### Fix

Use `#[cfg(unix)]` for Unix permission handling and an explicit Windows ACL implementation. Make every advertised release target a required CI compile/test target.

**Primary anchors:** `core/src/server/state.rs:67-99`; `.github/workflows/release.yml:31-47`.

## HST-019 — Global state lock and handler monolith

**Severity: Medium**

The server wraps all mutable state in `Arc<tokio::Mutex<ServerState>>`. Many handlers hold the lock while performing database, filesystem, crypto, and policy operations. `handler.rs` contains a very large number of unrelated tools and incident-specific logic.

### Risks

- head-of-line blocking,
- future lock-order/deadlock problems,
- difficult atomicity reasoning,
- broad regression blast radius,
- security review fatigue.

### Fix

Split typed services (identity/session, vault release, evidence, policy, messaging), use immutable policy snapshots and per-store synchronization, and route all consequential commands through a common authenticated command pipeline.

## HST-020 — Documentation and product state drift

**Severity: Medium**

`ARCHITECTURE.md` still frames unresolved Phase-0 questions while the implementation now contains a much larger runtime. Core is version `0.0.3`; app/Tauri reports `0.2.0`. Status claims are spread among README, PRD, incident comments, and code.

### Fix

Generate a release manifest containing component versions, schema versions, protocol versions, feature flags, and security posture. Maintain an architecture decision record for each trust boundary and derive status tables from tests rather than prose.

---

## Positive findings

The audit found meaningful strengths worth preserving:

1. **Cryptographic primitives are generally appropriate.** Argon2id, ChaCha20-Poly1305, SQLCipher, Ed25519, and shared Web4 pair-channel primitives are sensible choices.
2. **The operator challenge is random, single-use, and TTL-bounded.** The desktop app keeps the operator secret and bearer token outside the webview.
3. **The latest session resolver fix is fail-closed.** Removing the most-recent-session ambient-authority fallback was correct.
4. **OID4VCI credential issuance was moved behind the operator gate.** This closes the previously documented unauthenticated owner-signing route.
5. **Invalid hub law fails closed.** The remaining weakness is absence/rollback, not parse failure.
6. **Pair-channel crypto is reused rather than reimplemented.** Static plus ephemeral keys and AEAD failure behavior are tested.
7. **Policy composition is conservative.** Base, role, instance, and hub-law decisions fold strictest-wins.
8. **The codebase records its own mistakes.** The PRD and source comments contain unusually useful incident history and do not pretend known gaps are solved.

## Architecture gaps, by boundary

### Agent to daemon

Current: unauthenticated HTTP/MCP, caller-asserted identity, bearer UUID in payload.  
Required: authenticated transport identity, server-side context, per-principal capabilities, replay protection.

### Agent to operating system

Current: same Unix user, string-parsed hook gates, writable helpers and configuration.  
Required: separate UID/container, kernel-enforced filesystem/network scope, read confinement, immutable gate/runtime distribution.

### Daemon to helper

Current: direct execution of user-writable path with inherited environment.  
Required: package-owned helper, clean environment, sandbox, signed/hash-pinned binary, narrow IPC.

### Operator to daemon

Current: good local challenge flow, but raw challenge lacks origin binding and remote URL is configurable.  
Required: domain-separated origin-bound transcript, pinned server identity/TLS, explicit remote trust.

### Daemon to evidence

Current: local encrypted hash chain, unsigned and often best-effort.  
Required: signed atomic evidence plus external anchoring.

### Daemon to hub

Current: signed hub envelopes and sealed channels are comparatively strong.  
Required: equally strong authentication for callbacks and law distribution.

## Immediate containment plan

### Within 24 hours

1. Remove or hard-deny MCP `vault_get` and `vault_set` in production builds.
2. Disable callback mode.
3. Enforce loopback bind.
4. Stop placing `HESTIA_PASSPHRASE` in the daemon environment.
5. Disable daemon execution of the inventory helper until environment clearing and integrity pinning land.
6. Add a release-blocking regression test proving an unauthenticated MCP client cannot read or write any credential.

### Within one week

1. Implement authenticated MCP connect and transport-bound sessions.
2. Migrate credential release rules to explicit typed semantics.
3. Remove trust plaintext fallback after a one-shot migration.
4. Make witness append atomic with consequential state changes.
5. Domain-separate operator authentication and pin remote daemon identities.
6. Protect enrolled hub-law presence/hash against deletion and rollback.
7. Add global request limits/timeouts/rate limits.

### Within one month

1. Separate agent and daemon OS identities or deploy agents in containers.
2. Hardware/OS-keystore operator and sovereign keys.
3. Signed witness entries/checkpoints with external anchoring.
4. Rework vault persistence around revisions, locking, recovery, and key separation.
5. Make releases reproducible, signed, tested, and provenance-bearing.
6. Split the server into typed authenticated command services.

## Proposed release gates

A release should fail unless all of the following pass:

- unauthenticated MCP cannot obtain, alter, enumerate, or infer credentials;
- identity cannot be selected by caller-provided plugin/session strings;
- callback refuses unsigned/unpinned hub requests and never signs unbound bytes;
- non-loopback bind without TLS/client auth is rejected;
- no child process inherits vault/operator/sovereign secrets;
- trust ciphertext corruption cannot become accepted plaintext state;
- every consequential mutation has exactly one durable evidence record or does not commit;
- full chain verification passes from genesis to anchored head;
- app live contract tests run against a fresh daemon in CI;
- Linux, macOS, Windows, and aarch64 targets compile from a clean checkout;
- dependency audit, clippy, formatting, tests, fuzz corpus, and policy regression suite pass;
- release artifacts are signed and include SBOM/provenance.

## Final judgment

Hestia is architecturally valuable and substantially more sophisticated than its early version number suggests. The strongest parts—the policy fold, explicit evidence model, operator challenge, pair-channel reuse, and candid internal review culture—are the right foundations.

The current security posture is nevertheless dominated by one unresolved premise: **localhost and same-UID execution are treated as adequate authentication and isolation for components Hestia explicitly exists to govern.** They are not. Until the plugin transport and operating-system boundary become real trust boundaries, the vault, witness chain, trust tensor, and sovereign key remain reachable through compositional seams around their cryptography.

The priority is therefore not more policy sophistication. It is to make **WHO** non-forgeable and make **WHERE CODE RUNS** enforceable. Once those two boundaries are structural, much of the existing Hestia architecture becomes genuinely load-bearing rather than advisory.
