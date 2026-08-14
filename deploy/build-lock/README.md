# Build lock — cargo build de-prioritizer

**Increment 1 of the git-manager build lock. Tracks issue #358; root cause #354.**

## The problem
A heavy `cargo build` pins the CPU and starves the hestia daemon's **gate round-trip**
(`/mcp` POST — the real-work path, unlike the static `GET /` which stays sub-millisecond).
Under that contention every member's gate call **fail-closes on timeout**. On a shared
multi-member build host (claude / kimi / codex under one home), **one member's build times out
everyone**, and pausing live sessions does not help because auto sessions keep firing builds.

Measured (2026-08-12): kimi ran `cargo build --manifest-path core/Cargo.toml`, loadavg hit
6.62, and both kimi and codex fail-closed. The box had 21 GB free and never swapped — it is
purely CPU scheduling. The per-request timeout bump (#353, 0.5→5.0) lets a member *survive* a
stall, but a timeout knob cannot fix a CPU DoS: the gate makes several round-trips and their
sum still blows the budget when a build owns the CPU.

## The fix (this directory)
A transparent `cargo` shim that runs heavy, compile-bound subcommands
(`build`/`test`/`check`/`clippy`/`bench`/`doc`/`install`) under `nice -n 15`, so the daemon
(normal priority) **preempts the build** and the gate stays responsive. The build yields; it
does not starve the referee. Everything else passes straight through. The real cargo is
resolved as the first non-shim `cargo` on PATH and exec'd by absolute path, so the shim cannot
recurse and cannot break a build.

```
./install.sh                 # -> ~/.local/bin/cargo   (must precede ~/.cargo/bin in PATH)
cargo --version              # pass-through: prints the real cargo version
```

A **running** build that predates the shim can be relieved without killing it:
`renice -n 15 -p <build-pids>` (loadavg 6.62→0.98 when done live).

## Increments
1. **nice** (increment 1) — deprioritize heavy builds so the daemon preempts them.
2. **serialize + warm shared target** (increment 2, #387) — after measurement showed timeouts at
   *low CPU%* during sweeps, the second channel is **IO**: a cold build reads thousands of source
   files off the `/mnt/c` 9p mount, saturating the drvfs read queue every gate call also traverses
   (the daemon's own law/chain/vault are ext4, so the daemon is not the `/mnt/c` reader — the
   builds and the gate imports are). So the shim now:
   - **serializes** heavy builds via `flock` (N concurrent → 1), fail-open on a stuck lock
     (`HESTIA_BUILD_LOCK_WAIT`, default 900s) so a hung build can't deadlock the fleet;
   - defaults `CARGO_TARGET_DIR` to a **warm ext4 target shared across a repo's worktrees** (keyed
     on the git common-dir, so other projects and a caller's own `CARGO_TARGET_DIR` are untouched)
     — a worktree build becomes incremental (seconds) instead of a cold 8 minutes, slashing both
     the source-read storm on `/mnt/c` and the target IO. This is the bigger lever of the two.

### Still tracked (#358 / #387)
- **ionice** the build IO (compiles still compete with the daemon's ext4 chain reads).
- **Install the mechanism to ext4** beside each member's installed gate, so the hook's
  `hestia_gate_mechanism` import is ext4 too (kimi's gate is installed on ext4 but still imports
  the mechanism off `/mnt/c`) — closes the last `/mnt/c` read on the gate hot path.
- **The git-manager role** owns this properly — the single actor that runs/serializes builds,
  reconciles merges, and reaps worktrees on behalf of members. This shim is its increments.

## Deployment
Install on every build host (not just CBP). This is exactly the deployment-consolidation
discipline `docs/PRD_GATE_CONSOLIDATION.md` §7.2 demands of the gate itself: *declared →
executable → deployed → observed* — a source file that lives in the repo but is installed
per-host by hand drifts like any other copy. The git-manager should own the canonical install
and measure convergence.
