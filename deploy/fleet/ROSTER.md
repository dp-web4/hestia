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
| 6 | Nomad      | Linux x86_64           | x86_64-unknown-linux-gnu       | ✅      | ⬜      | ⬜         | Mobile oversight. Daemon installed 2026-06-12, serving since at least 2026-07-21 (v0.0.3, dashboard 200 on :7711) — row corrected 2026-07-25 from nomad's own report; it had read ⬜⬜⬜ while the daemon was live. Plugin/dashboard unconfirmed, left pending rather than assumed. |
| 7 | HUB        | Linux x86_64 (WSL2)    | x86_64-unknown-linux-gnu       | ✅      | ✅      | ✅         | Hub-operator machine. Built from source (HEAD g9c150dc, 30s); systemd user service + linger; loopback :7711. **First agent-owned identity** (`hestia init --ai`, LCT fc378634…) — not human-delegated. Claude Code plugin wired (PreToolUse gate + PostToolUse witness) alongside existing snarc hooks; safety preset. Dashboard is operator-key-gated (`operator.key`); monitor-only credential is a flagged gap for agent-owned nodes. |

| 8 | pub        | Linux x86_64 (`tl-Precision-3650-Tower`) | x86_64-unknown-linux-gnu | ✅ | ⬜ | ⬜ | Added 2026-07-25. Was running `hestia serve` + `hub-watch.service` with **no roster row at all** — and carried the latent ordering cycle with a live detonator, so a remediation sweep scoped to this table would have skipped the machine most likely to lose its watcher at next boot. Remediated by pub. Plugin/dashboard unconfirmed. |

**Legend:** ✅ installed · ⬜ pending · ❌ blocked (note in row)

> **This table is evidence, not authority.** It is self-reported and has drifted
> in both directions (pub absent while live; nomad ⬜ while serving). Do not scope
> a fleet sweep to these rows — a machine that is not listed still carries the
> bug. Let the detector define the population: run the checks in
> `install.sh:verify_service_linux` on every machine that runs `hestia serve`,
> roster row or not. An inventory nobody reconciles fails the same way an
> `enabled` unit nobody reboot-tests does — it reports coverage it does not have.

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
