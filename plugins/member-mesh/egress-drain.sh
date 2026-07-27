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
# The identity this drain is attributed under. It appears in every chain entry the
# drain causes, so it is a name a reader can hold responsible — not a member id
# borrowed from whoever happened to start the script.
DRAIN_PLUGIN_ID="${EGRESS_DRAIN_PLUGIN_ID:-egress-drain}"
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

# --- talking to the daemon ----------------------------------------------------
# ATTRIBUTION. `hestia_egress_pending` reads and retires OTHER members' outbound
# mail, so on 2026-07-26 it was hardened to require an attributed caller — a live
# session_id from `hestia_connect`, with no fallback. Correct, and it killed this
# script, which had never sent one. Every call since has been refused.
#
# The refusal was invisible for a reason worth keeping in front of whoever reads
# this next: it arrives as a *successful* JSON-RPC result (`isError: false`)
# carrying an `_hestia_error` envelope. The old parser asked for `pending`, got
# nothing, and looped. "The queue is empty" and "I am structurally forbidden from
# reading the queue" produced byte-identical behaviour and an identical (silent)
# log. The last thing this script ever said was FORWARDED.
#
# So: connect first, pass the session on every call, and treat `_hestia_error` as
# LOUD — never as an empty queue. `rpc` exits non-zero on an error envelope and
# prints it to stderr; callers must check.
rpc() { # rpc <tool> <json-args>  -> prints the tool's JSON result, non-zero on error
  python3 - "$1" "$2" "$ENDPOINT" "$DRAIN_PLUGIN_ID" <<'PY'
import json, sys, urllib.request
name, args, ep, plugin = sys.argv[1], json.loads(sys.argv[2]), sys.argv[3], sys.argv[4]
def post(body, hdrs=None):
    r = urllib.request.Request(ep, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream", **(hdrs or {})})
    resp = urllib.request.urlopen(r, timeout=15)
    return resp.read().decode(), resp.headers.get("mcp-session-id")
def result(body):
    for line in body.splitlines():
        if line.startswith("data: {"):
            return json.loads(json.loads(line[6:])["result"]["content"][0]["text"])
    return None
try:
    _, sid = post({"jsonrpc":"2.0","id":1,"method":"initialize","params":{
        "protocolVersion":"2024-11-05","capabilities":{},
        "clientInfo":{"name":"egress-drain","version":"2"}}})
    h = {"mcp-session-id": sid} if sid else {}
    post({"jsonrpc":"2.0","method":"notifications/initialized","params":{}}, h)
    # The drain is a caller with a name. It retires other members' packets, so the
    # daemon writes WHO into every `egress_forwarded` / `member_notice_unreachable`
    # entry it causes — an anonymous drain would make those records unattributable.
    conn = result(post({"jsonrpc":"2.0","id":2,"method":"tools/call","params":{
        "name":"hestia_connect","arguments":{
            "plugin_id": plugin, "host_agent": "egress-drain",
            "instance_name": "egress-drain"}}}, h)[0]) or {}
    session = conn.get("sessionId") or conn.get("session_id")
    if not session:
        print(f"connect failed, no session: {json.dumps(conn)[:300]}", file=sys.stderr)
        sys.exit(3)
    args["session_id"] = session
    out = result(post({"jsonrpc":"2.0","id":3,"method":"tools/call",
                       "params":{"name":name,"arguments":args}}, h)[0])
except Exception as e:
    print(f"rpc transport error: {e}", file=sys.stderr)
    sys.exit(4)
if out is None:
    print("no result frame in response", file=sys.stderr)
    sys.exit(5)
if isinstance(out, dict) and "_hestia_error" in out:
    # NOT an empty queue. The one conflation this script is being fixed for.
    print(json.dumps(out["_hestia_error"])[:400], file=sys.stderr)
    sys.exit(6)
print(json.dumps(out))
PY
}

drain_once() {
  local pending err
  err="$(mktemp)"
  if ! pending="$(rpc hestia_egress_pending '{"limit":25}' 2>"$err")"; then
    # The failure this script could not previously see. Say it every tick: a drain
    # that cannot READ the queue is not idle, and an operator scanning the log for
    # the last line must not find a FORWARDED from three days ago.
    say "UNREADABLE cannot list the egress queue: $(tr -d '\n' <"$err" | cut -c1-300) \
— nothing was forwarded and nothing was retried. This is NOT an empty queue."
    rm -f "$err"
    return 0
  fi
  rm -f "$err"
  python3 - "$pending" <<'PY' | while IFS=$'\t' read -r id addr is_lct peer kind ptr; do
import json, sys
try: d = json.loads(sys.argv[1])
except Exception: sys.exit(0)
if d.get("unresolved_note"):
    print("", file=sys.stderr)
for r in d.get("pending", []):
    # forward_on is the address the daemon says to use; forward_on_is_lct says
    # whether it is the roster-validated identifier or the prefix-matchable NAME.
    print("\t".join([str(r["id"]), r.get("forward_on") or r["dest_peer"],
                     "lct" if r.get("forward_on_is_lct") else "name",
                     r["dest_peer"], r["kind"], r.get("pointer_uri") or ""]))
PY
    [ -n "${id:-}" ] || continue
    # §1a (Kimi, notice 123): forward on the address the daemon resolved, not on a
    # name this script re-resolves. When the daemon has no LCT for the row it says
    # so, and the fallback to the name is NAMED in the log rather than silent —
    # hub-notify prefix-matches, so a name is an address that can change meaning.
    "$HUB_NOTIFY" "$addr" "$kind" "$ptr" >/dev/null 2>&1; rc=$?
    if [ "$rc" -eq 0 ]; then
      if rpc hestia_egress_pending "{\"mark_forwarded\":$id}" >/dev/null 2>&1; then
        say "FORWARDED id=$id -> $peer on=$is_lct kind=$kind"
      else
        # The hand-off landed but the row is still pending, so the next tick will
        # send it AGAIN. A duplicate is the honest outcome here and the log has to
        # say which one it was; silently swallowing this is how a double-delivery
        # becomes untraceable.
        say "DUPRISK   id=$id -> $peer kind=$kind (hub accepted it, mark_forwarded \
FAILED — this row will be re-sent next tick)"
      fi
    elif [ "$rc" -eq 126 ] || [ "$rc" -eq 127 ]; then
      # 126/127 is bash saying it could not RUN the notifier — it is not the hub's
      # answer, and it is not the peer's fault. Deliberately NOT marked failed: an
      # attempt burned here would walk a healthy peer toward a
      # `member_notice_unreachable` that indicts it for this box's misconfiguration.
      # The row stays, and the operator — not the next tick — is who can clear it.
      say "WEDGED    id=$id -> $peer kind=$kind (cannot invoke $HUB_NOTIFY, rc=$rc — \
CONFIG error, not an unreachable hub; not counted against the peer)"
    else
      # §1b (Kimi, notice 123): report the failure instead of parking it. The old
      # arm logged RETAIN and left the row pending, so `attempts` never incremented,
      # the bound never fired, and the sender was never told — a deterministically
      # failing hand-off retried every 20 seconds forever, visible only in this file,
      # which is a file nobody reads. "Never marked, never dropped" read as a virtue;
      # what it meant was that the failure was visible nowhere a report could see it.
      local outcome
      if outcome="$(rpc hestia_egress_pending \
            "{\"mark_failed\":$id,\"reason\":\"hub-notify rc=$rc\"}" 2>/dev/null)"; then
        say "FAILED    id=$id -> $peer kind=$kind (hub-notify rc=$rc) $(
             printf '%s' "$outcome" | cut -c1-220)"
      else
        say "RETAIN    id=$id -> $peer kind=$kind (hub-notify rc=$rc; and the failure \
could NOT be recorded — the row stays pending and the sender stays uninformed)"
      fi
    fi
  done
}

preflight_notifier
if [ "${1:-}" = "--once" ]; then drain_once; exit 0; fi
say "egress-drain up (poll=${POLL}s, endpoint=$ENDPOINT, hub-notify=$HUB_NOTIFY)"
while true; do drain_once; sleep "$POLL"; done
