#!/usr/bin/env bash
# egress-drain — the forwarding plane's write side (r6-routing branch 2).
#
# Takes notices the daemon routed to `peer/member` and hands them to the fleet mesh
# via hub-notify. Marks each row forwarded only after hub-notify EXITS ZERO, so a
# refused kind or an unreachable hub leaves the row pending and retryable rather
# than silently consumed — the send-succeeded-means-delivered defect this whole
# thread exists to remove.
#
# WHY THIS IS NOT IN hub-watch's LOOP (yet):
#   Thor measured that loop blocked for a median 77s and up to 16 minutes while a
#   fired session runs, because the fire is synchronous. Egress placed behind it
#   inherits that latency, and §3's success test becomes a race. Thor is taking the
#   concurrency fix (background the fire with a cap); once it lands, this belongs in
#   the watcher loop as originally proposed and this script goes away.
#
# Usage:  egress-drain.sh [--once]     (default: loop with POLL seconds)
set -uo pipefail
POLL="${EGRESS_DRAIN_POLL:-20}"
ENDPOINT="${HESTIA_ENDPOINT:-http://127.0.0.1:7711/mcp}"
HUB_MESH_ENV="${HUB_MESH_ENV:-$HOME/.config/hub-mesh.env}"
LOG="${EGRESS_DRAIN_LOG:-$HOME/.local/state/hestia-mesh/egress-drain.log}"
mkdir -p "$(dirname "$LOG")"
say() { echo "[$(date -u +%FT%TZ)] $*" | tee -a "$LOG"; }

# --- locating hub-notify ------------------------------------------------------
# This used to be one hardcoded default, the WSL layout. The fleet has three:
# WSL /mnt/c/exe/projects/ai-agents/..., Legion ~/ai-workspace/..., Darwin
# ~/repos/.... On any host but the first, that default named a path that does not
# exist, bash returned 127, and 127 is non-zero, so the row took the RETAIN arm
# below and logged "still pending" — every tick, forever. A misconfiguration that
# can never succeed was rendered in the log as patience, and the queue only grows.
#
# Resolution order: explicit env wins; then whatever the host's hub-mesh.env
# declares (the same file hub-notify.sh itself reads, so a host that has already
# configured the mesh does not configure it twice); then the known layouts.
resolve_hub_notify() {
  local c
  if [ -n "${HUB_NOTIFY:-}" ]; then printf '%s' "$HUB_NOTIFY"; return; fi
  if [ -r "$HUB_MESH_ENV" ]; then
    # Subshell: the env file is a fleet config, not our namespace to inherit.
    c="$( . "$HUB_MESH_ENV" >/dev/null 2>&1; printf '%s' "${HUB_NOTIFY:-}" )"
    if [ -n "$c" ]; then printf '%s' "$c"; return; fi
  fi
  for c in "$HOME/repos/private-context/hub-mesh/hub-notify.sh" \
           "$HOME/ai-workspace/private-context/hub-mesh/hub-notify.sh" \
           "/mnt/c/exe/projects/ai-agents/private-context/hub-mesh/hub-notify.sh"; do
    if [ -x "$c" ]; then printf '%s' "$c"; return; fi
  done
  printf '%s' ""
}
HUB_NOTIFY="$(resolve_hub_notify)"

# Refuse to drain against a notifier we cannot invoke. An absent or non-executable
# hub-notify is a CONFIG error, not an unreachable hub: no number of retries fixes
# it, so looping parks every forward while reporting patience. Exiting non-zero
# (78 = EX_CONFIG) puts the failure where a supervisor and an operator can see it.
# The queue is left untouched — nothing is dropped, only the pretence that the
# drain is working.
preflight_notifier() {
  if [ -z "$HUB_NOTIFY" ]; then
    say "CONFIG    no hub-notify found. Set HUB_NOTIFY, or declare it in $HUB_MESH_ENV. \
Not draining: an absent notifier cannot succeed on retry, and treating it as a transient \
failure parks every forward forever while the log reports patience."
    exit 78
  fi
  if [ ! -x "$HUB_NOTIFY" ]; then
    say "CONFIG    hub-notify at $HUB_NOTIFY is not executable. Not draining (same reason)."
    exit 78
  fi
}

rpc() { # rpc <tool> <json-args>  -> prints the tool's JSON result
  python3 - "$1" "$2" "$ENDPOINT" <<'PY'
import json, sys, urllib.request
name, args, ep = sys.argv[1], json.loads(sys.argv[2]), sys.argv[3]
def post(body, hdrs=None):
    r = urllib.request.Request(ep, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream", **(hdrs or {})})
    resp = urllib.request.urlopen(r, timeout=15)
    return resp.read().decode(), resp.headers.get("mcp-session-id")
_, sid = post({"jsonrpc":"2.0","id":1,"method":"initialize","params":{
    "protocolVersion":"2024-11-05","capabilities":{},
    "clientInfo":{"name":"egress-drain","version":"1"}}})
h = {"mcp-session-id": sid} if sid else {}
post({"jsonrpc":"2.0","method":"notifications/initialized","params":{}}, h)
body, _ = post({"jsonrpc":"2.0","id":2,"method":"tools/call",
                "params":{"name":name,"arguments":args}}, h)
for line in body.splitlines():
    if line.startswith("data: {"):
        print(json.loads(json.loads(line[6:])["result"]["content"][0]["text"]))
        break
PY
}

drain_once() {
  local pending
  pending="$(rpc hestia_egress_pending '{"limit":25}' 2>/dev/null)" || return 0
  python3 - "$pending" <<'PY' | while IFS=$'\t' read -r id peer kind ptr; do
import ast, sys
try: d = ast.literal_eval(sys.argv[1])
except Exception: sys.exit(0)
for r in d.get("pending", []):
    print(f"{r['id']}\t{r['dest_peer']}\t{r['kind']}\t{r.get('pointer_uri') or ''}")
PY
    [ -n "${id:-}" ] || continue
    "$HUB_NOTIFY" "$peer" "$kind" "$ptr" >/dev/null 2>&1; rc=$?
    if [ "$rc" -eq 0 ]; then
      rpc hestia_egress_pending "{\"mark_forwarded\":$id}" >/dev/null 2>&1
      say "FORWARDED id=$id -> $peer kind=$kind"
    elif [ "$rc" -eq 126 ] || [ "$rc" -eq 127 ]; then
      # 126/127 is bash saying it could not RUN the notifier — it is not the hub's
      # answer. Preflight catches this at startup; reaching it here means the path
      # went away underneath a running drain. Same disposition as RETAIN (the row
      # stays, nothing is dropped) but named differently, because retrying will not
      # help and the operator, not the next tick, is the one who can clear it.
      say "WEDGED    id=$id -> $peer kind=$kind (cannot invoke $HUB_NOTIFY, rc=$rc — \
CONFIG error, not an unreachable hub; every forward parks until this is fixed)"
    else
      # Left pending on purpose: a refused kind or an unreachable hub is a real
      # failure and must stay visible. Retried next tick; never marked, never dropped.
      say "RETAIN    id=$id -> $peer kind=$kind (hub-notify rc=$rc; still pending)"
    fi
  done
}

preflight_notifier
if [ "${1:-}" = "--once" ]; then drain_once; exit 0; fi
say "egress-drain up (poll=${POLL}s, endpoint=$ENDPOINT, hub-notify=$HUB_NOTIFY)"
while true; do drain_once; sleep "$POLL"; done
