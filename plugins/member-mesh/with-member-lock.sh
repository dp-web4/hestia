#!/usr/bin/env bash
# with-member-lock — Amendment 3: the one-session-per-member bound, as law.
#
# Until now that bound was an EMERGENT PROPERTY OF BASH: fire-*.sh ran the CLI in
# the foreground and the watcher called the fire synchronously, so nothing could
# start a second session. Nothing enforced it, nothing tested it, and appending a
# single `&` anywhere on the path removed it silently. Six rounds of the
# atp-metabolism thread flagged this as the oldest open item without closing it.
#
# What the bound is FOR: a fired session is a headless CLI with
# --dangerously-skip-permissions holding the member's own credentials and writing
# the shared working tree. Two of them concurrently is not "twice the throughput"
# — it is two writers on one tree with no coordination (see the fleet's
# shared-working-tree rule) and two agents answering the same drained,
# consume-once notices.
#
# Usage: with-member-lock.sh <plugin_id> <cmd> [args...]
#   Acquires an exclusive per-member lock, then runs <cmd>. The lock is held for
#   the ENTIRE lifetime of <cmd> and anything <cmd> leaves running that inherits
#   fd 9 — which is the semantics we want ("a session is live until its processes
#   are gone"), and also means a leaked background grandchild holds the member
#   busy. That shows up as a lock-wait timeout naming the holder, not as silence.
#
# Env:
#   HESTIA_MESH_LOCK_DIR   default $HOME/.local/state/hestia-mesh/locks
#   HESTIA_FIRE_LOCK_WAIT  seconds to wait for the lock, default 1830
#
# Why 1830 and not 0: the holder is itself bounded by `timeout -k 30 1800` in the
# fire scripts, so it CANNOT outlive ~1830s. Waiting that long therefore
# serializes an honestly-contended fire (no notices stranded) and only refuses
# when the holder has broken its own guarantee — a real anomaly, worth an rc.
#
# Exit codes on refusal are deliberately non-zero and deliberately distinct:
#   75 EX_TEMPFAIL   lock not acquired within the wait — retryable
#   69 EX_UNAVAILABLE  flock(1) missing — fail CLOSED, command NOT run
#   64 EX_USAGE      no command given
# Any non-zero rc reaches hestia-watch-member.sh, which retains the primer rather
# than deleting it — the drain is consume-once, so a refused fire must not eat it.
set -u

PLUGIN="${1:?plugin_id}"; shift
[ "$#" -gt 0 ] || { echo "[mesh-lock] no command given" >&2; exit 64; }

case "$PLUGIN" in
  */*|"") echo "[mesh-lock] refusing plugin id with a path separator: $PLUGIN" >&2; exit 64 ;;
esac

LOCK_DIR="${HESTIA_MESH_LOCK_DIR:-$HOME/.local/state/hestia-mesh/locks}"
mkdir -p "$LOCK_DIR" && chmod 700 "$LOCK_DIR"
LOCK="$LOCK_DIR/fire-$PLUGIN.lock"
HOLDER="$LOCK_DIR/fire-$PLUGIN.holder"
WAIT="${HESTIA_FIRE_LOCK_WAIT:-1830}"

# Fail CLOSED. A missing flock must not degrade to "run it anyway, unbounded" —
# that is exactly the pre-amendment state, and it would be invisible.
command -v flock >/dev/null 2>&1 || {
  echo "[mesh-lock] flock(1) not available — refusing to fire $PLUGIN unbounded" >&2
  exit 69
}

# Append, never truncate: `9>` would blank the file at open() — i.e. BEFORE the
# lock is taken — so a waiter would erase state while the holder still runs.
exec 9>>"$LOCK"

if ! flock -n 9; then
  echo "[mesh-lock] $PLUGIN is already firing; waiting up to ${WAIT}s" >&2
  [ -s "$HOLDER" ] && sed 's/^/[mesh-lock]   holder: /' "$HOLDER" >&2
  if ! flock -w "$WAIT" 9; then
    echo "[mesh-lock] REFUSED: $PLUGIN still locked after ${WAIT}s — the holder has" >&2
    echo "[mesh-lock] outlived its own 1800s timeout. Not starting a second session." >&2
    exit 75
  fi
fi

printf 'pid=%s started=%s cmd=%s\n' "$$" "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$*" > "$HOLDER"
# The LOCK is the invariant; the holder file is forensics only. A stale holder
# file (kill -9) misreports who is running; it cannot admit a second session.
trap 'rm -f "$HOLDER"' EXIT INT TERM

"$@"
RC=$?
exit "$RC"
