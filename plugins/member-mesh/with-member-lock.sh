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
#   69 EX_UNAVAILABLE  no lock tool: neither flock(1) nor python3 (fcntl) — fail CLOSED, command NOT run
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

# Fail CLOSED. A missing lock must not degrade to "run it anyway, unbounded".
# macOS has no flock(1). python3 fcntl.flock is the same exclusive lock, held
# until the command exits. A PATH with neither tool still refuses.
if ! command -v flock >/dev/null 2>&1; then
  command -v python3 >/dev/null 2>&1 || {
    echo "[mesh-lock] no lock tool (neither flock(1) nor python3) — refusing to fire $PLUGIN unbounded" >&2
    exit 69
  }
  exec python3 - "$LOCK" "$WAIT" "$HOLDER" "$PLUGIN" "$@" <<'PY'
import os
import sys
import time

try:
    import fcntl
except ImportError:
    sys.stderr.write("[mesh-lock] no lock tool (flock(1) missing, python3 has no fcntl) — refusing to fire unbounded\n")
    sys.exit(69)

path, wait_s, holder, plugin = sys.argv[1], float(sys.argv[2]), sys.argv[3], sys.argv[4]
cmd = sys.argv[5:]
fd = os.open(path, os.O_RDWR | os.O_CREAT | os.O_APPEND, 0o600)
started = time.time()
told = False
while True:
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        break
    except OSError:
        if not told:
            sys.stderr.write("[mesh-lock] %s is already firing; waiting up to %ss\n" % (plugin, wait_s))
            try:
                with open(holder) as handle:
                    for line in handle:
                        if line.strip():
                            sys.stderr.write("[mesh-lock]   holder: " + line)
            except OSError:
                pass
            told = True
        if time.time() - started >= wait_s:
            sys.stderr.write("[mesh-lock] REFUSED: %s still locked after %ss — the holder has\n" % (plugin, wait_s))
            sys.stderr.write("[mesh-lock] outlived its own 1800s timeout. Not starting a second session.\n")
            sys.exit(75)
        time.sleep(0.05)
with open(holder, "w") as handle:
    handle.write("pid=%s started=%s cmd=%s\n" % (
        os.getpid(),
        time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        " ".join(cmd),
    ))
# The lock must outlive this wrapper in anything <cmd> leaves running, as `exec 9>>` gives the
# flock(1) path: a leaked background grandchild holds the member busy (header, "Usage"). Python
# opens fds NON-inheritable (PEP 446), and close_fds=False does not change that, so without this
# line the fallback released the member while a child of the fire still ran
# (fire_concurrency_test 8f).
os.set_inheritable(fd, True)
try:
    proc = __import__("subprocess").Popen(cmd, close_fds=False)
    rc = proc.wait()
except FileNotFoundError:
    # bash reports a command it cannot find as 127; do the same instead of a traceback.
    sys.stderr.write("[mesh-lock] %s: command not found\n" % cmd[0])
    rc = 127
try:
    os.remove(holder)
except OSError:
    pass
# A signal death is -N from Popen; report 128+N as bash does, so the watcher sees the same rc.
sys.exit(128 - rc if rc < 0 else rc)
PY
fi

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
