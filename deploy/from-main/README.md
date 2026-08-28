# Deploy from main

One checkout, one timer, one log. The reference daemon on this box is deployed from
`origin/main` every four hours, from a checkout that nothing else touches. The script
header in `hestia-deploy.sh` explains the shape and the rollback; this file is the
install and the operating rules.

## Install — Linux, user systemd (once per box)

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

## Install — macOS, launchd (once per box)

Same script, same log, same rules; measured on mcnugget 2026-08-27 through two real cycles.
Only the service manager differs, so only the timer and the restart change, and
`hestia-deploy.sh` resolves both from `uname`.

    mkdir -p ~/.hestia/deploy ~/Library/Logs/hestia ~/.local/bin
    git clone git@github.com:dp-web4/hestia.git ~/.hestia/deploy/hestia
    git clone git@github.com:dp-web4/web4.git   ~/.hestia/deploy/web4
    install -m 0755 deploy/from-main/hestia-deploy.sh ~/.local/bin/hestia-deploy

    # Derive the binary from the daemon's REGISTRATION; never assume ~/.local/bin/hestia.
    BIN=$(launchctl print gui/$(id -u)/com.web4.hestia.daemon \
          | awk -F' = ' '$1 ~ /^[[:space:]]*program$/ { print $2; exit }')
    sed -e "s|__HOME__|$HOME|g" -e "s|__HESTIA_BIN__|$BIN|g" \
        deploy/from-main/com.web4.hestia.deploy.plist \
        > ~/Library/LaunchAgents/com.web4.hestia.deploy.plist
    launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.web4.hestia.deploy.plist
    launchctl kickstart -k gui/$(id -u)/com.web4.hestia.deploy   # first cycle, now, watched

That `BIN` line is the one step you cannot skip on a box that installed hestia by hand.
On mcnugget the daemon agent executes `/opt/homebrew/bin/hestia`, and a deploy pointed at
the `~/.local/bin` default would have written a current binary that nothing runs — logging
`DEPLOYED`, reading green on the dashboard, and changing nothing. The script reads the same
registration itself and **refuses** (`FAIL … set HESTIA_BIN to that path`, exit 1) when
`$HESTIA_BIN` and the registration disagree, before anything is built.

The plist is a template because launchd has no `%h`. There is no `RunAtLoad`, so
bootstrapping it is not a deploy — the `kickstart` is, and you watch it. Re-run the `sed` +
`bootstrap` pair (after `launchctl bootout gui/$(id -u)/com.web4.hestia.deploy`) when the
plist changes; as on Linux, only the script self-updates.

### One prerequisite that is not portable: bash

