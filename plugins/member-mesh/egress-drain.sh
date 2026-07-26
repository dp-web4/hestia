#!/usr/bin/env bash
# egress-drain — the forwarding plane's write side (r6-routing branch 2).
#
# Takes notices the daemon routed to `peer/member` and hands them to the fleet mesh
# via hub-notify, forwarding on the row's roster-validated LCT. Marks each row
# forwarded only after hub-notify EXITS ZERO — the send-succeeded-means-delivered
# defect this whole thread exists to remove — and marks it FAILED when it does not,
# so a refused kind or an unreachable hub burns an attempt against the daemon's
# bound and is eventually retired with a report to its sender, instead of retrying
# in silence forever (Kimi, r6-routing branch-2 review §1, 2026-07-26).
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
# The identity the drain acts as. `hestia_egress_pending` requires an attributed
# caller on every arm — marking a row failed retires another member's outbound
# mail, and the retirement is witnessed with this name (`retired_by`). Matches
# the `from_plugin` the router already reports under.
PLUGIN="${EGRESS_DRAIN_PLUGIN:-hestia-router}"
mkdir -p "$(dirname "$LOG")"
say() { echo "[$(date -u +%FT%TZ)] $*" | tee -a "$LOG"; }

rpc() { # rpc <tool> <json-args>  -> prints the tool's JSON result
  python3 - "$1" "$2" "$ENDPOINT" "$PLUGIN" <<'PY'
import json, sys, urllib.request
name, args, ep, plugin = sys.argv[1], json.loads(sys.argv[2]), sys.argv[3], sys.argv[4]
def post(body, hdrs=None):
    r = urllib.request.Request(ep, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream", **(hdrs or {})})
    resp = urllib.request.urlopen(r, timeout=15)
    return resp.read().decode(), resp.headers.get("mcp-session-id")
def call(h, tool, a):
    body, _ = post({"jsonrpc":"2.0","id":2,"method":"tools/call",
                    "params":{"name":tool,"arguments":a}}, h)
    for line in body.splitlines():
        if line.startswith("data: {"):
            return json.loads(json.loads(line[6:])["result"]["content"][0]["text"])
    return None
_, sid = post({"jsonrpc":"2.0","id":1,"method":"initialize","params":{
    "protocolVersion":"2024-11-05","capabilities":{},
    "clientInfo":{"name":"egress-drain","version":"1"}}})
h = {"mcp-session-id": sid} if sid else {}
post({"jsonrpc":"2.0","method":"notifications/initialized","params":{}}, h)
# Attribution is proven, not inherited: the drain must say who it is before it
# may read the forwarding queue or retire anyone's mail.
c = call(h, "hestia_connect", {"plugin_id": plugin, "host_agent": "egress-drain",
                               "instance_name": f"drain-{plugin}"}) or {}
s = c.get("sessionId") or c.get("session_id")
if not s:
    print({"error": "connect failed", "detail": c}); raise SystemExit(1)
args["session_id"] = s
print(call(h, name, args))
PY
}

drain_once() {
  local pending
  pending="$(rpc hestia_egress_pending '{"limit":25}' 2>/dev/null)" || return 0
  python3 - "$pending" <<'PY' | while IFS=$'\t' read -r id peer lct kind ptr; do
import ast, sys
try: d = ast.literal_eval(sys.argv[1])
except Exception: sys.exit(0)
for r in d.get("pending", []):
    # The LCT is what goes on the wire; the NAME is carried for the log only.
    print(f"{r['id']}\t{r['dest_peer']}\t{r.get('dest_peer_lct') or ''}"
          f"\t{r['kind']}\t{r.get('pointer_uri') or ''}")
PY
    [ -n "${id:-}" ] || continue
    # Forward on the roster-validated LCT, never on the name: `hub-notify`
    # resolves names by unique PREFIX, so a name changes meaning when an
    # unrelated member joins (McNugget §4). An empty LCT is a defect, not a
    # cue to fall back to the name — falling back is the hazard itself.
    if [ -z "$lct" ]; then
      mark_failed "$id" "no-dest-lct" "$peer" "$kind"
      continue
    fi
    if err="$("$HUB_NOTIFY" "$lct" "$kind" "$ptr" 2>&1 >/dev/null)"; then
      rpc hestia_egress_pending "{\"mark_forwarded\":$id}" >/dev/null 2>&1
      say "FORWARDED id=$id -> $peer ($lct) kind=$kind"
    else
      # Record the failure against the row. Leaving it merely "pending" was the
      # louder-sounding option and the quieter one in fact: `attempts` never
      # incremented, so the bound never fired, `retire_and_report_egress` was
      # unreachable from the only path that could reach it, and a
      # deterministically failing hand-off retried forever in a log nobody
      # reads. A failure the accountability layer cannot see is not visible.
      mark_failed "$id" "$err" "$peer" "$kind"
    fi
  done
}

# Report one failed hand-off to the daemon and say what it decided. The daemon
# owns the bound (MAX_EGRESS_ATTEMPTS) and the receipt; this only reports.
mark_failed() { # mark_failed <id> <raw-reason> <peer> <kind>
  local id="$1" reason kind="$4" peer="$3" out
  # One line, bounded, JSON-safe. The daemon sanitizes again before the reason
  # reaches a pointer; this keeps the RPC itself well-formed.
  reason="$(printf '%s' "$2" | tr -d '\000-\037' | tail -c 120 | sed 's/[\\"]/ /g')"
  [ -n "$reason" ] || reason="hub-notify exited non-zero"
  out="$(rpc hestia_egress_pending \
        "{\"mark_failed\":$id,\"reason\":\"$reason\"}" 2>/dev/null)"
  case "$out" in
    *"'retired'"*) say "RETIRED   id=$id -> $peer kind=$kind ($reason) — sender reported unreachable" ;;
    *)             say "FAILED    id=$id -> $peer kind=$kind ($reason) — $out" ;;
  esac
}

if [ "${1:-}" = "--once" ]; then drain_once; exit 0; fi
say "egress-drain up (poll=${POLL}s, endpoint=$ENDPOINT)"
while true; do drain_once; sleep "$POLL"; done
