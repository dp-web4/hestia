# hardbound (Rust)

Public trait surface for the **hardware-bound enterprise trust tier of
Web4**. This crate is the *contract*; implementations live elsewhere.

## What this crate is

Four traits + their supporting types:

| Trait | Replaces in consumer Hestia |
|---|---|
| `TrustedKeyProvider` | software-derived sovereign LCT |
| `SealedVault` | passphrase-derived AEAD key |
| `AttestationSigner` | Phase-1 placeholder signer LCT |
| `OversightPolicy` | default-allow stub |

Any compatible Hardbound implementation must expose at least one of
these (most will expose all four). A Hestia daemon configured with a
Hardbound provider gets:

- Hardware-anchored identity (TPM 2.0 / YubiKey / Secure Enclave)
- Sealed vault — even with the passphrase, the file won't decrypt off
  the bound hardware
- TPM-attested signatures over every witness chain entry
- A real policy engine in place of the OSS default-allow stub

## What this crate is NOT

- A working implementation. The reference (closed-source) impl lives
  at [metalinxx.io](https://metalinxx.io). Building against this crate
  pulls in only the trait shapes; you must wire an implementation
  yourself or contact `dp@metalinxx.io` for early access to the
  reference build.
- An exhaustive policy language. `OversightPolicy::evaluate` is the
  evaluation interface; the policy rules themselves are
  implementation-defined.

## See also

- [`hestia-core`](https://crates.io/crates/hestia) — the OSS daemon
  that these traits extend
- [`https://github.com/dp-web4/hestia/blob/main/demo/enterprise/README.md`](https://github.com/dp-web4/hestia/blob/main/demo/enterprise/README.md)
  — architectural pitch + integration plan

## Versioning

`0.0.1` — initial publication of the contract. Trait shapes may shift
before `0.1.0`. Pin a minor version and watch the changelog.

## License

AGPL-3.0-or-later, matching the rest of the dp-web4 stack. If you need
a permissive license for a compatible implementation, contact
`dp@metalinxx.io`.
