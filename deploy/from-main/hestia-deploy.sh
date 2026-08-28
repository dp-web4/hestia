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
# PORTABILITY (mcnugget, macOS/launchd, 2026-08-27): three things in here were Linux, not
# policy. Each is now resolved from `uname` with an env override, rather than forked into a
# second script — the policy is one script, one log, one set of invariants.
#   restart  systemctl --user restart <unit>  |  launchctl kickstart -k gui/<uid>/<label>
#   lock     flock(1)                         |  O_EXCL create, atomic everywhere
#   mtime    stat -c %Y                       |  stat -f %m
# Overrides: HESTIA_RESTART_CMD (wins outright), HESTIA_UNIT, HESTIA_LAUNCHD_LABEL.
# HESTIA_BIN is the fourth seam and it is not cosmetic: mcnugget's daemon agent has always
# executed /opt/homebrew/bin/hestia, so deploying to the default ~/.local/bin would have
# installed a current binary that nothing on that box runs — a deploy that reads green and
# changes nothing, which is the exact failure this script exists to end.
#
# Modes:  (none)        full cycle
#         --check       sync + report currency, no build, no restart, exit 0 current / 3 stale
#         --build-only  sync + build, no install, no restart
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

# An unrecognised argument must never mean "deploy". Before this, `hestia-deploy --version`
# fell through to a full cycle: measured on Legion the same day, where a stray one from a
# sibling session ran as a real deploy and collided with the timer's. (Legion reported the
# same defect against #698 from thread …-6743382a; if that fix lands first, keep whichever
# spelling is there — the requirement is that the default is refusal, not deployment.)
case "$MODE" in
  full|--check|--build-only|--hooks-only) ;;
  *) echo "hestia-deploy: unknown mode '$MODE' (full|--check|--build-only|--hooks-only)" >&2; exit 64 ;;
esac

export CARGO_TARGET_DIR="$DEPLOY_ROOT/target"
export PATH="$HOME/.cargo/bin:$PATH"
T0=$(date +%s)

log() { printf '%s %s\n' "$(date -u +%FT%TZ)" "$*" | tee -a "$LOG" >&2; }
die() { log "FAIL $*"; exit 1; }

# The parenthesised `git describe` string from a version line, e.g.
#   hestia 0.0.4 (v0.0.4-444-gdd4300c)  ->  v0.0.4-444-gdd4300c
describe_of() { grep -oE '\([^)]+\)' | head -1 | tr -d '()'; }

# The restart is the only thing a cycle does that anyone else on the box can see, and it is the
# one line that is not portable. Resolve it ONCE, here, so the rollback arm below is guaranteed
# to restart the same way the deploy did — a rollback that cannot restart is not a rollback.
case "$(uname -s)" in
  Darwin) DEFAULT_RESTART="launchctl kickstart -k gui/$(id -u)/$LAUNCHD_LABEL" ;;
  *)      DEFAULT_RESTART="systemctl --user restart $UNIT" ;;
esac
RESTART_CMD="${HESTIA_RESTART_CMD:-$DEFAULT_RESTART}"
restart_daemon() { eval "$RESTART_CMD"; }

# GNU stat spells mtime `-c %Y`, BSD stat spells it `-f %m`, and neither accepts the other's
# flag. Try, fall back; if both fail the caller gets an empty string and the arithmetic that
# uses it fails loudly rather than treating a hold as infinitely old.
mtime_of() { stat -c %Y "$1" 2>/dev/null || stat -f %m "$1" 2>/dev/null; }

# Invariant #1 of deploy/install-members.sh ("derive the target from the REGISTRATION; never
# assume it"), applied to the binary. This WARNS and never redirects the install: a wrong
# auto-derivation would deploy to a path nobody chose, which is worse than the mismatch. But an
# unnoticed mismatch is a deploy that logs DEPLOYED, reads green on the dashboard, and changes
# nothing that actually runs — so it must not be silent. mcnugget is the live case: its daemon
# agent executes /opt/homebrew/bin/hestia, not the ~/.local/bin default.
# deploy/install-members.sh uses `declare -A` (associative arrays) and `mapfile`, both bash 4
# builtins. macOS ships bash 3.2.57 as /bin/bash and nothing newer -- Apple froze it at the
# last GPLv2 release -- so on a stock Mac the members' install dies with
#   install-members.sh: line 189: syntax error near unexpected token `('
# which names neither the cause nor the fix. Resolve an interpreter that can actually run it,
# and when there is none, SAY SO instead of emitting that.
#
# Measured on mcnugget 2026-08-27: this is why ~/.hestia/current-build.json had never once
# been written on that box. Its dashboard row read "deployment: unknown" from the beginning,
# and the reason was four lines of bash 4 syntax nobody had a macOS box to trip over.
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

# Sets $hooks. Kept as a function because --hooks-only needs the same path: a cycle that
# deployed the binary and then failed the manifest leaves the box reading STALE, and nothing
# retries it -- the next cycle sees a current binary, logs CURRENT and exits before reaching
# here. Recovering that took a re-deploy until this existed.
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

