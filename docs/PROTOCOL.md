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