`deploy/install-members.sh` uses `declare -A` and `mapfile`, both **bash 4** builtins, and
macOS ships bash **3.2.57** (frozen at the last GPLv2 release) with nothing newer. A stock
Mac therefore fails the members' half of every cycle with

    install-members.sh: line 189: syntax error near unexpected token `('

`brew install bash` fixes it; `HESTIA_BASH` points at one in a nonstandard place. The script
checks for a bash ≥ 4 *before* invoking the installer and logs the requirement by name
rather than emitting that syntax error, so `hooks=skipped(no bash>=4)` is a diagnosis.

`HESTIA_BASH` is a **pin**, like `HESTIA_RESTART_CMD`: set, it is used or the cycle says why
it cannot be (`hooks=skipped(HESTIA_BASH not bash>=4)`) — it is never silently replaced by
a different interpreter found on `PATH`. It was a hint until 2026-08-27, when mcnugget
measured `HESTIA_BASH=/bin/bash` resolving to `/opt/homebrew/bin/bash` at rc=0, identical
to not setting it: an operator pinning 3.2 on purpose, to reproduce a stock Mac's failure,
got a different interpreter and no indication the pin was ignored. So this is also the
reproduction recipe for the half-deploy arm on any seat: `HESTIA_BASH=/bin/sh` (or any
non-bash-4) in the agent's environment on a cycle where main has moved ends
`HALF-DEPLOYED … (hooks=skipped(HESTIA_BASH not bash>=4))`, rc=1, daemon on the new binary.

This wants a fleet decision rather than local `brew install`s: either bash ≥ 4 is a
declared prerequisite for a hestia member host, or `install-members.sh` goes 3.2-clean
(two `mapfile` calls and one associative array). Measured consequence of leaving it:
mcnugget had **never once** written `~/.hestia/current-build.json` — its dashboard row read
"deployment: unknown" from the beginning, and nobody could see why, because no Linux box
could reproduce it.

## The four things that were Linux and not policy

Named here so the next non-systemd box finds them already answered. Each resolves from
`uname` and each is overridable when the default guesses wrong:

| | Linux | macOS | override |
|---|---|---|---|
| restart | `systemctl --user restart hestia.service` | `launchctl kickstart -k gui/<uid>/com.web4.hestia.daemon` | `HESTIA_RESTART_CMD`, `HESTIA_UNIT`, `HESTIA_LAUNCHD_LABEL` |
| lock | `flock(1)` | atomic `mkdir` lock, dead holder reaped by pid | — |
| mtime | `stat -c %Y` | `stat -f %m` | — |
| daemon's exe | `/proc/<MainPID>/exe` | `launchctl print` → `program =` | `HESTIA_BIN` |

macOS ships no `flock(1)`, and the original spelling of the lock line was
`flock -n 9 || { log "SKIP another deploy holds the lock"; exit 0; }`. On a Mac that is not
a crash: `flock: command not found` returns 127, the `||` fires, and the cycle logs
**"SKIP another deploy holds the lock" and exits 0** — a lie, at rc=0, forever, with a
healthy-looking log. Measured on mcnugget before the fix. That is the same silent-degrade
class the deploy policy exists to end, so the fallback is not a convenience: *a lock
primitive that is not there must never be indistinguishable from a lock that is held.*

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
  and does not take the lock — the default is refusal, not deployment.
- A half deploy heals on the **next timer cycle**: a full cycle that finds the binary
  `CURRENT` but `current-build.json` behind it (or absent) re-runs the members' install
  from the same synced checkout and logs `CURRENT <v> manifest-repair hooks=ok`. Until
  2026-08-27 that cycle logged `CURRENT` and exited before the installer, so a half deploy
  stayed half until someone ran `--hooks-only` by hand — and mcnugget measured that the
  someone, when it is an agent session, cannot (below). The timer is the one caller that
  is not a session, so its cycle is where the repair belongs. `--check` still only reports.
- `hestia-deploy --hooks-only` re-runs just the members' install by hand, **from an
  operator shell**: the installer refuses inside a governed session (`CLAUDECODE` /
  `HESTIA_ROLE` set without the operator ack), and the cycle spells that
  `hooks=refused(governed session)` — still rc=1, the manifest genuinely was not written,
  but named apart from `FAILED(rc=N)` because it is the governance surface working, not an
  install broken, and "fix the cause" is not the repair. mcnugget 2026-08-27: agent-run
  `--hooks-only` on that seat produced `FAILED(rc=3)` twice and never a manifest, while the
  launchd cycle (no `CLAUDECODE`) wrote it normally. `--hooks-only` refuses unless the
  synced checkout still equals what is deployed — otherwise it would write a `build_id`
  from a moved main over the running binary and manufacture the very divergence the
  manifest exists to disprove (mcnugget measured exactly that on the flag's first use,
  before the guard).
- The script refuses (exit 1, `FAIL`) when `HESTIA_BIN` is not the file the daemon is
  executing, or the lock primitive is missing and the fallback cannot be taken, or the
  restart command fails — a failed restart rolls back to the saved binary first. A
  `SKIP` at exit 0 means exactly two things: another deploy holds the lock, or a hold
  file is present. Nothing else exits 0 without deploying — and a **half** deploy does not
  exit 0 either: `DEPLOYED … hooks=FAILED(rc=N)`, `hooks=refused(governed session)`,
  `hooks=skipped(no bash>=4)` / `skipped(HESTIA_BASH not bash>=4)` / `skipped(no installer)`
  leaves the binary current and the manifest unwritten, so the cycle exits 1
  (`HALF-DEPLOYED` is the last line, and it names the repair for that value), the unit
  reads failed, and the next timer cycle repairs the manifest. The binary is not rolled
  back: a stale daemon would be a worse state than a stale manifest, and the manifest is
  what the repair rewrites. `hooks=ok` is checked against the **file**, not the installer's
  exit code: the installer exits 0 without writing anything when no member is registered on
  the host (and under `DRY_RUN=1`), and mcnugget measured the repair path reading that as
  `manifest-repair hooks=ok`, rc=0, under a real launchd timer, twice, with no manifest on
  disk — green every 4h, forever, on exactly the headless profile being onboarded next. It
  is now `hooks=FAILED(installer rc=0, manifest 'none')`, rc=1, and the tail says to look at
  the installer's own lines above. The one `hooks=skipped` that exits 0 is the explicit opt-out,
  `HESTIA_DEPLOY_HOOKS=0` (mcnugget asked which it was, 2026-08-27; this is the answer).
  Measured on Darwin by mcnugget (sandboxed home, real build, stub restart): rc=1, binary
  current, manifest absent, `launchctl list` column 2 = 1.
- Every cycle appends one line to `~/.hestia/deploy.log`; a deploy appends
  `DEPLOYED <old> -> <new> (hestia <sha>, web4 <sha>) hooks=<ok|skipped|FAILED>`.
  `journalctl --user -u hestia-deploy` has the same lines plus cargo's tail; on macOS
  that second copy is `~/Library/Logs/hestia/deploy-agent.log`.
- The members' installer refuses to run from inside a governed session (it is the
  gate installing the gate; the cycle logs it as `hooks=refused(governed session)`); it
  runs under the timer, which is not a member. Test the whole cycle through the service
  manager, never by hand:
  `systemctl --user start hestia-deploy.service`, or on macOS
  `launchctl kickstart -k gui/$(id -u)/com.web4.hestia.deploy`.

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
| mcnugget (macOS) | adopted via its port (`806f620`): `DEPLOYED 478 -> 484` (95s cold, `hooks=FAILED` on bash 3.2) then `484 -> 485 hooks=ok` in 40s through the launchd agent; found flock/stat/restart/BIN and the bash ≥ 4 prerequisite. The merged script here has not yet run on that seat. |
| sprout, thor | unmeasured — check `command -v flock` (the fallback covers its absence, but say which path you run) |
