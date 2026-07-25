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

# Kimi review 2026-07-24, Finding 4: single watcher per member (a second
# instance would double-fire the same drain cadence), and primers in a private
# 0700 state dir instead of world-writable /tmp — the fired CLI treats the
# primer as its authoritative work list.
STATE="${HESTIA_MESH_STATE:-$HOME/.local/state/hestia-mesh}"
mkdir -p "$STATE/primers" && chmod 700 "$STATE" "$STATE/primers"
exec 9>"$STATE/watch-$PLUGIN.lock"
flock -n 9 || { echo "[hestia-watch] another watcher holds $STATE/watch-$PLUGIN.lock — exiting"; exit 1; }

# A retained primer is this mesh's ONLY record of an undelivered consume-once
# notice, and until now nothing ever read the directory it lands in: two primers
# sat unclaimed for 13h and 23h before anyone looked (CBP 2026-07-25). Say it out
# loud at startup — an alarm no one reads is not an alarm.
for stale in "$STATE"/primers/notice-*.json; do
  [ -e "$stale" ] || break
  echo "[hestia-watch] STALE PRIMER (undelivered notices from a failed fire): $stale"
  python3 -c "import json,sys;d=json.load(open(sys.argv[1]));[print(f\"    id={n.get('id')} {n.get('kind')} from {n.get('from_plugin')} queued={n.get('queued_at','')}: {n.get('pointer_uri','')}\") for n in d.get('notices',[])]" "$stale" 2>/dev/null || true
done

# The unanswered row exists (daemon-side) only if something ASKS on a cadence —
# a queryable quantity nobody queries is the same defect as an alarm written to
# a directory nobody reads (Kimi, 2026-07-25). Two askers, deliberately weak-then-
# strong: the journal announcement below (cheap, but only as good as who reads
# journals), and the merge into every fire primer (guaranteed read, because it
# lands in the woken session's own prompt). What is NOT done: firing a member
# because it owes a response. Auto-waking a CLI is a consequential act; debt is
# not a reason to spend one.
UNANSWERED_EVERY="${UNANSWERED_EVERY:-3600}"   # journal cadence, seconds
STALE_AFTER="${STALE_AFTER:-21600}"            # a notice is stale at 6h unbound

mesh_rpc() {
python3 - "$PLUGIN" "$HOST_AGENT" "$EP" "$1" "${2:-}" <<'PY'
import json, sys, urllib.request
plugin, host_agent, ep, tool, extra = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
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
args = {"session_id": s}
if extra:
    args.update(json.loads(extra))
print(json.dumps(rpc(h, tool, args)))
PY
}

drain() { mesh_rpc hestia_member_inbox; }
unanswered() { mesh_rpc hestia_member_unanswered "{\"older_than_secs\": $STALE_AFTER}"; }

# Render the unanswered rows for a human (journal) or for a fire primer.
announce_unanswered() {
  local OUT; OUT=$(unanswered 2>/dev/null) || return 0
  printf '%s' "$OUT" | python3 -c '
import json,sys
try: d=json.load(sys.stdin)
except Exception: raise SystemExit(0)
for label,key in (("I OWE A RESPONSE","i_owe"),("NOBODY ANSWERED ME","owed_to_me")):
    for n in d.get(key,[]) or []:
        seen = "delivered, unanswered" if n.get("drained_at") else "NEVER PICKED UP"
        print(f"[hestia-watch] UNANSWERED ({label}): id={n.get(\"id\")} {n.get(\"kind\")} "
              f"{n.get(\"from_plugin\")}->{n.get(\"to_plugin\")} [{seen}] queued={n.get(\"queued_at\",\"\")}: "
              f"{n.get(\"pointer_uri\",\"\")}")
' || true
}

announce_unanswered
LAST_ANNOUNCE=$(date +%s)

while true; do
  NOW=$(date +%s)
  if [ $((NOW - LAST_ANNOUNCE)) -ge "$UNANSWERED_EVERY" ]; then
    announce_unanswered
    LAST_ANNOUNCE=$NOW
  fi
  OUT=$(drain || echo '{"total":0}')
  N=$(echo "$OUT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('total',0))" 2>/dev/null || echo 0)
  if [ "$N" -gt 0 ]; then
    PRIMER=$(mktemp "$STATE/primers/notice-XXXXXX.json")
    # The strong asker: fold the member's outstanding debt into the primer, so
    # the question is asked where an answer is possible — inside the wake that
    # is happening anyway. Costs one read; never causes a fire on its own.
    UN=$(unanswered 2>/dev/null || echo '{}')
    printf '%s' "$OUT" | UN="$UN" python3 -c '
import json,os,sys
d=json.load(sys.stdin)
try: u=json.loads(os.environ.get("UN") or "{}")
except Exception: u={}
d["unanswered"]={k:u.get(k,[]) for k in ("i_owe","owed_to_me")}
json.dump(d,sys.stdout)
' > "$PRIMER" 2>/dev/null || echo "$OUT" > "$PRIMER"
    echo "[hestia-watch] $N notice(s) for $PLUGIN -> $PRIMER"
    if [ -n "$FIRE" ]; then
      # Success: primer is spent, remove it. Failure: KEEP it — the drain was
      # consume-once, so the primer is the only copy of the work list.
      if "$FIRE" "$PRIMER"; then
        rm -f "$PRIMER"
      else
        echo "[hestia-watch] fire command failed (notices preserved in $PRIMER)"
      fi
    else
      python3 -c "import json;d=json.load(open('$PRIMER'));[print(f\"  {n['kind']} from {n['from_plugin']}: {n.get('pointer_uri','')}\") for n in d['notices']]"
    fi
  fi
  sleep "$IVL"
done
