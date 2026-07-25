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
| 6 | Nomad      | Linux x86_64           | x86_64-unknown-linux-gnu       | ✅      | ⬜      | ✅         | Mobile oversight. Daemon serving since ≥2026-07-21, v0.0.3 (`app-v0.1.2-130-g216c1c9`), dashboard 200 on :7711 — row was stale, corrected 2026-07-25 per nomad. Installed unit carried the `After=default.target` cycle (installed 2026-06-12, pre-`c77118ce`); repaired locally by nomad, never bit it because no other user unit is ordered `After=hestia.service`. Was also in a 289-restart 226/NAMESPACE loop until 2026-07-21 (WSL mount-namespacing vs the sandboxing block), cleared by a user-manager restart. |
| 7 | HUB        | Linux x86_64 (WSL2)    | x86_64-unknown-linux-gnu       | ✅      | ✅      | ✅         | Hub-operator machine. Built from source (HEAD g9c150dc, 30s); systemd user service + linger; loopback :7711. **First agent-owned identity** (`hestia init --ai`, LCT fc378634…) — not human-delegated. Claude Code plugin wired (PreToolUse gate + PostToolUse witness) alongside existing snarc hooks; safety preset. Dashboard is operator-key-gated (`operator.key`); monitor-only credential is a flagged gap for agent-owned nodes. |

**Legend:** ✅ installed · ⬜ pending · ❌ blocked (note in row)

## After install

1. Confirm `http://127.0.0.1:7711/` shows the dashboard
2. Generate at least one tool call (run a Claude Code command) and
   watch the chain length advance
3. Flip your row ⬜ → ✅ in the table above and commit

## Installed-unit drift (open, 2026-07-25)

Fixing `deploy/templates/hestia.service` in the repo does **not** reach a unit
file already written into a peer's `~/.config/systemd/user/`. Every systemd
install predating `c77118ce` carries `After=default.target` — the ordering
cycle. CBP and Nomad have repaired their own live units. **Sprout, thor, legion,
and HUB have not been confirmed.** McNugget is launchd, out of scope.

The line is latent, not harmful, on its own. It becomes destructive only when
some *other* user unit is ordered `After=hestia.service` — that unit is the one
systemd deletes, silently, at boot. Arming the mesh on a drifted machine
converts latent to active with no failure signal. So the risk is not "who has
the bad line" (everyone pre-`c77118ce`) but "who has, or will add, a unit
ordered after hestia."

Check your machine — no reboot needed, reads the manager's loaded state:

```sh
systemctl --user show hestia.service -p After --value | tr ' ' '\n' | grep -x default.target \
  && echo "DRIFTED — fix below" || echo "clean"
```

Fix: delete the `After=default.target` line from
`~/.config/systemd/user/hestia.service`, then `chmod 644` it and
`systemctl --user daemon-reload`. No restart required — ordering only matters
when systemd schedules jobs. Re-running `install.sh` also rewrites the unit
correctly and now verifies itself.

Do **not** use `systemd-analyze --user verify` for this check. Measured on CBP
2026-07-25: it returns clean, exit 0, on a unit carrying the cycle. It never
builds a job transaction, so it cannot see a transaction-time property.

## Why an ordered rollout, not a blast

See `replication-plan.md` for rationale. The short version: each new
machine is a research probe — Sprout proves aarch64, Thor proves the
ARC dialect, McNugget proves launchd, etc. We want signal from each
addition, not just "another box."