registered_bin() {
  case "$(uname -s)" in
    Darwin) launchctl print "gui/$(id -u)/$LAUNCHD_LABEL" 2>/dev/null \
              | awk -F' = ' '$1 ~ /^[[:space:]]*program$/ { print $2; exit }' ;;
    *)      systemctl --user show "$UNIT" -p ExecStart --value 2>/dev/null \
              | sed -n 's/.*path=\([^ ;]*\).*/\1/p' | head -1 ;;
  esac
}

running_version() {
  curl -s -m 10 -X POST "$EP" \
    -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
    -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"hestia-deploy","version":"0"}}}' \
    2>/dev/null | tr -d '\r' | grep -o '"serverInfo":{[^}]*}' | describe_of || true
}

# ---- one at a time -----------------------------------------------------------------------
# macOS ships no flock(1). Where flock exists the proven path is untouched; elsewhere the lock
# is an O_EXCL create (`set -o noclobber`), which is atomic on every filesystem this deploys to.
# A lock whose holder is gone is STALE and gets taken: a cycle killed mid-build must not wedge
# the timer silently until a human notices, which is the same failure mode as the expiring hold.
mkdir -p "$HESTIA_HOME"
if command -v flock >/dev/null 2>&1; then
  exec 9>"$HESTIA_HOME/deploy.lock"
  flock -n 9 || { log "SKIP another deploy holds the lock"; exit 0; }
else
  PIDLOCK="$HESTIA_HOME/deploy.lock.pid"
  take_lock() { ( set -o noclobber; echo $$ >"$PIDLOCK" ) 2>/dev/null && trap 'rm -f -- "$PIDLOCK"' EXIT; }
  if ! take_lock; then
    holder="$(cat "$PIDLOCK" 2>/dev/null || true)"
    if [ -n "$holder" ] && kill -0 "$holder" 2>/dev/null; then
      log "SKIP another deploy holds the lock (pid $holder)"; exit 0
    fi
    log "stale lock $PIDLOCK (pid ${holder:-unknown} is gone); taking it"
    rm -f -- "$PIDLOCK"
    take_lock || { log "SKIP could not take $PIDLOCK"; exit 0; }
  fi
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

reg="$(registered_bin || true)"
if [ -n "$reg" ] && [ "$reg" != "$BIN" ]; then
  log "WARN the service manager runs '$reg' but this deploy installs '$BIN'; set HESTIA_BIN=$reg or the deploy changes nothing that runs"
fi

# The script keeps itself current from the checkout it deploys (units run the installed copy).
if [ -f "$DEPLOY_ROOT/hestia/deploy/from-main/hestia-deploy.sh" ] && \
   ! cmp -s "$DEPLOY_ROOT/hestia/deploy/from-main/hestia-deploy.sh" "$SELF_INSTALL"; then
  install -m 0755 "$DEPLOY_ROOT/hestia/deploy/from-main/hestia-deploy.sh" "$SELF_INSTALL.new" && \
    mv -f "$SELF_INSTALL.new" "$SELF_INSTALL" && log "self-updated $SELF_INSTALL from $target"
fi

# Recovery path for a cycle that deployed the binary and then failed the manifest. Runs the
# members' install from the SAME synced checkout, so build_id still matches by construction --
# it just does it without needing main to move again first.
if [ "$MODE" = "--hooks-only" ]; then
  # The manifest's whole value is that build_id equals the binary's version BY CONSTRUCTION.
  # A full cycle gets that for free: it installs the hooks seconds after the binary. This mode
  # runs later, against a checkout that has since been hard-reset to a main that MOVED --
  # measured on mcnugget 2026-08-27, the first use of this flag wrote build_id
  # v0.0.4-485-gc7ec7bd over a daemon running v0.0.4-484-gfb1c849, manufacturing the precise
  # divergence the policy exists to remove. So it refuses unless the synced checkout is still
  # exactly what is deployed, and says to run a full cycle instead.
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
restart_daemon || die "restart failed: $RESTART_CMD"

deadline=$(( $(date +%s) + READY_SECS ))
got=""
while [ "$(date +%s)" -lt "$deadline" ]; do
  got="$(running_version)"
  [ "$got" = "$newv" ] && break
  sleep 3
done
if [ "$got" != "$newv" ]; then
  log "daemon did not answer as $newv within ${READY_SECS}s (got '${got:-none}'); rolling back"
  if [ -f "$prev" ]; then
    install -m 0755 "$prev" "$BIN.new" && mv -f "$BIN.new" "$BIN"
    restart_daemon || true
    log "rolled back to $(basename "$prev"): running=$(running_version)"
  fi
  die "deploy $newv"
fi
log "daemon up on $newv after $(( $(date +%s) - T0 ))s"

# ---- members' governance surface, from the SAME checkout -----------------------------------------
install_hooks

# ---- prune old backups (newest KEEP_BACKUPS stay) -----------------------------------------------------
ls -1t "$HESTIA_HOME"/hestia.prev-* 2>/dev/null | tail -n +"$(( KEEP_BACKUPS + 1 ))" | while read -r f; do
  rm -f -- "$f"
done

log "DEPLOYED ${running:-none} -> $newv (hestia $target_sha, web4 $web4_sha) hooks=$hooks in $(( $(date +%s) - T0 ))s"
