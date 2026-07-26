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
HUB_NOTIFY="${HUB_NOTIFY:-/mnt/c/exe/projects/ai-agents/private-context/hub-mesh/hub-notify.sh}"
LOG="${EGRESS_DRAIN_LOG:-$HOME/.local/state/hestia-mesh/egress-drain.log}"
mkdir -p "$(dirname "$LOG")"
say() { echo "[$(date -u +%FT%TZ)] $*" | tee -a "$LOG"; }

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
    if "$HUB_NOTIFY" "$peer" "$kind" "$ptr" >/dev/null 2>&1; then
      rpc hestia_egress_pending "{\"mark_forwarded\":$id}" >/dev/null 2>&1
      say "FORWARDED id=$id -> $peer kind=$kind"
    else
      # Left pending on purpose: a refused kind or an unreachable hub is a real
      # failure and must stay visible. Retried next tick; never marked, never dropped.
      say "RETAIN    id=$id -> $peer kind=$kind (hub-notify non-zero; still pending)"
    fi
  done
}

if [ "${1:-}" = "--once" ]; then drain_once; exit 0; fi
say "egress-drain up (poll=${POLL}s, endpoint=$ENDPOINT)"
while true; do drain_once; sleep "$POLL"; done
