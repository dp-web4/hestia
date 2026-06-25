# Hestia fleet roster

Tracks where the Hestia daemon, plugin, and dashboard are installed
across the fleet. Each machine updates its own row when it completes
the install.

**Install command (any machine):**
```sh
bash <(curl -fsSL https://raw.githubusercontent.com/dp-web4/hestia/main/deploy/fleet/install.sh)
```

**Install order** (per `replication-plan.md`):

| # | Machine    | OS / Arch              | Target binary                  | Daemon | Plugin | Dashboard | Notes |
|---|------------|------------------------|--------------------------------|--------|--------|-----------|-------|
| 1 | CBP        | Linux x86_64 (WSL2)    | x86_64-unknown-linux-gnu       | ✅      | ✅      | ✅         | First probe; reference deployment |
| 2 | Sprout     | Linux aarch64 (Jetson) | aarch64-unknown-linux-gnu      | ✅      | ✅      | ✅         | Rebuilt from source after JetPack 7.2 reinstall (2026-06-24, Rust 1.96, 5m16s, g9e62894). Daemon on loopback :7711, dashboard 200. Claude Code plugin re-wired (witness + policy, verified). New vault identity post-wipe; `hub join` pending — hub node offline at restore time. |
| 3 | Thor       | Linux aarch64 (Jetson Thor) | aarch64-unknown-linux-gnu | ✅      | ✅      | ✅         | ARC-AGI workload dialect; Thor is aarch64 (corrected from x86_64). Daemon + plugin installed cleanly on Tegra L4T 2026-05-21 |
| 4 | Legion     | Linux x86_64           | x86_64-unknown-linux-gnu       | ✅      | ✅      | ✅         | Built from source (Rust 1.94, 41s); systemd user service; RTX 4090 GPU-bound autonomous tracks |
| 5 | McNugget   | macOS aarch64 (M4)     | aarch64-apple-darwin           | ✅      | ✅      | ✅         | launchd ✓ (`com.web4.hestia.daemon`, pid alive on :7711); daemon v0.0.3; plugin hook (`post_tool_use.sh`) wired in `~/.claude/settings.json`; dashboard HTTP 200. macOS Tauri app (.app + .dmg, v0.1.0) built 2026-05-24. iOS pending full Xcode. |
| 6 | Nomad      | Linux x86_64           | x86_64-unknown-linux-gnu       | ⬜      | ⬜      | ⬜         | Mobile oversight |

**Legend:** ✅ installed · ⬜ pending · ❌ blocked (note in row)

## After install

1. Confirm `http://127.0.0.1:7711/` shows the dashboard
2. Generate at least one tool call (run a Claude Code command) and
   watch the chain length advance
3. Flip your row ⬜ → ✅ in the table above and commit

## Why an ordered rollout, not a blast

See `replication-plan.md` for rationale. The short version: each new
machine is a research probe — Sprout proves aarch64, Thor proves the
ARC dialect, McNugget proves launchd, etc. We want signal from each
addition, not just "another box."
