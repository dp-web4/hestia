#!/usr/bin/env bash
# hestia-watch-member — the local-mesh wake loop (fractal analog of fleet hub-watch).
#
# Polls the member's hestia inbox; when notices are queued, drains them and fires the
# member's CLI headless with a primer pointing at the notices. DISABLED BY DEFAULT:
# auto-firing a CLI session is a consequential act — enable per-member only with dp's
# sign-off (mirror the fleet hub-watch gates: sender-allowlist + kind + pointer-shape
# + untrusted-data posture + human gate on irreversibles).
#
# Usage: hestia-watch-member.sh <plugin_id> <host_agent> [fire_cmd_template]
#   fire_cmd_template receives the primer file path as $1. Absent -> print-only mode.
# Env: HESTIA_ENDPOINT (default http://127.0.0.1:7711/mcp), WATCH_INTERVAL (default 60s)
set -euo pipefail
PLUGIN="${1:?plugin_id}"; HOST_AGENT="${2:?host_agent}"; FIRE="${3:-}"
EP="${HESTIA_ENDPOINT:-http://127.0.0.1:7711/mcp}"
IVL="${WATCH_INTERVAL:-60}"

drain() {
python3 - "$PLUGIN" "$HOST_AGENT" "$EP" <<'PY'
import json, sys, urllib.request
plugin, host_agent, ep = sys.argv[1], sys.argv[2], sys.argv[3]
def post(payload, hdrs={}):
    req = urllib.request.Request(ep, data=json.dumps(payload).encode(),
        headers={"Content-Type":"application/json","Accept":"application/json, text/event-stream",**hdrs})
    r = urllib.request.urlopen(req, timeout=5); return r.read().decode(), r.headers.get("mcp-session-id")
def rpc(h, name, args):
    body,_ = post({"jsonrpc":"2.0","id":9,"method":"tools/call","params":{"name":name,"arguments":args}}, h)
    for line in body.splitlines():
        if line.startswith("data: {"):
            return json.loads(json.loads(line[6:])["result"]["content"][0]["text"])
_, sid = post({"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"hestia-watch","version":"1"}}})
h = {"mcp-session-id": sid} if sid else {}
post({"jsonrpc":"2.0","method":"notifications/initialized","params":{}}, h)
c = rpc(h, "hestia_connect", {"plugin_id": plugin, "host_agent": host_agent, "instance_name": f"watch-{plugin}"})
s = c.get("sessionId") or c.get("session_id")
if not s: print(json.dumps({"error": c})); raise SystemExit(1)
print(json.dumps(rpc(h, "hestia_member_inbox", {"session_id": s})))
PY
}

while true; do
  OUT=$(drain || echo '{"total":0}')
  N=$(echo "$OUT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('total',0))" 2>/dev/null || echo 0)
  if [ "$N" -gt 0 ]; then
    PRIMER=$(mktemp /tmp/hestia-notice-XXXXXX.json)
    echo "$OUT" > "$PRIMER"
    echo "[hestia-watch] $N notice(s) for $PLUGIN -> $PRIMER"
    if [ -n "$FIRE" ]; then
      "$FIRE" "$PRIMER" || echo "[hestia-watch] fire command failed (notices preserved in $PRIMER)"
    else
      python3 -c "import json;d=json.load(open('$PRIMER'));[print(f\"  {n['kind']} from {n['from_plugin']}: {n.get('pointer_uri','')}\") for n in d['notices']]"
    fi
  fi
  sleep "$IVL"
done
