#!/usr/bin/env bash
# hestia daemon warm-up — runs as ExecStartPost so the cold first-connect (issue #423: ~4.6-5.7 s,
# PER MEMBER) is paid HERE, inside the restart, never on a member's gate call. Bounded; failure
# is non-fatal (the daemon still serves — members would just meet the cold path as before).
#
# WHO IS WARMED: every member on this box's ROSTER, read at run time — the seat projections the
# daemon renders from the vault, $HESTIA_HOME/seats/<member>.env (one per configured seat;
# `_`-prefixed files are shared, not members). Never a hard-coded list: the list that used to
# sit here named four ids, so a seat added later met the cold path on its first act, and since
# one-gate stage C a cold connect that outlives a short registration is a recorded DENIAL
# ("no verdict, no act"), not a slow allow. HESTIA_WARMUP_MEMBERS (space-separated) replaces the
# roster for a one-off run.
set -u
EP="${HESTIA_ENDPOINT:-http://127.0.0.1:7711/mcp}"
HOME_DIR="${HESTIA_HOME:-}"
if [ -n "${HESTIA_WARMUP_MEMBERS:-}" ]; then
  MEMBERS="$HESTIA_WARMUP_MEMBERS"
else
  MEMBERS=""
  if [ -n "$HOME_DIR" ] && [ -d "$HOME_DIR/seats" ]; then
    for f in "$HOME_DIR"/seats/*.env; do
      [ -f "$f" ] || continue
      m="$(basename "$f" .env)"
      case "$m" in _*) continue ;; esac
      MEMBERS="$MEMBERS $m"
    done
  fi
fi
if [ -z "${MEMBERS// /}" ]; then
  echo "warm-up: no members on the roster (HESTIA_HOME=${HOME_DIR:-unset}); nothing warmed" >&2
  exit 0
fi
python3 - "$EP" $MEMBERS <<'PY' 2>/dev/null
import json, sys, time, urllib.request
ep, members = sys.argv[1], sys.argv[2:]
def post(payload, sid=None, timeout=20):
    h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if sid:
        h["Mcp-Session-Id"] = sid
    r = urllib.request.urlopen(
        urllib.request.Request(ep, json.dumps(payload).encode(), h), timeout=timeout)
    r.read()
    return r.headers.get("Mcp-Session-Id")
t0 = time.time()
for attempt in range(20):
    try:
        sid = post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                               "clientInfo": {"name": "systemd-warmup", "version": "1"}}})
        post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, sid)
        # The call that pays the cold cost — PER PLUGIN (measured: warming claude-code left the
        # codex path cold), so every rostered member. Labeled as the warm-up: honest witness grain.
        for pid in members:
            post({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                  "params": {"name": "hestia_connect",
                             "arguments": {"plugin_id": pid,
                                           "host_agent": "systemd-warmup",
                                           "host_session_id": "systemd-warmup"}}})
        print(f"warm in {time.time()-t0:.1f}s after {attempt+1} attempt(s): {' '.join(members)}")
        break
    except Exception:
        time.sleep(1.5)
PY
exit 0
