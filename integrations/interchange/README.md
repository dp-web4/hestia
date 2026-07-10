# hestia vault backend for Interchange

A small, working integration that lets [Interchange](https://github.com/faremeter/interchange)
store credential secrets in [hestia](https://github.com/dp-web4/hestia)'s encrypted vault
instead of a plaintext database column.

## What it solves

Interchange's `docs/CREDENTIALS.md` notes:

> Encryption at rest: secrets are currently stored as plaintext. Envelope encryption or KMS
> integration is a separate concern to be addressed independently.

This backend is that separate concern. The `credential.secret` column
(`packages/db/src/schema/credentials.ts`) holds a reference:

```
hestia+vault://openai-prod
```

The real secret lives in hestia's vault (Argon2id + ChaCha20-Poly1305, SQLCipher at rest,
loopback-only) and is dereferenced to plaintext only at agent-launch materialization, inside
the control-plane process that already reads the column today
(`packages/hub-sessions/src/credential-push.ts`). Plaintext never lands in Postgres. Literal
(legacy) secrets pass through unchanged, so the change is additive.

```
 credential.secret = "hestia+vault://openai-prod"     Postgres holds a reference
                                |
             materializeSecret(row)   one call, at launch, control-plane side
                                |
                     hestia vault get openai-prod       encrypted store
                                |
                                v
        HarnessConfig.secret = "sk-live-..."            in memory only, as today
```

## Files

| File | Role |
|---|---|
| `hestia-vault-backend.ts` | The conforming implementation, typed for Interchange's tree. |
| `hestia-vault.mjs` | The same logic, runnable on plain Node (no bun / TS toolchain). |
| `demo.mjs` | End-to-end round-trip against a live hestia vault. |

## Run it

Requires an initialized hestia on the machine (`~/.hestia` + passphrase), which the
control-plane host running Interchange would have.

```bash
node demo.mjs
```

Expected:

```
  [1] sealed "intx-path-a-demo" in hestia vault (Argon2id + ChaCha20-Poly1305)
  [2] Postgres credential.secret = "hestia+vault://intx-path-a-demo"
  [2] asserted: the real secret is NOT present anywhere in the DB row
  [3] materialized secret for the harness = "sk-live-DEMO-ONLY-..."
  [4] asserted: harness receives the true secret; DB still holds only the ref
  [5] asserted: legacy plaintext secrets pass through unchanged (additive)
  OK PASS - secret sealed at rest, referenced in DB, released only at launch.
```

## How it slots into Interchange

1. `credential.type` gains a `vault_ref` variant (or the ref is detected by scheme).
2. `resolveCredentialRequirement` is unchanged; it still returns the row.
3. `credential-push.ts` calls `materializeSecret(row)` immediately before assembling
   `HarnessConfig` - one line at the single point where the plaintext is read today.
4. The admin UI's "create credential" flow writes a `hestia+vault://` ref (and can seal the
   value into hestia in the same action) instead of a plaintext column.

No change to the grant model, the wire protocol, the harness, or the agent. The same pattern
generalizes to `refreshSecret` and OAuth tokens.

This prototype drives hestia through its CLI (`hestia vault get/add/remove`), which the
operator / control-plane context is authorized for (it holds the passphrase). A production
backend could speak hestia's local API directly instead of shelling out.

## Wider context

hestia is one component of [Web4](https://github.com/dp-web4/web4), a proposed open standard
for agentic-AI governance: witnessed identity (LCTs), a policy/law engine, an append-only
witnessed audit ledger, and a metered accountability model. The credential vault shown here is
the smallest, most concrete seam between the two systems; the aim is a common substrate that
platforms like Interchange can adopt rather than each re-implement.

## Licensing and acknowledgments

- **Interchange** is by Alexander Guy / Faremeter, licensed **LGPL-2.1-only**
  (<https://github.com/faremeter/interchange>). This integration references Interchange's
  documented interfaces and file layout (`credential.secret`, `resolveCredentialRequirement`,
  `credential-push.ts`); it contains no copied Interchange source. Thanks to the Interchange
  authors for a clean, well-documented codebase to build against.
- **hestia / Web4** are by dp-web4, licensed **AGPL-3.0-or-later**. This directory is part of
  the hestia repository and carries that license.
- **Linking direction:** a bridge that *uses* Interchange's LGPL-2.1 interfaces from AGPL code
  is compatible. Anyone shipping this as part of Interchange (LGPL) should confirm the linking
  direction for that distribution; the LGPL-2.1 notice-retention terms apply either way.
