# Fleet replication plan

CBP is the first probe (see `../cbp/README.md`). The other five
machines come online in deliberate order so we get research signal
out of each addition, not just "more boxes running the same thing."

## Order of operations and why

1. **CBP** — done. Oversight machine, x86_64 Linux (WSL2), busy
   Claude Code session, large enough to absorb noise.
2. **Sprout** — Jetson, 8 GB RAM, aarch64. *The constraint probe.*
   If Hestia is heavy (SQLite cache pressure, glibc baseline,
   tokio overhead), Sprout flags it. The release binary cross-built
   for aarch64 is the artifact to validate.
3. **Cross-witnessing** between CBP and Sprout. Each daemon
   periodically posts its tail-hash to the other; a small "hestia
   gossip" sidecar reads/writes. The research question this opens:
   *do two Hestia societies that watch each other develop different
   trust states for the same plugin, and what does the divergence
   tell us?* This is the synthon-formation question at fleet scale.
4. **Thor** — heavy ARC-AGI workload, qwen 14B running. Witness
   chain on Thor will look completely different from CBP's —
   instead of human-driven Claude Code calls, it'll be the
   ARC-solving loop's own tool calls. Two distinct dialects of
   "what an agent does."
5. **Legion** — RTX 4090, Phi-4 14B, autonomous tracks. Adds a
   third dialect: GPU-bound batch workloads.
6. **McNugget** — M4 Mac, 24 GB. The macOS deployment probe.
   launchd instead of systemd. Different stdlib paths. Different
   pkg-installed glibc-equivalents.
7. **Nomad** — RTX 4060, mobile, oversight peer to CBP.

## Per-machine deployment recipe

### Linux (CBP, Sprout, Thor, Legion, Nomad)

```bash
# 1. Copy the release binary to ~/.local/bin/
#    Build once on x86_64; cross-build for aarch64 (Sprout):
#      cd hestia/core && cargo build --release --target aarch64-unknown-linux-gnu
mkdir -p ~/.local/bin && scp <build-host>:.../release/hestia ~/.local/bin/hestia

# 2. Generate passphrase + init vault
mkdir -p ~/.hestia && chmod 700 ~/.hestia
openssl rand -base64 30 | tr -d '\n' > ~/.hestia/.passphrase
chmod 600 ~/.hestia/.passphrase
HESTIA_PASSPHRASE="$(cat ~/.hestia/.passphrase)" ~/.local/bin/hestia init

# 3. Install systemd user unit
cp <repo>/deploy/templates/hestia.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now hestia.service
loginctl enable-linger "$USER"

# 4. (Optional) Wire claude-code hooks — only on machines where you
# actually run Claude Code interactively.
# Edit ~/.claude/settings.json — add the PostToolUse entry pointing
# to <repo>/integrations/claude-code/hooks/post_tool_use.sh

# 5. Smoke test
curl -s http://127.0.0.1:7711/mcp -X POST -H 'Accept: text/event-stream' \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"deploy-smoke","version":"0"}}}' \
  | grep -q '"name":"hestia"' && echo "✓" || echo "✗"
```

### macOS (McNugget)

Same shape, but `launchd` instead of systemd. Template:
`<repo>/deploy/templates/io.hestia.tools.plist`. Drop into
`~/Library/LaunchAgents/`, `launchctl load` it. No lingering needed
— launchd already handles user-session daemons.

## What changes per machine

- **The witness data**. Different agent populations on different
  machines produce different chain shapes. Compare them after a week.
- **The threat model on the passphrase file**. CBP is a personal
  WSL2; treat the passphrase like an ssh key. Thor / Legion run
  unattended; same treatment. Sprout sits on a network; consider
  TPM-binding earlier here (this is where Hardbound stops being
  optional).
- **The hook target**. CBP runs Claude Code → witness Claude Code's
  tool calls. Thor runs the ARC solver → witness the solver's tool
  calls (needs a different hook integration, not the claude-code
  one).

## Federation (after step 3 above)

Each daemon publishes a small "tail" record at `<HESTIA_HOME>/tail.json`:

```json
{
  "society_lct": "lct:web4:hestia:sovereign:cbp",
  "chain_position": 12433,
  "tail_hash": "...",
  "ts": "..."
}
```

A periodic cron rsyncs all machines' `tail.json` files to a shared
location (e.g. `private-context/fleet-state/hestia/`). Each daemon
witnesses the other tails via `hestia_request_witness` events so
the chains cross-reference each other's state at known points in time.

That's enough to ask: did all six machines agree about what each
other was doing at hour T? The audit trail becomes a fleet artifact,
not a per-machine artifact.

## What we are NOT doing yet

- Identity propagation. Sprout's `plugin:claude-code` and CBP's
  `plugin:claude-code` are *different entities* — the trust state
  doesn't merge. This is correct for now; cross-machine identity
  reconciliation is a hard design question that needs data first.
- Hardware binding. Coming with Hardbound for the unattended
  machines.
- Policy enforcement. The hook fires `record_outcome` only — no
  `query_policy`. Policy gates come once we know what we'd gate on,
  which is the witness-data analysis's job to tell us.
