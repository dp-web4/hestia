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
#         --hooks-only  re-run the members' install against the deployed binary (recovery for
#                       hooks=FAILED; refuses if main has moved since — see the block below)
# Exit:   0 only when the cycle did everything it claims: CURRENT, SKIP (lock/hold), or DEPLOYED
#         with hooks=ok (or hooks=skipped by explicit HESTIA_DEPLOY_HOOKS=0). DEPLOYED with any
#         other hooks value exits 1 — the binary is live, the manifest is not (see the tail).
#         anything else usage, exit 2, BEFORE the lock is taken (a typo'd flag from a shell
#                       used to run a full cycle: Legion, 2026-08-27)
#
# PORTABILITY (mcnugget, macOS/launchd, 2026-08-27, measured on Darwin through two real
# cycles): four things in here were Linux, not policy. Each resolves from `uname` with an env
# override rather than being forked into a second script — one script, one log, one set of
# invariants.
#   restart  systemctl --user restart <unit>  |  launchctl kickstart -k gui/<uid>/<label>
#   lock     flock(1)                         |  atomic mkdir lock with pid reaping
#   mtime    stat -c %Y                       |  stat -f %m
#   exe      /proc/<MainPID>/exe              |  `launchctl print` -> program =
# Overrides: HESTIA_RESTART_CMD (wins outright), HESTIA_UNIT, HESTIA_LAUNCHD_LABEL, HESTIA_BIN,
# HESTIA_BASH. The invariant that matters: a MISSING primitive fails loudly instead of looking
# like a healthy SKIP. HESTIA_BIN is not cosmetic: mcnugget's daemon agent executes
# /opt/homebrew/bin/hestia, and deploying to the ~/.local/bin default would have installed a
# current binary that nothing on that box runs — a deploy that reads green and changes nothing.
set -euo pipefail

DEPLOY_ROOT="${HESTIA_DEPLOY_ROOT:-$HOME/.hestia/deploy}"
HESTIA_HOME="${HESTIA_HOME:-$HOME/.hestia}"
BRANCH="${HESTIA_DEPLOY_BRANCH:-main}"
BIN="${HESTIA_BIN:-$HOME/.local/bin/hestia}"
SELF_INSTALL="$HOME/.local/bin/hestia-deploy"
EP="${HESTIA_ENDPOINT:-http://127.0.0.1:7711/mcp}"
UNIT="${HESTIA_UNIT:-hestia.service}"
LAUNCHD_LABEL="${HESTIA_LAUNCHD_LABEL:-com.web4.hestia.daemon}"
LOG="$HESTIA_HOME/deploy.log"
HOLD="$HESTIA_HOME/deploy.hold"
HOLD_MAX_SECS="${HESTIA_DEPLOY_HOLD_MAX_SECS:-21600}"
KEEP_BACKUPS="${HESTIA_DEPLOY_KEEP_BACKUPS:-5}"
READY_SECS="${HESTIA_DEPLOY_READY_SECS:-120}"
MODE="${1:-full}"
case "$MODE" in
  full|--check|--build-only|--hooks-only) ;;
  *) echo "usage: hestia-deploy [--check|--build-only|--hooks-only]" >&2; exit 2 ;;
esac

# The restart is the only thing a cycle does that anyone else on the box can see, and it is
# the one line that is not portable. Resolved ONCE, here, so the rollback arm below restarts
# the same way the deploy did — a rollback that cannot restart is not a rollback.
OS="$(uname -s)"
case "$OS" in
  Darwin) DEFAULT_RESTART="launchctl kickstart -k gui/$(id -u)/$LAUNCHD_LABEL" ;;
  *)      DEFAULT_RESTART="systemctl --user restart $UNIT" ;;
esac
RESTART_CMD="${HESTIA_RESTART_CMD:-$DEFAULT_RESTART}"

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

