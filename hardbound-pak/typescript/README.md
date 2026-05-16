# hardbound (TypeScript)

Public interface surface for the **hardware-bound enterprise trust tier
of Web4**. This package is the *contract*; implementations live
elsewhere.

```typescript
import {
  TrustedKeyProvider,
  SealedVault,
  AttestationSigner,
  OversightPolicy,
  Attestation,
  PolicyAction,
  PolicyDecision,
  HardboundError,
} from "hardbound";
```

## What this package is

Four interfaces + supporting types:

| Interface | Replaces in consumer Hestia |
|---|---|
| `TrustedKeyProvider` | software-derived sovereign LCT |
| `SealedVault` | passphrase-derived AEAD key |
| `AttestationSigner` | Phase-1 placeholder signer LCT |
| `OversightPolicy` | default-allow stub |

## What this package is NOT

A working implementation. The reference (closed-source) impl lives at
[metalinxx.io](https://metalinxx.io). Contact `dp@metalinxx.io` for
early access.

## See also

- [`@hestia/plugin-sdk`](https://www.npmjs.com/package/@hestia/plugin-sdk)
  — TS SDK for plugging an agent into the OSS Hestia daemon
- [`hestia` Rust crate](https://crates.io/crates/hestia) — the daemon
  itself
- [`https://github.com/dp-web4/hestia/blob/main/demo/enterprise/README.md`](https://github.com/dp-web4/hestia/blob/main/demo/enterprise/README.md)
  — architectural pitch + integration plan

## License

AGPL-3.0-or-later. Contact `dp@metalinxx.io` if you need a permissive
license for a compatible implementation.
