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

`~/.local/bin/hestia-deploy` keeps itself current from the deploy checkout after that.
The unit files do not: re-run the `install` line for them when they change.

## Install — macOS, launchd (once per box)

Same script, same log, same rules. Only the service manager differs, so only the timer
and the restart change; `hestia-deploy.sh` resolves both from `uname`.

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

That `BIN` line is the one step you cannot skip on a box that installed hestia by hand.
On mcnugget the daemon agent executes `/opt/homebrew/bin/hestia`, and a deploy pointed at
the `~/.local/bin` default would have written a current binary that nothing runs — logging
`DEPLOYED`, reading green on the dashboard, and changing nothing. The script logs a `WARN`
whenever `$HESTIA_BIN` and the registration disagree, so that mistake cannot stay quiet.

The plist is a template because launchd has no `%h`. Re-run the `sed` + `bootstrap` pair
(after `launchctl bootout gui/$(id -u)/com.web4.hestia.deploy`) when it changes; as on
Linux, only the script self-updates.

## Operating rules

- Deploy from that checkout, always. Nothing installs `~/.local/bin/hestia` from a
  worktree any more. If you need a branch running on the reference daemon, merge it.
- Local branch work never contends with a deploy build: the deploy tree has its own
  cargo target under `~/.hestia/deploy/target`. The only thing a deploy does that
  anyone else can see is the restart, and only when main moved since the last cycle.
- A test that needs the daemon stable: `echo "why, who" > ~/.hestia/deploy.hold`.
  The next cycle skips and logs the reason. A hold older than 6h is ignored, so a
  forgotten file cannot stop deploys silently. Remove it when done.
- `hestia-deploy --check` says whether the running daemon is current (exit 0) or
  stale (exit 3) without building. `hestia-deploy --build-only` builds without
  installing, for a pre-flight before a hold. An unrecognised argument exits 64 and
  deploys nothing — the default has to be refusal, not deployment.
- `hestia-deploy --hooks-only` re-runs just the members' install, for the one case the
  cycle cannot recover on its own: `hooks=FAILED` leaves the binary current and the
  manifest stale, so the next cycle logs `CURRENT` and exits before reaching the
  installer. It refuses unless the synced checkout still equals what is deployed —
  otherwise it would write a `build_id` from a moved main over the running binary and
  manufacture the very divergence the manifest exists to disprove.
- Every cycle appends one line to `~/.hestia/deploy.log`; a deploy appends
  `DEPLOYED <old> -> <new> (hestia <sha>, web4 <sha>) hooks=<ok|skipped|FAILED>`.
  `journalctl --user -u hestia-deploy` has the same lines plus cargo's tail; on macOS
  that second copy is `~/Library/Logs/hestia/deploy-agent.log`.
- The members' installer refuses to run from inside a governed session (it is the
  gate installing the gate); it runs under the timer, which is not a member. Test the
  whole cycle through the service manager, never by hand:
  `systemctl --user start hestia-deploy.service`, or on macOS
  `launchctl kickstart -k gui/$(id -u)/com.web4.hestia.deploy`.

## The three things that were Linux and not policy

Named here because the next non-systemd box should find them already answered, and
because each is overridable when the default guesses wrong:

| | Linux | macOS | override |
|---|---|---|---|
| restart | `systemctl --user restart hestia.service` | `launchctl kickstart -k gui/<uid>/com.web4.hestia.daemon` | `HESTIA_RESTART_CMD`, `HESTIA_UNIT`, `HESTIA_LAUNCHD_LABEL` |
| lock | `flock(1)` | `O_EXCL` create, stale locks taken | — |
| mtime | `stat -c %Y` | `stat -f %m` | — |

macOS ships no `flock(1)`, and the original's spelling of that line is
`flock -n 9 || { log "SKIP another deploy holds the lock"; exit 0; }`. On a Mac that is not
a crash: `flock: command not found` returns 127, the `||` fires, and the cycle logs
**"SKIP another deploy holds the lock" and exits 0** — a lie, at rc=0, forever, with a
healthy-looking log. Measured on mcnugget before the fix. That is the same silent-degrade
class the deploy policy exists to end, so the fallback is not a convenience.

### One prerequisite that is not portable: bash

`deploy/install-members.sh` uses `declare -A` and `mapfile`, both **bash 4** builtins, and
macOS ships bash **3.2.57** (frozen at the last GPLv2 release) with nothing newer. A stock
Mac therefore fails the members' half of every cycle with

    install-members.sh: line 189: syntax error near unexpected token `('

`brew install bash` fixes it; `HESTIA_BASH` points at one in a nonstandard place. The script
now checks for a bash ≥ 4 *before* invoking the installer and logs the requirement by name
rather than emitting that syntax error, so `hooks=skipped(no bash>=4)` is a diagnosis.

This is worth a fleet decision rather than five local `brew install`s: either bash ≥ 4 is a
declared prerequisite for a hestia member host, or `install-members.sh` should be 3.2-clean
(two `mapfile` calls and one associative array). Measured consequence of leaving it: mcnugget
had **never once** written `~/.hestia/current-build.json` — its dashboard row read
"deployment: unknown" from the beginning, and nobody could see why, because no Linux box
could reproduce it.

## What is deployed, and what is not

The daemon binary, then `deploy/install-members.sh` from the same checkout, so the
manifest's `build_id` matches the binary and the dashboard comparison is true by
construction. Set `HESTIA_DEPLOY_HOOKS=0` in the service environment to deploy the
daemon only. The web4 sibling tracks web4 main, which is what CI's `cargo test` builds
hestia against; `web4.pin` is a release property and is not consulted here.
