#!/usr/bin/env bash
# hestia-deploy: deploy the daemon and the members' governance surface from origin/main,
# on a timer, from ONE checkout that nothing else touches.
#
# WHY: the reference daemon was days old and forty commits behind main, the loop repairs
# it needed (#666/#667) were merged and not running, and every prior deploy on this box was
# a hand-copy from whichever worktree someone happened to be in (`hestia.prev-*` backups
# with no script behind them). "Merged" is not "in force"; this makes the distance between
# the two a schedule instead of a memory.
#
# THE SHAPE:
#   ~/.hestia/deploy/hestia   the deploy checkout, hard-reset to origin/main every cycle
#   ~/.hestia/deploy/web4     its sibling, tracking web4 main (what CI's `cargo test` builds
#                             against; releases pin web4.pin instead, and that is a release
#                             property, not a deploy-main property)
#   ~/.hestia/deploy/target   its own cargo target: nothing is shared with the worktrees,
#                             so a local branch build never contends with a deploy build
#                             and the artifact-split class in the workspace cargo config
#                             cannot recur here.
#
# WHAT ONE CYCLE DOES: sync both clones; if the checkout's `git describe` equals the running
# daemon's version and the on-disk binary's, log "current" and stop (most cycles). Else build
# release, verify the new binary describes itself as the checkout, back up and atomically
# replace ~/.local/bin/hestia, restart the unit, wait for the daemon to answer `initialize`
# with the new version, and only then run deploy/install-members.sh from the same checkout so
# current-build.json's build_id matches the binary by construction. If the daemon does not
# come back on the new binary, the previous binary is restored and restarted, and the cycle
# fails loudly.
#
# STAYING OUT OF THE WAY OF LOCAL WORK: only the restart is observable to anyone else, and
# only when main moved. The timer fires at a fixed wall clock (see hestia-deploy.timer). A
# test that needs the daemon stable touches ~/.hestia/deploy.hold; a hold younger than
# HOLD_MAX_SECS skips the cycle (the hold is logged, and it expires so a forgotten file
# cannot silently stop deploys).
#
# Modes:  (none)        full cycle
#         --check       sync + report currency, no build, no restart, exit 0 current / 3 stale
#         --build-only  sync + build, no install, no restart
#         anything else usage, exit 2, BEFORE the lock is taken (a typo'd flag from a shell
#                       used to run a full cycle: Legion, 2026-08-27)
#
# PORTABILITY (mcnugget, 2026-08-27, measured on Darwin): flock(1) and `stat -c` are GNU/util-linux
# and absent on macOS and slim images; `systemctl --user restart` is a systemd seat's restart.
# Each has a portable path below, and the invariant that matters is that a MISSING primitive
# fails loudly instead of looking like a healthy SKIP. Non-systemd seats set:
#   HESTIA_BIN          the file the daemon actually execs (e.g. /opt/homebrew/bin/hestia)
#   HESTIA_RESTART_CMD  e.g. "launchctl kickstart -k gui/$(id -u)/com.web4.hestia.daemon"
set -euo pipefail

DEPLOY_ROOT="${HESTIA_DEPLOY_ROOT:-$HOME/.hestia/deploy}"
HESTIA_HOME="${HESTIA_HOME:-$HOME/.hestia}"
BRANCH="${HESTIA_DEPLOY_BRANCH:-main}"
BIN="${HESTIA_BIN:-$HOME/.local/bin/hestia}"
SELF_INSTALL="$HOME/.local/bin/hestia-deploy"
EP="${HESTIA_ENDPOINT:-http://127.0.0.1:7711/mcp}"
UNIT="${HESTIA_UNIT:-hestia.service}"
RESTART_CMD="${HESTIA_RESTART_CMD:-systemctl --user restart $UNIT}"
LOG="$HESTIA_HOME/deploy.log"
HOLD="$HESTIA_HOME/deploy.hold"
HOLD_MAX_SECS="${HESTIA_DEPLOY_HOLD_MAX_SECS:-21600}"
KEEP_BACKUPS="${HESTIA_DEPLOY_KEEP_BACKUPS:-5}"
READY_SECS="${HESTIA_DEPLOY_READY_SECS:-120}"
MODE="${1:-full}"
case "$MODE" in
  full|--check|--build-only) ;;
  *) echo "usage: hestia-deploy [--check|--build-only]" >&2; exit 2 ;;
esac

export CARGO_TARGET_DIR="$DEPLOY_ROOT/target"
export PATH="$HOME/.cargo/bin:$PATH"
T0=$(date +%s)

log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" | tee -a "$LOG" >&2; }
die() { log "FAIL $*"; exit 1; }

# The parenthesised `git describe` string from a version line, e.g.
#   hestia 0.0.4 (v0.0.4-444-gdd4300c)  ->  v0.0.4-444-gdd4300c
describe_of() { grep -oE '\([^)]+\)' | head -1 | tr -d '()'; }

running_version() {
  curl -s -m 10 -X POST "$EP" \
    -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"hestia-deploy","version":"0"}}}' \
    2>/dev/null | tr -d '\r' | grep -o '"serverInfo":{[^}]*}' | describe_of || true
}