# The file the daemon is actually executing, when the seat can tell us: /proc on a systemd
# seat, the agent's registration (`launchctl print` -> `program =`) on launchd. Empty when
# unknown, and an unknown is not a mismatch — the check below only fires on a known exe.
daemon_exe() {
  local pid
  case "$OS" in
    Darwin)
      command -v launchctl >/dev/null 2>&1 || return 0
      launchctl print "gui/$(id -u)/$LAUNCHD_LABEL" 2>/dev/null \
        | awk -F' = ' '$1 ~ /^[[:space:]]*program$/ { print $2; exit }' || true ;;
    *)
      command -v systemctl >/dev/null 2>&1 || return 0
      pid="$(systemctl --user show "$UNIT" -p MainPID --value 2>/dev/null || true)"
      [ -n "$pid" ] && [ "$pid" -gt 0 ] 2>/dev/null || return 0
      readlink "/proc/$pid/exe" 2>/dev/null | sed 's/ (deleted)$//' || true ;;
  esac
}

# ONE restart, used by the deploy AND the rollback (a port that fixes only the first leaves
# rollback unable to bring the old binary back).
restart_daemon() { log "restart: $RESTART_CMD"; eval "$RESTART_CMD"; }

# deploy/install-members.sh uses `declare -A` and `mapfile`, both bash 4 builtins. macOS ships
# bash 3.2.57 as /bin/bash and nothing newer (frozen at the last GPLv2 release), so on a stock
# Mac the members' half of the cycle dies with
#   install-members.sh: line 189: syntax error near unexpected token `('
# which names neither the cause nor the fix. Measured on mcnugget 2026-08-27: this is why
# ~/.hestia/current-build.json had never once been written there and its dashboard row read
# "deployment: unknown" from the beginning. Resolve an interpreter that can run it; when there
# is none, SAY SO instead of emitting that.
bash4() {
  local c v
  for c in "${HESTIA_BASH:-}" bash /opt/homebrew/bin/bash /usr/local/bin/bash; do
    [ -n "$c" ] || continue
    command -v "$c" >/dev/null 2>&1 || continue
    v="$("$c" -c 'echo ${BASH_VERSINFO[0]}' 2>/dev/null)" || v=""
    case "$v" in ''|*[!0-9]*) v=0 ;; esac
    if [ "$v" -ge 4 ]; then command -v "$c"; return 0; fi
  done
  return 1
}

# Sets $hooks. A function because --hooks-only needs the same path: a cycle that deployed the
# binary and then failed the manifest leaves the box reading STALE, and nothing retries it —
# the next cycle sees a current binary, logs CURRENT and exits before reaching here.
install_hooks() {
  local sh
  hooks="skipped"
  [ "${HESTIA_DEPLOY_HOOKS:-1}" = "1" ] || return 0
  [ -x "$DEPLOY_ROOT/hestia/deploy/install-members.sh" ] || { hooks="skipped(no installer)"; return 0; }
  if ! sh="$(bash4)"; then
    hooks="skipped(no bash>=4)"
    log "WARN install-members.sh needs bash>=4 (declare -A, mapfile); the newest here is $(bash --version 2>/dev/null | head -1). Install one (macOS: brew install bash) or point HESTIA_BASH at it; until then the manifest cannot be written and the dashboard reads unknown."
    return 0
  fi
  if HESTIA_HOME="$HESTIA_HOME" "$sh" "$DEPLOY_ROOT/hestia/deploy/install-members.sh" >>"$LOG" 2>&1; then
    hooks="ok"
  else
    hooks="FAILED(rc=$?)"   # daemon is up; the manifest was not rewritten, so it now reads stale
  fi
}

# ---- one at a time -----------------------------------------------------------------------
# A lock primitive that is not there must never be indistinguishable from a lock that is held.
# `flock -n 9 || exit 0` on a seat without flock turned rc=127 "command not found" into a SKIP
# at rc=0 on every cycle, forever, with a log line that read like healthy mutual exclusion
# (mcnugget, measured before the fix: macOS ships no flock(1)).
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
log "target=$target ($target_sha, web4 $web4_sha) running=${running:-none} ondisk=${ondisk:-none} bin=$BIN"

