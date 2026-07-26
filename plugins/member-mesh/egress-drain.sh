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
HUB_MESH_ENV="${HUB_MESH_ENV:-$HOME/.config/hub-mesh.env}"
LOG="${EGRESS_DRAIN_LOG:-$HOME/.local/state/hestia-mesh/egress-drain.log}"
# The identity the drain acts as. `hestia_egress_pending` requires an attributed
# caller on every arm — marking a row failed retires another member's outbound
# mail, and the retirement is witnessed with this name (`retired_by`). Matches
# the `from_plugin` the router already reports under.
PLUGIN="${EGRESS_DRAIN_PLUGIN:-hestia-router}"
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
  # G4 — the field separator is US (0x1f), NOT tab, and the difference is a
  # silent black hole rather than a style preference.
  #
  # Tab is IFS *whitespace*, so `read` collapses a run of tabs into ONE delimiter
  # and an empty field simply disappears. A row with no `dest_peer_lct` — the
  # population the nullable `ALTER TABLE` migration created on every box — emitted
  # `id\tpeer\t\tkind\tptr`, which `read` parsed as four fields with every value
  # after the gap shifted one place left: `lct` took the KIND, `kind` took the
  # POINTER. So the `-z "$lct"` guard below could never fire (it was unreachable
  # dead code), and the drain instead invoked `hub-notify "<kind>" "<pointer>" ""`
  # — forwarding on a destination that is not an LCT, then marking the row
  # FORWARDED on a zero exit. Undelivered mail recorded as delivered, which is the
  # one outcome this whole exploration exists to remove, reached through a shell
  # word-splitting rule.
  #
  # US is not IFS whitespace, so empty fields are preserved positionally. It also
  # cannot occur in any of these values — a control character is rejected by the
  # member-id and pointer rules long before it reaches here.
  #
  # Found by executing the drain against a stub endpoint, not by reading it: the
  # guard reads correctly, greps clean, and passes `bash -n`.
  python3 - "$pending" <<'PY' | while IFS=$'\x1f' read -r id peer lct kind ptr; do
import ast, sys
try: d = ast.literal_eval(sys.argv[1])
except Exception: sys.exit(0)
US = "\x1f"
for r in d.get("pending", []):
    # The LCT is what goes on the wire; the NAME is carried for the log only.
    print(US.join([str(r['id']), str(r['dest_peer']), r.get('dest_peer_lct') or '',
                   str(r['kind']), r.get('pointer_uri') or '']))
PY
    [ -n "${id:-}" ] || continue
    # Forward on the roster-validated LCT, never on the name: `hub-notify`
    # resolves names by unique PREFIX, so a name changes meaning when an
    # unrelated member joins (McNugget §4). An empty LCT is a defect, not a
    # cue to fall back to the name — falling back is the hazard itself.
    if [ -z "$lct" ]; then
      # G1. This arm must NOT `mark_failed`, for the same reason the 126/127 arm
      # below must not: nothing was sent, `hub-notify` was never invoked, the peer
      # was never contacted. `mark_failed` burns an attempt against
      # MAX_EGRESS_ATTEMPTS and on the fifth tick retires the row with a report
      # telling the sender the PEER was unreachable — a defect in MY peer table
      # laundered into witnessed evidence against an innocent member. The rule was
      # already written seven lines down; the row above it did not meet it.
      #
      # Nor does it park: the daemon retires these itself, at zero attempts,
      # through a path whose chain event is `member_notice_undeliverable_local`.
      # So in normal operation this arm is UNREACHABLE — the undeliverable sweep
      # runs inside the same `hestia_egress_pending` call that produced this list,
      # so such a row is retired before it can be handed to us. It stays as
      # defense in depth for an older daemon that has no sweep, where the correct
      # behaviour is still "say it, do not blame anyone for it."
      say "UNSENDABLE id=$id -> $peer kind=$kind (row has no dest_peer_lct — LOCAL \
defect, peer never contacted; no attempt burned, no report about the peer; the \
daemon retires it and tells the sender)"
      continue
    fi
    err="$("$HUB_NOTIFY" "$lct" "$kind" "$ptr" 2>&1 >/dev/null)"; rc=$?
    if [ "$rc" -eq 0 ]; then
      rpc hestia_egress_pending "{\"mark_forwarded\":$id}" >/dev/null 2>&1
      say "FORWARDED id=$id -> $peer ($lct) kind=$kind"
    elif [ "$rc" -eq 126 ] || [ "$rc" -eq 127 ]; then
      # 126/127 is bash saying it could not RUN the notifier — it is not the hub's
      # answer, and it is not evidence about the peer. Preflight catches this at
      # startup; reaching it here means the path went away underneath a running
      # drain.
      #
      # THIS ARM MUST NOT `mark_failed`, and that is the whole reason B5 belongs
      # in this graft rather than beside it. Alone, each branch is safe: McNugget's
      # B5 retains on 127, and the WIP marks failed on any non-zero back when 127
      # only ever meant "the hardcoded WSL path is absent," i.e. cosmetic. Composed
      # naively, 127 reaches `mark_failed`, which burns an attempt against
      # MAX_EGRESS_ATTEMPTS and eventually RETIRES the row with a report telling the
      # sender the PEER was unreachable. The peer was never contacted. A local
      # misconfiguration would be laundered into witnessed evidence against an
      # innocent member — the exact shape of `f8a4d30` ("a deny with no verdict is
      # not evidence about the member"), arriving through the retirement seam.
      #
      # So: same disposition as RETAIN — the row stays, nothing is dropped, no
      # attempt is burned — but named, because retrying cannot help and the
      # operator, not the next tick, is who can clear it.
      say "WEDGED    id=$id -> $peer kind=$kind (cannot invoke $HUB_NOTIFY, rc=$rc — \
CONFIG error, not an unreachable hub; no attempt burned, no report home; every \
forward parks until this is fixed)"
    else
      # A real answer from a notifier we could actually run: a refused kind, or a
      # hub that did not accept. Record it against the row. Leaving it merely
      # "pending" was the louder-sounding option and the quieter one in fact:
      # `attempts` never incremented, so the bound never fired,
      # `retire_and_report_egress` was unreachable from the only path that could
      # reach it, and a deterministically failing hand-off retried forever in a log
      # nobody reads. A failure the accountability layer cannot see is not visible.
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

preflight_notifier
if [ "${1:-}" = "--once" ]; then drain_once; exit 0; fi
say "egress-drain up (poll=${POLL}s, endpoint=$ENDPOINT, hub-notify=$HUB_NOTIFY)"
while true; do drain_once; sleep "$POLL"; done
