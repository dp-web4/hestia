# Deploy from main

One checkout, one timer, one log. The reference daemon on this box is deployed from
`origin/main` every four hours, from a checkout that nothing else touches. The script
header in `hestia-deploy.sh` explains the shape and the rollback; this file is the
install and the operating rules.

## Install (once per box, systemd seats)

    mkdir -p ~/.hestia/deploy
    git clone git@github.com:dp-web4/hestia.git ~/.hestia/deploy/hestia
    git clone git@github.com:dp-web4/web4.git   ~/.hestia/deploy/web4
    install -m 0755 deploy/from-main/hestia-deploy.sh ~/.local/bin/hestia-deploy
    install -m 0644 deploy/from-main/hestia-deploy.{service,timer} ~/.config/systemd/user/
    systemctl --user daemon-reload
    systemctl --user enable --now hestia-deploy.timer
    journalctl --user -u hestia-deploy -f

Until #698 merges, `deploy/from-main/` is **not on main**: run the two `install` lines from
a checkout of `cbp/deploy-from-main`, not from `~/.hestia/deploy/hestia` (which is main and
does not have the directory yet). The script's self-update is guarded by `[ -f … ]`, so it
is a no-op until main carries the file, not a break.

**`enable --now` IS the first cycle.** `Persistent=true` with no stamp file fires the
service the instant the timer activates (measured on Legion: `LAST 16ms ago`). Do not
follow it with `systemctl --user start hestia-deploy.service`: that is a second start
racing the first, and the loser logs `SKIP another deploy holds the lock`, which reads
like a fault on a fresh install. Watch the one that ran with the `journalctl -f` line.

`~/.local/bin/hestia-deploy` keeps itself current from the deploy checkout after that.
The unit files do not: re-run the `install` line for them when they change.

## Install on a seat without systemd (macOS / launchd)

The script is the same; three things differ, each an environment variable, and each fails
loudly rather than silently when unset (see `hestia-deploy.sh` header, PORTABILITY):

| what | systemd default | macOS (measured on mcnugget, 2026-08-27) |
|---|---|---|
| `HESTIA_BIN` | `~/.local/bin/hestia` | `/opt/homebrew/bin/hestia` — what the plist's `ProgramArguments[0]` execs |
| `HESTIA_RESTART_CMD` | `systemctl --user restart hestia.service` | `launchctl kickstart -k gui/<uid>/com.web4.hestia.daemon` |
| lock | `flock(1)` | absent; the script falls back to an atomic `mkdir` lock with pid reaping |

`com.web4.hestia-deploy.plist` is the launchd equivalent of the service + timer:
`StartCalendarInterval` at the same six wall-clock marks (xx:17 every 4h — `StartInterval`
would drift from load time and across sleeps, and the fixed schedule is the point of policy
point 1). It carries `__HOME__` and `__UID__` placeholders because launchd does not expand
`$HOME` or `$(id -u)`:

    sed -e "s|__HOME__|$HOME|g" -e "s|__UID__|$(id -u)|g" \
        deploy/from-main/com.web4.hestia-deploy.plist \
        > ~/Library/LaunchAgents/com.web4.hestia-deploy.plist
    install -m 0755 deploy/from-main/hestia-deploy.sh ~/.local/bin/hestia-deploy
    launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.web4.hestia-deploy.plist
    launchctl kickstart gui/$(id -u)/com.web4.hestia-deploy   # first cycle, now

The plist was written from mcnugget's measurements, not run there: **untested on a macOS
seat as of 2026-08-27.** Before enabling it, run `hestia-deploy --check` and
`hestia-deploy --build-only` by hand with the same environment; the first exercises the
lock, the hold expiry and the `HESTIA_BIN`-vs-daemon check, the second the build.

## Operating rules

- Deploy from that checkout, always. Nothing installs the daemon binary from a worktree
  any more. If you need a branch running on the reference daemon, merge it.
- Local branch work never contends with a deploy build: the deploy tree has its own
  cargo target under `~/.hestia/deploy/target`, and the service runs at `Nice=15` so the
  daemon's gate round-trip preempts the build (`deploy/build-lock/README.md`). The only
  thing a deploy does that anyone else can see is the restart, and only when main moved
  since the last cycle.
- A test that needs the daemon stable: `echo "why, who" > ~/.hestia/deploy.hold`.
  The next cycle skips and logs the reason. A hold older than 6h is ignored, so a
  forgotten file cannot stop deploys silently. Remove it when done.
- `hestia-deploy --check` says whether the running daemon is current (exit 0) or
  stale (exit 3) without building. `hestia-deploy --build-only` builds without
  installing, for a pre-flight before a hold. Any other argument is usage, exit 2,
  and does not take the lock.
- The script refuses (exit 1, `FAIL`) when `HESTIA_BIN` is not the file the daemon is
  executing, or the lock primitive is missing and the fallback cannot be taken, or the
  restart command fails — a failed restart rolls back to the saved binary first. A
  `SKIP` at exit 0 means exactly two things: another deploy holds the lock, or a hold
  file is present. Nothing else exits 0 without deploying.
- Every cycle appends one line to `~/.hestia/deploy.log`; a deploy appends
  `DEPLOYED <old> -> <new> (hestia <sha>, web4 <sha>) hooks=<ok|skipped|FAILED>`.
  `journalctl --user -u hestia-deploy` has the same lines plus cargo's tail.
- The members' installer refuses to run from inside a governed session (it is the
  gate installing the gate); it runs under the timer, which is not a member. Test the
  whole cycle with `systemctl --user start hestia-deploy.service`, never by hand.

## What is deployed, and what is not

The daemon binary, then `deploy/install-members.sh` from the same checkout, so the
manifest's `build_id` matches the binary and the dashboard comparison is true by
construction. Set `HESTIA_DEPLOY_HOOKS=0` in the service environment to deploy the
daemon only. The web4 sibling tracks web4 main, which is what CI's `cargo test` builds
hestia against; `web4.pin` is a release property and is not consulted here.

## Adoption record

| seat | status (2026-08-27) |
|---|---|
| CBP | adopted; first cycle 239s cold, `DEPLOYED 444 -> 484`, rollback arm unfired |
| Legion | adopted; 65s cold at nice 15; found the mode-parser hole and the `enable --now` race |
| mcnugget (macOS) | **not adopted**: flock/stat/systemctl/BIN blockers measured, all addressed above; plist untested |
| sprout, thor | unmeasured — check `command -v flock` (the fallback covers its absence, but say which path you run) |