# mtime as epoch seconds: GNU `stat -c %Y`, BSD `stat -f %m`. Selected ONCE, GNU first: on GNU
# `-f` means "file system status" and `%m` is read as a path, so probing the BSD form first is
# not a clean failure (measured: it prints an fs block and exits 1, and BSD `stat -c` prints
# nothing at all, which is how the hold expiry lost its operand on mcnugget).
if stat -c %Y / >/dev/null 2>&1; then mtime_of() { stat -c %Y "$1"; }
else                                   mtime_of() { stat -f %m "$1"; }; fi

# Absolute path with symlinks resolved where the tools allow; else absolutised (pwd -P).
canon() { readlink -f "$1" 2>/dev/null || (cd "$(dirname "$1")" 2>/dev/null && printf '%s/%s\n' "$(pwd -P)" "$(basename "$1")"); }

# The file the daemon is actually executing, when the seat can tell us (systemd + /proc).
# Empty when unknown; a non-systemd seat states it with HESTIA_BIN instead.
daemon_exe() {
  command -v systemctl >/dev/null 2>&1 || return 0
  local pid
  pid="$(systemctl --user show "$UNIT" -p MainPID --value 2>/dev/null || true)"
  [ -n "$pid" ] && [ "$pid" -gt 0 ] 2>/dev/null || return 0
  readlink "/proc/$pid/exe" 2>/dev/null | sed 's/ (deleted)$//' || true
}

# ONE restart, used by the deploy AND the rollback (a port that fixes only the first leaves
# rollback unable to bring the old binary back).
restart_daemon() { log "restart: $RESTART_CMD"; eval "$RESTART_CMD"; }

# ---- one at a time -----------------------------------------------------------------------
# A lock primitive that is not there must never be indistinguishable from a lock that is held.
# `flock -n 9 || exit 0` on a seat without flock turned rc=127 "command not found" into a SKIP
# at rc=0 on every cycle, forever, with a log line that read like healthy mutual exclusion.
mkdir -p "$HESTIA_HOME"
LOCKD="$HESTIA_HOME/deploy.lock.d"
take_lockd() {
  mkdir "$LOCKD" 2>/dev/null || return 1
  echo $$ >"$LOCKD/pid"
  trap 'rm -f "$LOCKD/pid"; rmdir "$LOCKD" 2>/dev/null' EXIT
}
if command -v flock >/dev/null 2>&1; then
  exec 9>"$HESTIA_HOME/deploy.lock"
  flock -n 9 || { log "SKIP another deploy holds the lock ($HESTIA_HOME/deploy.lock)"; exit 0; }
elif ! take_lockd; then
  # mkdir is atomic everywhere; a holder killed without running its trap is reaped by pid.
  holder="$(cat "$LOCKD/pid" 2>/dev/null || true)"
  if [ -n "$holder" ] && kill -0 "$holder" 2>/dev/null; then
    log "SKIP another deploy holds the lock (pid $holder, $LOCKD)"; exit 0
  fi
  log "stale lock $LOCKD (holder '${holder:-unknown}' not running); reclaiming"
  rm -f "$LOCKD/pid"; rmdir "$LOCKD" 2>/dev/null || true
  take_lockd || { log "SKIP another deploy holds the lock ($LOCKD)"; exit 0; }
fi

# ---- operator hold -----------------------------------------------------------------------
if [ -e "$HOLD" ]; then
  age=$(( $(date +%s) - $(mtime_of "$HOLD") ))
  if [ "$age" -lt "$HOLD_MAX_SECS" ]; then
    log "SKIP hold present (${age}s old, expires at ${HOLD_MAX_SECS}s): $(head -c 200 "$HOLD" | tr '\n' ' ')"
    exit 0
  fi
  log "hold present but expired (${age}s); proceeding"
fi

# ---- sync the deploy checkout and its sibling --------------------------------------------
[ -d "$DEPLOY_ROOT/hestia/.git" ] || die "no deploy checkout at $DEPLOY_ROOT/hestia (see README)"
[ -d "$DEPLOY_ROOT/web4/.git" ]   || die "no web4 sibling at $DEPLOY_ROOT/web4 (see README)"
git -C "$DEPLOY_ROOT/hestia" fetch -q --tags origin || die "fetch hestia"
git -C "$DEPLOY_ROOT/hestia" reset -q --hard "origin/$BRANCH" || die "reset hestia"
git -C "$DEPLOY_ROOT/hestia" clean -qfd
git -C "$DEPLOY_ROOT/web4" fetch -q origin || die "fetch web4"
git -C "$DEPLOY_ROOT/web4" reset -q --hard origin/main || die "reset web4"
git -C "$DEPLOY_ROOT/web4" clean -qfd

target="$(git -C "$DEPLOY_ROOT/hestia" describe --tags --always)"
target_sha="$(git -C "$DEPLOY_ROOT/hestia" rev-parse --short HEAD)"
web4_sha="$(git -C "$DEPLOY_ROOT/web4" rev-parse --short HEAD)"
running="$(running_version)"
ondisk="$("$BIN" --version 2>/dev/null | describe_of || true)"
log "target=$target ($target_sha, web4 $web4_sha) running=${running:-none} ondisk=${ondisk:-none}"

