#!/usr/bin/env bash
# Portable timeout for member-mesh fire scripts.
#
# GNU coreutils `timeout` is not on stock macOS. Prefer a real timeout(1) /
# gtimeout(1) when present (same flags as the fire scripts already use).
# Otherwise python3 bounds the process group the same way. SIGTERM at
# DURATION. Without -k that is the only signal: a command that ignores TERM
# is not force-killed, matching GNU timeout. With -k, SIGKILL follows after
# KILL_AFTER, and that force-kill exits 137 (128+9). The grace wait follows
# the whole group, not only the direct child: a leader that exits on SIGTERM
# must not cancel the scheduled SIGKILL while a descendant is alive. A TERM
# timeout that does not send KILL exits 124.
#
# Usage (GNU-compatible subset):
#   mesh-timeout.sh DURATION COMMAND [ARG...]
#   mesh-timeout.sh -k KILL_AFTER DURATION COMMAND [ARG...]
set -u

KILL_AFTER=""
if [[ "${1:-}" == "-k" ]]; then
  KILL_AFTER="${2:?mesh-timeout: -k needs a kill-after duration}"
  shift 2
fi
DURATION="${1:?mesh-timeout: duration required}"
shift
[[ $# -ge 1 ]] || { echo "mesh-timeout: command required" >&2; exit 125; }

# Prefer an installed GNU-compatible timeout. Detect -k support so a BSD-ish
# stub cannot silently drop the kill-after bound the fire scripts rely on.
pick_timeout() {
  local cand
  for cand in timeout gtimeout; do
    command -v "$cand" >/dev/null 2>&1 || continue
    if [[ -n "$KILL_AFTER" ]]; then
      "$cand" -k 1 1 true >/dev/null 2>&1 || continue
    fi
    # Reject macOS/Homebrew wrappers that are not GNU when -k is unused too:
    # a binary named timeout that cannot parse a numeric duration is useless.
    "$cand" 1 true >/dev/null 2>&1 || continue
    printf '%s\n' "$cand"
    return 0
  done
  return 1
}

if TOOL="$(pick_timeout)"; then
  if [[ -n "$KILL_AFTER" ]]; then
    exec "$TOOL" -k "$KILL_AFTER" "$DURATION" "$@"
  fi
  exec "$TOOL" "$DURATION" "$@"
fi

command -v python3 >/dev/null 2>&1 || {
  echo "mesh-timeout: no timeout/gtimeout and no python3 — cannot bound the command" >&2
  exit 125
}

export MESH_TIMEOUT_DURATION="$DURATION"
export MESH_TIMEOUT_KILL_AFTER="${KILL_AFTER:-}"
exec python3 - "$@" <<'PY'
import os, signal, subprocess, sys, time

duration = float(os.environ["MESH_TIMEOUT_DURATION"])
kill_after = os.environ.get("MESH_TIMEOUT_KILL_AFTER") or ""
cmd = sys.argv[1:]

# New session so SIGTERM/SIGKILL reach the whole tree the CLI may spawn,
# matching GNU timeout's process-group behaviour.
try:
    proc = subprocess.Popen(cmd, start_new_session=True)
except OSError as e:
    # 126 cannot invoke, 127 not found — mirror timeout(1) as closely as we can.
    err = getattr(e, "errno", None)
    if err == 2:  # ENOENT
        sys.exit(127)
    sys.exit(126)

pgid = proc.pid

def _other_members():
    # Only needed when killpg is refused. Absolute path: the fire PATH may
    # not include ps, and a descendant still has to be signaled by pid.
    ps = "/bin/ps" if os.path.exists("/bin/ps") else "/usr/bin/ps"
    try:
        out = subprocess.check_output(
            [ps, "-ax", "-o", "pid=", "-o", "pgid="],
            text=True, stderr=subprocess.DEVNULL,
        )
    except (OSError, subprocess.CalledProcessError):
        return []
    found = []
    for line in out.splitlines():
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            pid_i, pgid_i = int(parts[0]), int(parts[1])
        except ValueError:
            continue
        if pgid_i == pgid and pid_i != pgid:
            found.append(pid_i)
    return found

def signal_group(sig):
    try:
        os.killpg(pgid, sig)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        # macOS: killpg(SIGKILL) raises EPERM when SIGTERM is already
        # tearing the leader down, even though that leader is our child.
        # Signal it directly, then any descendant still in the group.
        sent = False
        for pid in (pgid, *_other_members()):
            try:
                os.kill(pid, sig)
                sent = True
            except (ProcessLookupError, PermissionError):
                pass
        return sent

def group_alive():
    # The leader must already be reaped. A zombie leader still answers
    # killpg and would look like a surviving descendant.
    return signal_group(0)

try:
    rc = proc.wait(timeout=duration)
    sys.exit(rc)
except subprocess.TimeoutExpired:
    pass

signal_group(signal.SIGTERM)
if not kill_after:
    # GNU timeout without --kill-after sends the initial signal and waits.
    # It does not add a SIGKILL. Exit 124 once the direct child has exited.
    while proc.poll() is None:
        try:
            proc.wait(timeout=0.05)
        except subprocess.TimeoutExpired:
            continue
    sys.exit(124)

# proc.wait() only reaps the direct child. If that leader exits on
# SIGTERM while a descendant ignores it, returning here would skip the
# SIGKILL and the descendant would run past the kill deadline.
grace = float(kill_after)
deadline = time.monotonic() + grace
while True:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        break
    if proc.poll() is None:
        try:
            proc.wait(timeout=min(remaining, 0.05))
        except subprocess.TimeoutExpired:
            continue
    if not group_alive():
        sys.exit(124)
    time.sleep(min(0.05, max(0.0, deadline - time.monotonic())))

if proc.poll() is None or group_alive():
    signal_group(signal.SIGKILL)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    # GNU timeout keeps 137 when the command is sent KILL, and uses 124
    # only for the TERM timeout path.
    sys.exit(137)
sys.exit(124)
PY
