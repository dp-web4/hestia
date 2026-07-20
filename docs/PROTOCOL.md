# Hestia Protocol — Pointer

The Hestia daemon implements the **Web4 Presence Protocol**, which
is canonically specified outside this repo:

- **Spec**: [`web4/web4-standard/core-spec/presence-protocol.md`](https://github.com/dp-web4/web4/blob/main/web4-standard/core-spec/presence-protocol.md)
- **Changelog**: [`web4/web4-standard/core-spec/presence-protocol-CHANGELOG.md`](https://github.com/dp-web4/web4/blob/main/web4-standard/core-spec/presence-protocol-CHANGELOG.md)
- **Schemas**: [`web4/web4-standard/schemas/presence-protocol/`](https://github.com/dp-web4/web4/tree/main/web4-standard/schemas/presence-protocol)
- **Conformance vectors**: [`web4/web4-standard/testing/conformance/presence-protocol-conformance.json`](https://github.com/dp-web4/web4/blob/main/web4-standard/testing/conformance/presence-protocol-conformance.json)
- **PR checklist for changes**: [`shared-context/protocol-discipline/PR_CHECKLIST.md`](https://github.com/dp-web4/shared-context/blob/main/protocol-discipline/PR_CHECKLIST.md) (private repo — Metalinxx contributors)

Hardbound (private) and Hestia (this repo) both speak this same
protocol — same wire format, same error envelope, same tool surface.
The implementations differ in how they store state (Hestia:
software-encrypted vault; Hardbound: hardware-sealed vault), not in
what they expose to an orchestrator.

## Hestia-specific surface (not in the canonical spec)

Beyond the canonical presence protocol, this daemon exposes two
extras that are **Hestia-only** — not portable to other presence
implementations:

| Endpoint | Path | What |
|---|---|---|
| Dashboard HTML | `GET /` | Embedded HTML/CSS/JS dashboard. See [DASHBOARD.md](./DASHBOARD.md). |
| Dashboard JSON | `GET /api/dashboard` | JSON snapshot consumed by both the web dashboard and the `hestia dashboard` TUI. See [DASHBOARD.md](./DASHBOARD.md). |
| Gate profile (PreToolUse clients) | — | Normative client-construction contract for adapter gate hooks (fail-open engines): [GATE_PROFILE.md](./GATE_PROFILE.md). Wire protocol itself stays presence-protocol §3.4. |

These are operator surfaces — for the user/operator to see what's
happening in their own daemon. Orchestrators (Claude Code, etc.) do
NOT use these; they use the MCP path at `/mcp`. A conforming
presence layer is NOT required to implement these.

## Connected messaging (implemented)

Two connected-presence protocols are live in this daemon. Both are the
citizen/member half of a hub-brokered exchange: the **wire format** and the
**crypto** are canonical (they live in `web4-standard` and `web4-core`); what
this section documents is how Hestia *consumes* them and the local tool surface
it exposes. Source of truth: `core/src/pairing.rs`,
`core/src/storage/inbox.rs`, `core/src/server/handler.rs`.

### Paired member↔member channels

**The hub is the authentication controller.** When it admits a pairing between
two members (hub-law gate at `pairing_requested`) it establishes a sealed
channel and hands each side the peer's ephemeral **pairing key**; the members
then negotiate any additional security layers *over that channel as transport*.
A secret is one such layer — it rides the channel as a `pair_message`, sealed
end-to-end, and the hub relays only opaque ciphertext.

**Lifecycle** (hub REST surface, each act carried in a `SignedEnvelope`):

| Step | Hub endpoint | CLI |
|---|---|---|
| Propose | `POST /v1/hubs/:id/pairs/request` | `hestia hub pair-request <peer>` |
| Confirm | `POST /v1/hubs/:id/pairs/:pair_id/confirm` | `hestia hub pair-confirm <pair_id>` |
| Send secret | `POST /v1/hubs/:id/pairs/:pair_id/messages` | `hestia hub send-secret --to <peer> [--pair <id>]` (payload from `--file`/stdin, **never** argv) |
| Poll | `GET /v1/hubs/:id/pairs/:pair_id/messages?since=<seq>` | (drained by `hestia_pair_inbox`) |
| Revoke | `POST /v1/hubs/:id/pairs/:pair_id/revoke` | `hestia hub pair-revoke <pair_id>` |
| List (local) | — | `hestia hub pair-list` |

**Key agreement (forward-secret v2).** Each side mints a per-session X25519
**ephemeral** keypair, published in `pair_request` / `pair_confirm`; the
confirmed-pair detail carries both ephemeral pubkeys. The session key is derived
by mixing **static‖ephemeral** ECDH — the peer's *static* LCT pubkey (resolved
once from the hub's pinned-pubkey endpoint, an authentication fact, not a private
roster) and the peer's *ephemeral* pubkey (from the pair detail) — and the body
is sealed with ChaCha20-Poly1305. All of this is `web4_core::pair_channel`
(`EphemeralKeyPair`, `derive_session_key_v2`, `seal_fs` / `open_fs`), so Hestia
and other conforming clients interoperate byte-for-byte. The hub witnesses only
the message's `payload_hash` — it is **content-blind**.

- **Forward secrecy.** The per-pair ephemeral *secret* is persisted
  **vault-sealed** (`presence/pairings`) so the daemon can reopen the channel
  across restarts without exposing it at rest, and is **wiped on revoke/expiry**
  — compromise of an LCT key does not retroactively decrypt past pair-sessions.
- **Fail-closed.** An unconfirmed pair (no peer ephemeral yet) refuses to
  seal/open; opening with the wrong sender static key fails closed.
- **Inner contract.** A secret is a `SecretEnvelope { kind: "secret", act_id,
  secret_hex }` — an interop contract between the two *members*, not a hub seam;
  `act_id` gives the receiver an id to ACK, `kind` routes it to the credential
  gate below.

**Pull-side drain — `hestia_pair_inbox`.** For each active pair it pulls
`messages?since=<cursor>`, opens each *peer* message as a `SecretEnvelope`, and
advances a **monotone per-pair cursor** so each secret is delivered exactly once
(the daemon's own echoed messages advance the cursor without being opened). It is
`credential_access`-gated (§7.8.2, below): an unattended caller is deferred and
the secret waits on the hub for an attended drain — nothing is released.

### Accept-and-defer (durable inbound inbox)

Canonical: mcp-protocol **§7.8** (accept-and-defer) and **§7.8.2** (deliver only
to the authenticated LCT). Hestia's implementation makes an inbound HUB→citizen
notice **crash-safe**: it is durably parked *before* the hub is ACKed, so an
ACK-then-crash can no longer lose a work item the hub believes delivered.

**`hestia_notify`** — receives an inbound sealed notice: opens the body, records
receipt in the witness chain, returns a sealed ACK. With **`defer: true`** it
instead parks the still-sealed notice in the durable inbox and ACKs *without*
returning the body (**park-before-ACK** — the durable enqueue precedes the ACK).
Opening a body is itself a `credential_access` release, so an **unattended**
caller is deferred *by law* (`deferredByLaw`), never denied-with-loss —
accept-and-defer keeps the work item either way.

**Storage — `inbox.db`.** A SQLCipher-encrypted queue beside `witness.db`,
sealed under the same stable storage key (wrong key ⇒ refused; the file is never
plaintext SQLite). Notices are stored **still channel-sealed to the member**, so
there are two independent crypto layers: SQLCipher at-rest + the end-to-end body
seal. Bodies are opened only at drain time, with the vault identity keypair. Two
persistences by doctrine: the **witness chain is the completion ledger**; the
**inbox is the durable work queue** — distinct files, distinct jobs.

**`hestia_inbox`** — the consumer side: an atomic **consume-once** drain, oldest
first. A crash before it returns rolls the transaction back, so notices survive
to the next drain (**at-least-once**, the same failure bias as the hub mailbox).
Retention: 7-day TTL and a 1000-notice cap (drop-oldest), pruned on both enqueue
and drain.

**§7.8.2 gate.** Both `hestia_inbox` and `hestia_pair_inbox` are
`credential_access`-gated, and the gate runs **before** the drain — so an
unattended drain (e.g. an autonomous timer) releases nothing and the work waits
for an attended session. This binds the ratified unattended-role
`credential_access` deny (2026-07-06) to the release path with no new rule.

## Hestia-specific vault format

The Hestia vault file format (`vault.enc`) is documented in this
repo's `core/src/vault/storage.rs` source comments. The format is:

```
[magic: "HEST"]  [version: u8]  [salt: 16B]  [nonce: 12B]  [ciphertext]
```

Hardbound's vault file is byte-compatible with Hestia's for the
serialized inner structure but is wrapped by a hardware-sealing
layer instead of the Argon2id-derived AEAD. The shape of what's
*inside* the seal is the same.

## Why the protocol lives in web4-standard

The presence protocol is part of the Web4 ontology — it's the
inward complement of the outward MCP that other societies engage
through. Hosting the spec next to the existing `mcp-protocol.md`
keeps the two surfaces discoverable side-by-side and makes the
protocol independent of any single implementation. Hestia is the
reference; Hardbound is the hardware-bound variant; future
implementations are welcome.
