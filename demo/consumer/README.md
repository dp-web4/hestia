# Hestia Consumer Demo

End-to-end walkthrough: a Hestia daemon + OpenClaw-style plugin running
against the real Rust core, with a transcripted action sequence and a
witness chain dump.

## What you'll see

1. Daemon initialization (vault + identity)
2. Vault credential seeding with scope + consumer ACLs
3. Daemon startup on a sandbox port
4. Plugin connect → Soft LCT issued
5. A realistic R6 action sequence:
   - `Read /etc/hostname` (low magnitude)
   - `vault_get anthropic_key` (allowed)
   - `vault_get github_pat` under wrong scope (denied with typed error)
   - `Bash echo hello` (high magnitude)
   - `Write /tmp/demo.txt` (simulated failure → trust hit)
   - 2× `Read` (recover)
6. Witness chain dump (chain_position, event_type, detail, hash)
7. Trust state (T3/V3 via `web4-trust-core`)
8. Cross-agent shared context (empty in this demo; populated by other plugins)

## Requirements

- Built `hestia` binary: `cd core && cargo build`
- Built `@hestia/plugin-sdk`: `cd plugin-sdk/typescript && npm install && npm run build`
- Node.js ≥ 20

## Running

```bash
cd demo/consumer
npm install
npm run demo
```

Set `KEEP_HOME=1` to preserve the sandbox HOME for poking around:

```bash
KEEP_HOME=1 npm run demo
# inspect the daemon's persisted state:
ls /tmp/hestia-demo-*
sqlite3 /tmp/hestia-demo-*/witness.db "SELECT * FROM chain_entries"
cat /tmp/hestia-demo-*/trust/*.json
```

## Sample transcript

See `transcript.txt` for a captured run.

## What this demonstrates that matters

- **Self-sovereignty**: the daemon runs on your machine, owns its own
  state, never phones home. No SaaS dependency.
- **Plugin-agnostic**: this demo uses an OpenClaw-style hook, but any
  agent that speaks MCP (Claude Code, Cursor, your own) can plug in via
  the SDK. Hestia is the layer; the agent is the substrate.
- **Typed errors across MCP**: the denied-scope vault read surfaces as
  a `hestia.vault_scope_mismatch` exception on the SDK side, not a
  generic "tool failed" — Mechanism A from ADR-0005 in action.
- **Audit trail you can grep**: `witness.db` is a vanilla SQLite file.
  Open it in DBeaver, sqlite3, or anything. Nothing about it is opaque.
- **Trust math is canonical Web4**: `EntityTrust` from
  `web4-trust-core` 0.2 — same crate, same tests, same RDF backing as
  every other Web4 implementation.
