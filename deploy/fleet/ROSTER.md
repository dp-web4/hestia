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
| 2 | Sprout     | Linux aarch64 (Jetson) | aarch64-unknown-linux-gnu      | ⬜      | ⬜      | ⬜         | The constraint probe |
| 3 | Thor       | Linux x86_64           | x86_64-unknown-linux-gnu       | ⬜      | ⬜      | ⬜         | ARC-AGI workload dialect |
| 4 | Legion     | Linux x86_64           | x86_64-unknown-linux-gnu       | ⬜      | ⬜      | ⬜         | GPU-bound autonomous tracks |
| 5 | McNugget   | macOS aarch64 (M4)     | aarch64-apple-darwin           | ⬜      | ⬜      | ⬜         | launchd probe |
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
