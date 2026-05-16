# Hestia Demos

End-to-end walkthroughs of the Hestia daemon. Two tiers:

- **`consumer/`** — local, self-sovereign, no hardware. The default tier:
  a passphrase-encrypted vault, software-bound Soft LCTs, SQLite witness
  chain. Targets indie users and small teams.

- **`enterprise/`** — overview of what Hardbound adds on top: TPM-bound
  identity, hardware-sealed vault, signed witness entries, attestation
  envelopes. Hardbound itself is a private repo; this folder is the
  pitch and the integration plan, not the implementation.

## Quickstart (consumer)

```bash
# 1. Build the daemon
cd core && cargo build

# 2. Build the TypeScript SDK (the demo depends on it)
cd ../plugin-sdk/typescript && npm install && npm run build

# 3. Install + run the demo
cd ../../demo/consumer && npm install && npm run demo
```

What the demo proves:

- Daemon spins up against a sandbox HOME (no global state touched)
- Vault enforces scope + consumer ACLs (one credential is granted, another
  is denied with a typed `hestia.vault_scope_mismatch` error)
- OpenClaw-style plugin connects, gets a Soft LCT, runs through a
  realistic R6 action sequence (Read / Bash / Write / Read)
- Witness chain grows with hash linkage; both successes and failures are
  recorded
- Trust evolves via `web4-trust-core` — `EntityTrust` T3/V3 update from
  outcomes, success rate computed across the session
- All state survives daemon restart (covered by `core/tests/persistence.rs`)

Set `KEEP_HOME=1` before running to preserve the sandbox HOME for
inspection (`sqlite3 $HOME/witness.db ...` etc).

## The enterprise pitch in one paragraph

Consumer Hestia gives you a self-sovereign trust layer that any AI agent
plugin can talk to: vault, Soft LCT identity, witness chain, T3/V3.
Hardbound takes the same daemon, binds it to a TPM 2.0 (or YubiKey, or
Secure Enclave), and signs the chain and seals the vault with the bound
key. The Soft LCT becomes a hardware-anchored LCT. The audit trail
becomes attestation-grade. Same MCP surface, same plugin SDK, same
witness chain shape — but anchored in silicon, so compliance reviewers
can verify what actually happened on what actually was the user's
hardware. See `enterprise/README.md`.
