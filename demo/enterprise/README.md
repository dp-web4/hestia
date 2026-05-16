# Hestia Enterprise (Hardbound) — Overview

The consumer Hestia daemon gives you a self-sovereign trust layer. The
Hardbound tier — implemented in the private `hardbound/` repo — adds
the four things that make the same daemon survive a compliance review.

This folder is the pitch and the integration map, not the code. The
code lives in `hardbound/` and reuses the same `hestia-core` crate
exposed by this repo.

## What Hardbound adds to consumer Hestia

| Property | Consumer | Enterprise (Hardbound) |
|---|---|---|
| Identity | Soft LCT, deterministic-from-passphrase | Hardware-bound LCT, anchored to TPM 2.0 / YubiKey / Secure Enclave |
| Vault keys | Argon2id from user passphrase | TPM-sealed; passphrase optionally gates unsealing |
| Chain signatures | Sovereign LCT placeholder (Phase 1) → SW Ed25519 (Phase 2) | TPM-attested signatures over each entry |
| Audit trail | Hash-linked SQLite witness chain | Same + attestation envelope per entry |
| Attestation | none | TPM quotes + RDF-typed `AttestationEnvelope` triples |
| Policy engine | default-allow stub | RBAC + role-bound MRH policies |
| Resilience to OS compromise | low (key recoverable from filesystem) | high (key stays inside TPM PCR-bound) |

Same MCP surface. Same plugin SDK contract. Same R6/R7 chain shape.
**The plugins don't change.** They keep talking to the same daemon
endpoint and getting back the same payloads. The only thing that
changes is what's signing the entries and where the keys live.

## Architectural map

```
                   ┌──────────────────────────┐
                   │  any agent w/ MCP plugin │
                   │  (Claude Code, OpenClaw, │
                   │   Cursor, custom...)     │
                   └────────────┬─────────────┘
                                │  MCP / @hestia-tools/plugin-sdk
                                ▼
       ┌─────────────────────────────────────────────────┐
       │              hestia-core daemon                 │ ← this repo
       │  vault  │  chain  │  trust  │  MCP server       │
       └──────┬─────────────────────────────┬────────────┘
              │ trait-based bindings        │
        ┌─────┴──────┐                ┌─────┴──────┐
        │  Consumer  │                │  Hardbound │ ← private repo
        │  (default) │                │  bridge    │
        └────────────┘                └─────┬──────┘
                                            │
                                  ┌─────────┼──────────┐
                                  ▼         ▼          ▼
                              TPM 2.0   YubiKey   Secure Enclave
```

The bridge is the only enterprise-specific code. It implements:

- `TrustedKeyProvider` — replaces the deterministic placeholder LCT
  with hardware-attested key material.
- `SealedVault` — wraps the existing ChaCha20-Poly1305 vault with a
  TPM-sealing layer so the AEAD key never leaves the hardware-bound
  context.
- `AttestationSigner` — every `chain_entries` row gets a TPM signature
  in a sidecar table; verification crosses TPM quote + Ed25519
  signature + the chain's existing hash linkage.
- `OversightPolicy` — replaces the default-allow stub with a real
  policy engine (Phi-4 Mini policy model, per the dp-web4 hardbound
  Attack-263–270 defenses).

## Demo plan (not yet built in this repo)

The enterprise demo will mirror the consumer demo, with three additions:

1. **Identity bootstrap shows TPM source.** The Soft LCT line in the
   transcript becomes `Hardware LCT (TPM PCR4:..., attest_quote:...)`.
2. **Sealed vault.** A passphrase still gates open, but the vault file
   can't be decrypted on a different machine — copy the file and
   `hestia info` reports "vault present but unsealable on this hardware".
3. **Attested chain entries.** A sidecar `attestations.db` co-located
   with `witness.db` carries a TPM signature per entry. The demo dumps
   one entry verbatim and shows the TPM quote inline.

The bridge lives in `hardbound/integrations/hestia/`. The end-to-end
demo wires it the same way `demo/consumer/run.mjs` wires the consumer
path — replace the daemon spawn with the bridge-augmented daemon, then
run identical plugin interactions and observe the upgrade.

## Why this matters for compliance

The consumer demo proves Hestia *behaves* like a trust layer. The
enterprise demo proves it *holds up* under adversarial inspection:

- The witness chain is no longer "trust the user's machine to have
  recorded the truth" — it's "trust the TPM to have attested that
  this machine ran this code at this time and signed this hash."
- The vault is no longer "trust the user not to leak the passphrase"
  — it's "even with the passphrase, the vault won't decrypt off the
  bound hardware."
- Trust state evolution is still software (T3/V3 math is the same),
  but the inputs to that math — the success/failure flags on chain
  entries — are now non-repudiable.

EU AI Act Article 12-15 deadline is 2026-08-02. The Hardbound tier is
the answer to "show me the audit trail" in front of an auditor.