# BIN must be the file the daemon execs. Otherwise one cycle installs to a path nothing
# launches, restarts the OLD binary, sees the old version, and "rolls back" a file nobody runs
# (mcnugget: default ~/.local/bin/hestia vs a launchd plist exec'ing /opt/homebrew/bin/hestia).
# This REFUSES rather than redirecting: a deploy to a path nobody chose is worse than a FAIL
# that names both paths.
[ -f "$BIN" ] || die "no daemon binary at $BIN; set HESTIA_BIN to the file the daemon execs"
exe="$(daemon_exe)"
if [ -n "$exe" ] && [ "$(canon "$exe")" != "$(canon "$BIN")" ]; then
  die "BIN=$BIN but the daemon ($UNIT / $LAUNCHD_LABEL) is executing $exe; set HESTIA_BIN to that path"
fi

# The script keeps itself current from the checkout it deploys (units run the installed copy).
if [ -f "$DEPLOY_ROOT/hestia/deploy/from-main/hestia-deploy.sh" ] && \
   ! cmp -s "$DEPLOY_ROOT/hestia/deploy/from-main/hestia-deploy.sh" "$SELF_INSTALL"; then
  install -m 0755 "$DEPLOY_ROOT/hestia/deploy/from-main/hestia-deploy.sh" "$SELF_INSTALL.new" && \
    mv -f "$SELF_INSTALL.new" "$SELF_INSTALL" && log "self-updated $SELF_INSTALL from $target"
fi

# Recovery path for a cycle that deployed the binary and then failed the manifest: run the
# members' install from the SAME synced checkout, so build_id still matches by construction.
# The manifest's whole value is that build_id equals the binary's version BY CONSTRUCTION; a
# full cycle gets that for free by installing the hooks seconds after the binary. This mode
# runs later, against a checkout that has since been hard-reset to a main that may have MOVED
# — measured on mcnugget 2026-08-27, the first use of this flag wrote build_id
# v0.0.4-485-gc7ec7bd over a daemon running v0.0.4-484-gfb1c849, manufacturing the precise
# divergence the policy exists to remove. So it refuses unless the synced checkout is still
# exactly what is deployed, and says to run a full cycle instead.
if [ "$MODE" = "--hooks-only" ]; then
  if [ "$running" != "$target" ] || [ "$ondisk" != "$target" ]; then
    die "--hooks-only refuses: checkout is now '$target' but running='${running:-none}' ondisk='${ondisk:-none}'; a manifest written here would not match the binary. Run a full cycle."
  fi
  install_hooks
  log "HOOKS-ONLY $target hooks=$hooks"
  [ "$hooks" = "ok" ] || exit 1
  exit 0
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
install_hooks

# ---- prune old backups (newest KEEP_BACKUPS stay) -----------------------------------------------------
ls -1t "$HESTIA_HOME"/hestia.prev-* 2>/dev/null | tail -n +"$(( KEEP_BACKUPS + 1 ))" | while read -r f; do
  rm -f -- "$f"
done

log "DEPLOYED ${running:-none} -> $newv (hestia $target_sha, web4 $web4_sha) hooks=$hooks in $(( $(date +%s) - T0 ))s"

# A DEPLOYED line with hooks != ok is HALF a deploy: the binary is current, the manifest is not,
# and the dashboard reads stale (or unknown) until someone runs --hooks-only. Until 2026-08-27
# that half-deploy exited 0 — a line starting with the word DEPLOYED, a green unit, and the
# README's "nothing else exits 0 without deploying" quietly false (mcnugget: "either the hooks
# failure is fatal, or that sentence is not true"). It is fatal to the CYCLE, not to the binary:
# a rollback here would trade a current daemon for a stale one to repair a manifest, and the
# manifest is exactly what --hooks-only repairs. So the binary stays, the log line still says
# DEPLOYED (it is true), and the cycle exits 1 so the unit reads failed and the tail names why.
# The only hooks value that exits 0 without a manifest is the explicit opt-out
# (HESTIA_DEPLOY_HOOKS=0 -> hooks=skipped); an absent installer or an absent bash>=4 is a
# missing primitive, and a missing primitive does not read as a pass.
case "$hooks" in
  ok|skipped) exit 0 ;;
  *) log "HALF-DEPLOYED $newv: binary current, manifest not written (hooks=$hooks); fix the cause, then hestia-deploy --hooks-only"
     exit 1 ;;
esac