# BIN must be the file the daemon execs. Otherwise one cycle installs to a path nothing
# launches, restarts the OLD binary, sees the old version, and "rolls back" a file nobody runs
# (mcnugget: default ~/.local/bin/hestia vs a launchd plist exec'ing /opt/homebrew/bin/hestia).
[ -f "$BIN" ] || die "no daemon binary at $BIN; set HESTIA_BIN to the file the daemon execs"
exe="$(daemon_exe)"
if [ -n "$exe" ] && [ "$(canon "$exe")" != "$(canon "$BIN")" ]; then
  die "BIN=$BIN but the daemon ($UNIT) is executing $exe; set HESTIA_BIN to that path"
fi

# The script keeps itself current from the checkout it deploys (units run the installed copy).
if [ -f "$DEPLOY_ROOT/hestia/deploy/from-main/hestia-deploy.sh" ] && \
   ! cmp -s "$DEPLOY_ROOT/hestia/deploy/from-main/hestia-deploy.sh" "$SELF_INSTALL"; then
  install -m 0755 "$DEPLOY_ROOT/hestia/deploy/from-main/hestia-deploy.sh" "$SELF_INSTALL.new" && \
    mv -f "$SELF_INSTALL.new" "$SELF_INSTALL" && log "self-updated $SELF_INSTALL from $target"
fi

if [ "$running" = "$target" ] && [ "$ondisk" = "$target" ]; then
  log "CURRENT $target"
  exit 0
fi
if [ "$MODE" = "--check" ]; then
  log "STALE running=${running:-none} ondisk=${ondisk:-none} target=$target"
  exit 3
fi

# ---- build ----------------------------------------------------------------------------------
log "build $target (release, target dir $CARGO_TARGET_DIR)"
if ! (cd "$DEPLOY_ROOT/hestia/core" && cargo build --release --locked -p hestia 2>&1 | tail -20 >&2); then
  die "cargo build"
fi
new="$CARGO_TARGET_DIR/release/hestia"
[ -x "$new" ] || die "no binary at $new"
newv="$("$new" --version | describe_of)"
[ "$newv" = "$target" ] || die "built binary describes itself as '$newv', checkout is '$target'"
log "built $newv in $(( $(date +%s) - T0 ))s"
[ "$MODE" = "--build-only" ] && { log "BUILD-ONLY done"; exit 0; }

# ---- install + restart, with rollback ---------------------------------------------------------
prev="$HESTIA_HOME/hestia.prev-$(date +%Y%m%d-%H%M%S)"
[ -f "$BIN" ] && cp -f "$BIN" "$prev"
install -m 0755 "$new" "$BIN.new" && mv -f "$BIN.new" "$BIN" || die "install $BIN"
log "installed $newv (previous saved as $(basename "$prev"))"

# Restore the saved binary and restart on it. Reached from a failed restart as well as from a
# daemon that came back on the wrong version; before, a failed restart died with the new file
# already in place and nothing put the old one back.
rollback() {
  log "$1; rolling back"
  if [ -f "$prev" ]; then
    install -m 0755 "$prev" "$BIN.new" && mv -f "$BIN.new" "$BIN"
    restart_daemon || true
    log "rolled back to $(basename "$prev"): running=$(running_version)"
  else
    log "no previous binary to roll back to"
  fi
  die "deploy $newv"
}
restart_daemon || rollback "restart failed ($RESTART_CMD)"

deadline=$(( $(date +%s) + READY_SECS ))
got=""
while [ "$(date +%s)" -lt "$deadline" ]; do
  got="$(running_version)"
  [ "$got" = "$newv" ] && break
  sleep 3
done
[ "$got" = "$newv" ] || rollback "daemon did not answer as $newv within ${READY_SECS}s (got '${got:-none}')"
log "daemon up on $newv after $(( $(date +%s) - T0 ))s"

# ---- members' governance surface, from the SAME checkout -----------------------------------------
hooks="skipped"
if [ "${HESTIA_DEPLOY_HOOKS:-1}" = "1" ] && [ -x "$DEPLOY_ROOT/hestia/deploy/install-members.sh" ]; then
  if HESTIA_HOME="$HESTIA_HOME" bash "$DEPLOY_ROOT/hestia/deploy/install-members.sh" >>"$LOG" 2>&1; then
    hooks="ok"
  else
    hooks="FAILED(rc=$?)"   # daemon is up; the manifest was not rewritten, so it now reads stale
  fi
fi

# ---- prune old backups (newest KEEP_BACKUPS stay) -----------------------------------------------------
ls -1t "$HESTIA_HOME"/hestia.prev-* 2>/dev/null | tail -n +"$(( KEEP_BACKUPS + 1 ))" | while read -r f; do
  rm -f -- "$f"
done

log "DEPLOYED ${running:-none} -> $newv (hestia $target_sha, web4 $web4_sha) hooks=$hooks in $(( $(date +%s) - T0 ))s"
