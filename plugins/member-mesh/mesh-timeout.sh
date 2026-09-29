#!/usr/bin/env bash
# Portable timeout for member-mesh fire scripts.
#
# GNU coreutils `timeout` is not on stock macOS. Prefer a real timeout(1) /
# gtimeout(1) when present (same flags as the fire scripts already use).
# Otherwise python3 bounds the child the same way: SIGTERM at DURATION, then
# SIGKILL after KILL_AFTER when -k was given.
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
import os, signal, subprocess, sys

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

def kill_tree(sig):
    try:
        os.killpg(proc.pid, sig)
    except ProcessLookupError:
        pass

try:
    rc = proc.wait(timeout=duration)
    sys.exit(rc)
except subprocess.TimeoutExpired:
    kill_tree(signal.SIGTERM)
    grace = float(kill_after) if kill_after else 0.0
    if grace > 0:
        try:
            proc.wait(timeout=grace)
            sys.exit(124)
        except subprocess.TimeoutExpired:
            pass
    kill_tree(signal.SIGKILL)
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    sys.exit(124)
PY
