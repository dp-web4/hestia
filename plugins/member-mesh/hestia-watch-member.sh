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
# PER-MEMBER NAMESPACE (2026-07-31). Primers used to live in ONE directory for every
# member on the host, named `notice-XXXXXX.json` by mktemp and recording `from_plugin`
# on each notice and the recipient NOWHERE. The stale-retry loop below then globbed that
# whole directory and re-fired whatever it found through its own $FIRE — so which member
# received a retained work list was decided by whichever watcher's glob got there first.
# On 2026-07-31 that fired Codex's mail (notice 215, and Codex's own debt report) into
# Kimi's CLI at 10:35:39 and into Codex's at 10:40:45, both watchers logging DELIVERED for
# the same consume-once list. Kimi could not answer any of it — the daemon correctly
# refuses `member_notify_reply_binding_not_yours` — so the wake was spent on mail its
# reader was structurally barred from clearing.
# The directory is the fix: a file under $PRIMERS is this member's by construction, so
# nothing downstream has to infer an owner that was never written down.
PRIMERS="$STATE/primers/$PLUGIN"
mkdir -p "$PRIMERS" && chmod 700 "$STATE" "$STATE/primers" "$PRIMERS"
exec 9>"$STATE/watch-$PLUGIN.lock"
flock -n 9 || { echo "[hestia-watch] another watcher holds $STATE/watch-$PLUGIN.lock — exiting"; exit 1; }

# A long-running bash process executes the script it began reading at startup; changing
# the file underneath it does not deploy the change and can even leave the process reading
# from a stale byte offset. Record a snapshot of the source bytes at startup, not the
# repository commit: an installed copy or dirty worktree can honestly differ from either
# HEAD or main. Bash does not expose its parsed buffer, so this is explicitly a source
# snapshot rather than a claim that every byte had already been parsed.
WATCH_SOURCE="${BASH_SOURCE[0]}"
watch_source_hash() {
  python3 - "$WATCH_SOURCE" <<'PY'
import hashlib, sys
h = hashlib.sha256()
with open(sys.argv[1], "rb") as fh:
    for chunk in iter(lambda: fh.read(1024 * 1024), b""):
        h.update(chunk)
print(h.hexdigest())
PY
}
WATCH_STARTUP_SHA256="$(watch_source_hash 2>/dev/null || true)"
[[ "$WATCH_STARTUP_SHA256" =~ ^[0-9a-f]{64}$ ]] || WATCH_STARTUP_SHA256="unavailable"
WATCH_STARTED_AT="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
WATCH_CURRENT_SHA256="$WATCH_STARTUP_SHA256"
if [[ "$WATCH_STARTUP_SHA256" =~ ^[0-9a-f]{64}$ ]]; then
  WATCH_ARTIFACT_STATE="ok"
  WATCH_ARTIFACT_REASON="matches-startup"
else
  # A baseline never captured cannot be reconstructed later: a hash obtained after
  # startup says what is on disk NOW, not what this process began executing. Keep
  # this state absorbing for the process lifetime rather than comparing a real hash
  # with the sentinel and reporting a false drift when python becomes available.
  WATCH_ARTIFACT_STATE="unverifiable"
  WATCH_ARTIFACT_REASON="startup-baseline-unavailable"
fi
WATCH_LAST_ALARM_STATE=""

# DAEMON DRIFT (2026-08-03, mesh-vocabulary thread: "landed is three steps short").
# The watcher refuses to run stale bytes of ITSELF (check_artifact_drift above), but
# the daemon had no equivalent: it knows its own build string and never compared it
# to anything. So `hestia_request_scope` sat committed in 7c6ab83 while the running
# daemon (g32486b6, started before the arc) answered every connect with a 29-tool
# surface that did not include it — and F1 (PR #165) sat the same way, merged-green
# and nowhere in effect. The daemon now reports its build provenance on every MCP
# initialize (serverInfo.version carries the same string `--version` prints); the
# comparator below is the checkout this watcher runs from.
# Equality, not ancestry, is the VERDICT: the honest claim is "the running daemon
# was built from these bytes", not a guess about direction — both raw strings ship
# with every verdict so a relying party can draw its own line (inspectable
# evidence, not prescribed trust). A trailing `-dirty` is stripped before
# comparison: a dirty worktree is the normal state of a shared checkout and says
# nothing about when the daemon was built.
# But the REMEDY is directional, and equality cannot supply it. A mismatch has two
# opposite causes: the daemon is behind the checkout (rebuild+restart), or the
# checkout is behind the daemon (pull — rebuilding from it would REGRESS the
# running binary). Observed on CBP the same hour this check was merged: the daemon
# was deployed at f863088 from a clean worktree while the shared checkout every
# watcher runs from sat 11 commits behind and permanently dirty, so an alarm
# reading "rebuild+restart required" was instructing the fleet to walk the daemon
# backwards. So: ancestry is resolved where it CAN be (both sides name a commit
# this checkout has) and reported as the reason, and the imperative follows it.
# Where it cannot, the wording stays neutral rather than guessing.
WATCH_REPO_ROOT="$(cd "$(dirname "$WATCH_SOURCE")/../.." 2>/dev/null && pwd || true)"

daemon_version_string() {
python3 - "$EP" <<'PY'
import json, sys, urllib.request
ep = sys.argv[1]
req = urllib.request.Request(ep,
    data=json.dumps({"jsonrpc":"2.0","id":1,"method":"initialize","params":{
        "protocolVersion":"2024-11-05","capabilities":{},
        "clientInfo":{"name":"hestia-watch","version":"1"}}}).encode(),
    headers={"Content-Type":"application/json",
             "Accept":"application/json, text/event-stream"})
try:
    body = urllib.request.urlopen(req, timeout=3).read().decode()
except Exception:
    raise SystemExit(1)
for line in body.splitlines():
    line = line.strip()
    if line.startswith("data:"):
        line = line[5:].strip()
    if not line.startswith("{"):
        continue
    try:
        d = json.loads(line)
    except Exception:
        continue
    print(d.get("result", {}).get("serverInfo", {}).get("version", ""))
    break
PY
}

drift_direction() {
  # $1=running describe, $2=source describe. Echoes one of daemon-behind-source /
  # source-behind-daemon / differs-from-source. `git describe` ends in `-g<sha>`
  # for any commit past a tag and is a bare sha when the checkout has no tags
  # (CI's depth-1 clone), so accept both shapes. A commit this checkout does not
  # have — an unfetched branch, a stub's invented sha — resolves to no direction,
  # which is a real fourth state and not a licence to pick one.
  local RUN="${1%-dirty}" SRC="${2%-dirty}" A B
  A="${RUN##*-g}"; B="${SRC##*-g}"
  case "$A$B" in *[!0-9a-f]*) return 0 ;; esac
  git -C "$WATCH_REPO_ROOT" cat-file -e "${A}^{commit}" 2>/dev/null || return 0
  git -C "$WATCH_REPO_ROOT" cat-file -e "${B}^{commit}" 2>/dev/null || return 0
  if git -C "$WATCH_REPO_ROOT" merge-base --is-ancestor "$A" "$B" 2>/dev/null; then
    printf 'daemon-behind-source'
  elif git -C "$WATCH_REPO_ROOT" merge-base --is-ancestor "$B" "$A" 2>/dev/null; then
    printf 'source-behind-daemon'
  fi
  # Divergent history (both commits present, neither an ancestor) falls out of
  # the chain having printed nothing, and the caller's `${REASON:-...}` supplies
  # the neutral wording. No explicit `return 0` is needed: an `if` whose every
  # condition tested false and which has no `else` exits 0 by rule, so `set -e`
  # is not waiting here — verified against a real divergent pair rather than
  # assumed in either direction.
}

check_daemon_drift() {
  # $1=refresh re-reads the source describe (startup + hourly announce). The
  # per-pass call skips it: `git describe` on a slow mount (WSL drvfs) costs
  # seconds, and per-pass that stalls the FIRST drain past the point where a
  # watcher looks dead — the daemon's string can only change on a restart, and
  # noticing a moved checkout within the hour is enough.
  local VER PROV SOURCE STATE REASON
  VER="$(daemon_version_string 2>/dev/null || true)"
  if [ "${1:-}" = "refresh" ] || [ -z "${WATCH_DAEMON_SOURCE_RAW:-}" ]; then
    WATCH_DAEMON_SOURCE_RAW="$(git -C "$WATCH_REPO_ROOT" describe --tags --always --dirty 2>/dev/null || true)"
  fi
  SOURCE="$WATCH_DAEMON_SOURCE_RAW"
  case "$VER" in
    *\(*\)) PROV="${VER#*\(}"; PROV="${PROV%\)}" ;;
    *)      PROV="" ;;
  esac

  if [ -z "$VER" ]; then
    # A down daemon is a different, already-visible condition; do not report it
    # as drift.
    STATE="unverifiable"
    REASON="daemon-unreachable"
  elif [ -z "$PROV" ]; then
    # A daemon too old to report its build predates the exposure itself — on a
    # checkout that carries this check, that IS drift, and the alarm is the
    # correct instruction (rebuild+restart).
    STATE="drift"
    REASON="no-build-provenance"
  elif [ "$PROV" = "unknown" ]; then
    STATE="unverifiable"
    REASON="build-provenance-unknown"
  elif [ -z "$SOURCE" ]; then
    STATE="unverifiable"
    REASON="source-not-a-checkout"
  elif [ "${PROV%-dirty}" = "${SOURCE%-dirty}" ]; then
    STATE="ok"
    REASON="matches-source"
  else
    STATE="drift"
    REASON="$(drift_direction "$PROV" "$SOURCE")"
    REASON="${REASON:-differs-from-source}"
  fi

  WATCH_DAEMON_STATE="$STATE"
  WATCH_DAEMON_REASON="$REASON"
  WATCH_DAEMON_RUNNING="${PROV:-unavailable}"
  WATCH_DAEMON_SOURCE="${SOURCE:-unavailable}"

  # Same edge-then-level discipline as check_artifact_drift: the alarm is the
  # transition, the periodic DAEMON line is the gauge that survives rotation.
  if [ "$STATE" = "ok" ]; then
    WATCH_DAEMON_LAST_ALARM_STATE=""
  elif [ "$STATE" != "$WATCH_DAEMON_LAST_ALARM_STATE" ]; then
    if [ "$STATE" = "drift" ]; then
      # The remedy follows the resolved direction. "rebuild+restart" is the right
      # instruction only when the daemon is the stale side; told to a machine whose
      # CHECKOUT is the stale side it walks the daemon backwards, which is the
      # failure this branch exists to not cause.
      local FIX
      case "$REASON" in
        source-behind-daemon) FIX="pull the checkout — the daemon is AHEAD; rebuilding from here would regress it" ;;
        daemon-behind-source) FIX="rebuild+restart required" ;;
        *)                    FIX="direction unresolved — compare the two strings before acting" ;;
      esac
      echo "[hestia-watch] DAEMON DRIFT — $FIX; running=$WATCH_DAEMON_RUNNING source=$WATCH_DAEMON_SOURCE reason=$REASON"
    else
      echo "[hestia-watch] DAEMON UNVERIFIABLE — reason=$REASON running=$WATCH_DAEMON_RUNNING source=$WATCH_DAEMON_SOURCE"
    fi
    WATCH_DAEMON_LAST_ALARM_STATE="$STATE"
  fi
}
WATCH_DAEMON_STATE="unverifiable"
WATCH_DAEMON_REASON="not-yet-checked"
WATCH_DAEMON_RUNNING="unavailable"
WATCH_DAEMON_SOURCE="unavailable"
WATCH_DAEMON_LAST_ALARM_STATE=""

announce_daemon() {
  check_daemon_drift refresh
  echo "[hestia-watch] DAEMON state=$WATCH_DAEMON_STATE reason=$WATCH_DAEMON_REASON running=$WATCH_DAEMON_RUNNING source=$WATCH_DAEMON_SOURCE"
}

announce_artifact() {
  # Re-measure here even though the loop also checks every pass. The periodic line
  # is the level-triggered gauge that survives log rotation; it must never depend on
  # a prior one-shot alarm still being visible.
  check_artifact_drift
  echo "[hestia-watch] ARTIFACT plugin=$PLUGIN state=$WATCH_ARTIFACT_STATE reason=$WATCH_ARTIFACT_REASON startup_sha256=$WATCH_STARTUP_SHA256 disk_sha256=$WATCH_CURRENT_SHA256 started=$WATCH_STARTED_AT"
}

check_artifact_drift() {
  local CURRENT STATE REASON
  CURRENT="$(watch_source_hash 2>/dev/null || true)"
  [[ "$CURRENT" =~ ^[0-9a-f]{64}$ ]] || CURRENT="unavailable"

  if [[ ! "$WATCH_STARTUP_SHA256" =~ ^[0-9a-f]{64}$ ]]; then
    STATE="unverifiable"
    REASON="startup-baseline-unavailable"
  elif [ "$CURRENT" = "unavailable" ]; then
    STATE="unverifiable"
    REASON="disk-hash-unavailable"
  elif [ "$CURRENT" != "$WATCH_STARTUP_SHA256" ]; then
    STATE="drift"
    REASON="differs-from-startup"
  else
    STATE="ok"
    REASON="matches-startup"
  fi

  WATCH_CURRENT_SHA256="$CURRENT"
  WATCH_ARTIFACT_STATE="$STATE"
  WATCH_ARTIFACT_REASON="$REASON"

  # Alarms are edges; the periodic ARTIFACT line above is the level. Remember the
  # last non-ok state rather than a boolean so unverifiable -> drift emits the new,
  # actionable condition once. Returning to ok clears the edge memory.
  if [ "$STATE" = "ok" ]; then
    WATCH_LAST_ALARM_STATE=""
  elif [ "$STATE" != "$WATCH_LAST_ALARM_STATE" ]; then
    if [ "$STATE" = "drift" ]; then
      echo "[hestia-watch] ARTIFACT DRIFT — restart required; startup_sha256=$WATCH_STARTUP_SHA256 disk_sha256=$CURRENT"
    else
      echo "[hestia-watch] ARTIFACT UNVERIFIABLE — reason=$REASON startup_sha256=$WATCH_STARTUP_SHA256 disk_sha256=$CURRENT"
    fi
    WATCH_LAST_ALARM_STATE="$STATE"
  fi
}

announce_artifact
announce_daemon

# A retained primer is this mesh's ONLY record of an undelivered consume-once
# notice, and until now nothing ever read the directory it lands in: two primers
# sat unclaimed for 13h and 23h before anyone looked (CBP 2026-07-25). Say it out
# loud at startup — an alarm no one reads is not an alarm.
# ...and then RETRY it. Announcing was only half the fix: for a day this loop said
# STALE PRIMER on every restart and nothing ever re-fired, so a batch that failed once was
# stranded permanently. Codex's first four notices — including Thor's answers to Codex's
# own PR — sat that way (2026-07-26). The alarm existed and the recovery did not, which is
# this corpus's recurring defect wearing recovery's clothes.
#
# Bounded, because a poison primer that fails forever must not fire forever: attempts are
# counted in a sidecar, and on exhaustion the primer is SET ASIDE rather than deleted — it
# is the only copy of a consume-once work list.
STALE_MAX_ATTEMPTS="${STALE_MAX_ATTEMPTS:-3}"

# RESCUE THE ALREADY-STRANDED (2026-07-31). When the namespace above landed, the flat
# directory held 24 primers from three members intermixed. They are consume-once work
# lists — the only copy — so they are moved, never dropped.
#
# A member claims ONLY what is provably its own: `for_plugin` if the file has it, else the
# `unanswered` fold, whose `i_owe` rows are addressed TO the owner and whose `owed_to_me`
# rows are FROM it. That is structural, not a guess. Anything that resolves to no owner or
# to more than one is ANNOUNCED AND LEFT ALONE — 7 of the 24 were written by the path where
# the unanswered RPC failed, so they name nobody, and a work list whose owner is unknown
# must not be delivered to a guess. That is the whole defect being fixed.
#
# Claiming only its own also makes this safe on a half-deployed host: watchers are
# long-running and reload nothing (#74), so an un-restarted peer may still be writing flat
# files while this one runs. Touching only what it owns means the two cannot fight.
migrate_flat_primers() {
  local f owner moved=0
  for f in "$STATE"/primers/notice-*.json; do
    [ -e "$f" ] || break
    owner=$(python3 - "$f" <<'PY' 2>/dev/null || true
import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception: print(""); raise SystemExit(0)
who=set()
fp=d.get("for_plugin")
if isinstance(fp,str) and fp:
    who.add(fp)
else:
    u=d.get("unanswered") or {}
    for r in u.get("i_owe") or []:
        if r.get("to_plugin"): who.add(r["to_plugin"])
    for r in u.get("owed_to_me") or []:
        if r.get("from_plugin"): who.add(r["from_plugin"])
print(next(iter(who)) if len(who)==1 else "")
PY
)
    if [ "$owner" = "$PLUGIN" ]; then
      if mv -f "$f" "$PRIMERS/" 2>/dev/null; then
        moved=$((moved + 1))
        if [ -e "$f.attempts" ]; then mv -f "$f.attempts" "$PRIMERS/" 2>/dev/null || true; fi
      fi
    elif [ -z "$owner" ]; then
      echo "[hestia-watch] UNATTRIBUTABLE PRIMER (names no member — left in place rather than delivered to a guess): $f"
    fi
  done
  if [ "$moved" -gt 0 ]; then
    echo "[hestia-watch] rescued $moved stranded primer(s) from the shared directory -> $PRIMERS"
  fi
  return 0
}
migrate_flat_primers

for stale in "$PRIMERS"/notice-*.json; do
  [ -e "$stale" ] || break
  echo "[hestia-watch] STALE PRIMER (undelivered notices from a failed fire): $stale"
  python3 -c "import json,sys;d=json.load(open(sys.argv[1]));[print(f\"    id={n.get('id')} {n.get('kind')} from {n.get('from_plugin')} queued={n.get('queued_at','')}: {n.get('pointer_uri','')}\") for n in d.get('notices',[])]" "$stale" 2>/dev/null || true
  [ -n "$FIRE" ] || continue
  attempts_file="$stale.attempts"
  attempts="$(cat "$attempts_file" 2>/dev/null || echo 0)"
  [[ "$attempts" =~ ^[0-9]+$ ]] || attempts=0
  if [ "$attempts" -ge "$STALE_MAX_ATTEMPTS" ]; then
    echo "[hestia-watch] STALE PRIMER exhausted ($attempts/$STALE_MAX_ATTEMPTS) — set aside: $stale.exhausted"
    mv -f "$stale" "$stale.exhausted" 2>/dev/null && rm -f "$attempts_file"
    continue
  fi
  echo $((attempts + 1)) > "$attempts_file"
  echo "[hestia-watch] RETRYING stale primer (attempt $((attempts + 1))/$STALE_MAX_ATTEMPTS): $stale"
  if "$FIRE" "$stale"; then
    rm -f "$stale" "$attempts_file"
    echo "[hestia-watch] stale primer DELIVERED on retry: $stale"
  else
    rc=$?
    echo "[hestia-watch] stale retry failed rc=$rc (preserved, will retry): $stale"
  fi
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

# THE WATCHER IS NOT THE MEMBER (F3, CBP notice 699/701/702 thread, 2026-08-03).
# `mesh_rpc` connects with the watched member's `plugin_id` and, until now, no
# `role` — so the daemon failed it closed to `role:constellation:member` (PR #66's
# defect, fixed on the member path and never applied to the watcher's own RPC).
# Every act this gateway performed was therefore filed under the member it
# watches, at a role the member did not declare: kimi's trust record carries
# reports kimi never wrote, and on the chain an unreachable report was
# indistinguishable from the member itself replying.
#
# `mesh-worker` is the published role for exactly this capacity
# (`reputation::KNOWN_CONSTELLATION_ROLES`), so declaring it needs no daemon
# change — it turns an ACCIDENTAL discriminator into a designed one. Measured on
# CBP the same day: over the chain's whole member_notice population (695 rows,
# positions 1..89974) all 27 non-delivery reports carried the defaulted `member`
# role, which is why the accident worked; it is still only an accident, because
# `role` is caller-supplied and any member that loses `HESTIA_ROLE` collides with
# it silently. Do NOT build a detector on this field alone (see the note on the
# `#undelivered:` marker at `report_unreachable`) — the durable fix is a reserved
# KIND for a non-delivery report, which is vocabulary work in KINDS.md.
#
# `plugin_id` is still the member's: the watcher genuinely acts on that member's
# mailbox, and a distinct gateway identity is a daemon-side enrolment question.
# Role is the one grain the watcher can correct today, from its own side.
WATCH_ROLE="${HESTIA_WATCH_ROLE:-role:constellation:mesh-worker}"

mesh_rpc() {
python3 - "$PLUGIN" "$HOST_AGENT" "$EP" "$1" "${2:-}" "$WATCH_ROLE" <<'PY'
import json, sys, urllib.request
plugin, host_agent, ep, tool, extra = sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5]
watch_role = sys.argv[6]
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
c = rpc(h, "hestia_connect", {"plugin_id": plugin, "host_agent": host_agent,
                              "instance_name": f"watch-{plugin}", "role": watch_role})
s = c.get("sessionId") or c.get("session_id")
if not s: print(json.dumps({"error": c})); raise SystemExit(1)
# Declaring a role and having it TAKE are different events: an unpublished string
# normalizes to role:constellation:member and the connect succeeds identically, so
# "it connected" never verified the grain (handler.rs: "kimi-code's role repair was
# live-verified by a connect that answers — which it does either way"). The daemon
# echoes the outcome in `roleDeclarationHonored`/`constellationRole`; those are the
# key names to read — a guard spelled `role`/`role_lct` matches nothing the daemon
# sends and never fires, which is how this check was first written here. Verified
# against the live daemon 2026-08-03: mesh-worker comes back honored=true.
# STDERR, never stdout — every caller of mesh_rpc parses stdout as JSON. Older
# daemons omit the field entirely (None); stay quiet rather than warn on all of them.
if c.get("roleDeclarationHonored") is False:
    print(f"[hestia-watch] WARNING: declared role {watch_role} did NOT survive connect "
          f"(daemon reports {c.get('constellationRole')!r}) — this gateway's acts are "
          f"filing under the watched member's grain", file=sys.stderr)
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
        live = n.get("recipient_liveness")
        if live and live != "live": seen += f", recipient {live}"
        # Single quotes inside the expressions, deliberately: this block is
        # already inside a single-quoted shell string, so a backslash-escaped
        # double quote reaches Python as `\"` — a SyntaxError in every version
        # (PEP 701 relaxed quote REUSE, not escapes). It was written that way,
        # and `|| true` swallowed it, so this asker has never printed a line
        # since it shipped. Found 2026-07-26 running the branch-4 vector: this
        # thread keeps finding the same shape, and here the alarm nobody reads
        # turned out to be an alarm that never fired.
        print("[hestia-watch] UNANSWERED ({}): id={} {} {}->{} [{}] queued={}: {}".format(
              label, n.get("id"), n.get("kind"), n.get("from_plugin"),
              n.get("to_plugin"), seen, n.get("queued_at",""), n.get("pointer_uri","")))
' || true
}

# Branch 4 of dp's routing algorithm (shared-context/explorations/
# r6-routing-tcpip-of-trust-2026-07-26): a packet that cannot be delivered
# REPORTS to the sender. Without this, a dead fire and a notice never sent are
# indistinguishable at both ends — the sender's unanswered view reads
# "delivered, unanswered" for mail the member never saw (41 fires / 3 dead /
# all reported success). The report is a `reply` bound to the failed notice:
# reply awaits a disposition, so the failure sits in the SENDER's debt row
# until it acks — reroute, resend, or abandon, and the decision is witnessed.
# A coordination-kind report could be ignored in silence, which is the silent
# drop again one layer up. It is sent under the failed member's own plugin
# identity — and that is the report's remaining dishonesty (CBP review §4,
# 2026-07-26): the daemon derives the instance LCT from plugin_id alone and
# drops `instance_name` on connect, so on the chain an unreachable report is
# indistinguishable from the member itself having replied — the router forging
# the destination's source address, not ICMP. The real fix (a gateway identity
# distinct from the member's) is daemon vocabulary and its own thread; the
# honest-today fix is the one field the watcher fully controls: the pointer
# fragment names the OBSERVER as well as the verdict,
# `#undelivered:fire-rc=3;via=watch-$PLUGIN`. The binding is legal because the
# notice was addressed to this plugin. Two ICMP-style suppressions: never
# report an undelivered report (pointer already carries #undelivered), never
# report an undelivered ack (terminal; its loop-closing happened daemon-side
# at send). A failed report is journaled, never fatal — report generation must
# not kill the router.
# WHY THE FIRE FAILED — the reason was already flowing and was being compressed
# into an integer. `fire-rc=1` spans at least four distinct worlds: out-of-credits
# (a billing state), egress-blocked (the member's harness sandbox eating its own
# return path), timeout (rc=124), and plain usage error. Codex's four-day
# "silence" (notice 160 → 2026-07-31) was spent inside exactly that ambiguity —
# rc=1 was read as a dead fire path when codex had in fact answered 126 of 127
# notices and the sandbox ate every disposition. An exit taxonomy too coarse for
# the decisions being made on it, same shape as `unanswered` collapsing
# *would-not* and *could-not*.
#
# The classifier belongs HERE rather than in the fire log (kimi, notice 564): the
# watcher already tails the log, runs outside every member's sandbox, and needs
# no cooperation from the fired member — which matters precisely in the case
# where the member cannot talk to us at all.
#
# Best-effort and NEVER fatal: an unclassifiable failure reports `why=unknown`,
# which is still strictly more than the bare integer said. This is a diagnostic
# hint, not a verdict — the log remains the evidence, and a wrong hint must not
# be more expensive than no hint, so nothing downstream branches on it.
classify_fire_failure() {
  local RC="$1" PREFIX LOG TAIL
  [ "$RC" = "124" ] && { echo timeout; return 0; }
  PREFIX=$(basename "${FIRE:-}" .sh); PREFIX="${PREFIX#fire-}"
  [ -n "$PREFIX" ] || { echo unknown; return 0; }
  LOG=$(ls -t "$STATE/logs/$PREFIX"-*.log 2>/dev/null | head -1) || LOG=""
  [ -n "$LOG" ] || { echo unknown; return 0; }
  TAIL=$(tail -n 200 "$LOG" 2>/dev/null) || TAIL=""
  if printf '%s' "$TAIL" | grep -qi 'out of credits\|insufficient credit\|quota exceeded'; then
    echo out-of-credits
  elif printf '%s' "$TAIL" | grep -qi 'EPERM\|operation not permitted\|network is unreachable\|connection refused\|urllib\.error'; then
    echo egress-blocked
  elif printf '%s' "$TAIL" | grep -qi 'timed out\|timeout'; then
    echo timeout
  else
    echo unknown
  fi
}

report_unreachable() {
  local PRIMER_FILE="$1" WHY="$2" ROWS ARGS OUT LIVE
  ROWS=$(python3 - "$PRIMER_FILE" "$WHY" "watch-$PLUGIN" <<'PY'
import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception: raise SystemExit(0)
why=sys.argv[2]; via=sys.argv[3]
for n in d.get("notices",[]):
    p=str(n.get("pointer_uri") or "")
    nid=n.get("id"); sender=n.get("from_plugin")
    if n.get("kind")=="ack" or "#undelivered" in p: continue
    if not isinstance(nid,int) or not sender: continue
    # The pointer keeps naming the undelivered CONTENT; the fragment names
    # the routing verdict AND the observer (`;via=watch-$PLUGIN` — the chain
    # cannot otherwise tell gateway from member, CBP review §4). Bytes, not
    # chars — the daemon's bound is bytes.
    # TRUNCATE THE CONTENT NAME, NEVER THE VERDICT (CBP review 2026-07-26,
    # case E): a pointer at the 512-byte MTU is legal, so appending the
    # fragment and then cutting to 512 dropped the `#undelivered` marker for
    # any pointer over 500 bytes — and at exactly 512 the report came out
    # byte-identical to the notice it reported on. The marker is the one-hop
    # visited bit the suppression above reads, so losing it turns suppression
    # off exactly where pointers are longest, and two gateways with failing
    # fires report each other's reports once per poll. A degraded content name
    # is still a lead; a lost verdict is the silent drop this branch exists to
    # remove. The reserved region is the whole fragment, observer included.
    frag=f"#undelivered:{why};via={via}".encode()[:512]
    p=p.encode()[:512-len(frag)].decode(errors="ignore")+frag.decode(errors="ignore")
    print(json.dumps({"to_plugin_id":sender,"kind":"reply",
                      "pointer_uri":p,"in_reply_to":nid}))
PY
) || ROWS=""
  [ -n "$ROWS" ] || return 0
  while IFS= read -r ARGS; do
    [ -n "$ARGS" ] || continue
    if OUT=$(mesh_rpc hestia_member_notify "$ARGS" 2>/dev/null) \
       && printf '%s' "$OUT" | grep -q '"queued_id"' \
       && ! printf '%s' "$OUT" | grep -q '_hestia_error'; then
      # CBP review §5: the report of an unreachable can itself be unreachable —
      # `queued_id` reads like success even when the recipient is a name nothing
      # drains (the id=54 -> thor case). The daemon already says what it knows
      # (recipient_liveness + recipient_note); keep it in the journal so the
      # branch-4 receipt is not the next success-shaped receipt.
      LIVE=$(printf '%s' "$OUT" | python3 -c '
import json,sys
try: d=json.load(sys.stdin)
except Exception: d={}
live=d.get("recipient_liveness") or "unreported"
note=d.get("recipient_note") or ""
print(live+(" — "+note if note else ""))' 2>/dev/null)
      echo "[hestia-watch] UNREACHABLE reported (recipient: ${LIVE:-unreported}): $ARGS"
    else
      echo "[hestia-watch] unreachable-report FAILED (notices remain in $PRIMER_FILE): $ARGS"
    fi
  done <<< "$ROWS"
}

announce_unanswered
LAST_ANNOUNCE=$(date +%s)

while true; do
  check_artifact_drift
  check_daemon_drift
  NOW=$(date +%s)
  if [ $((NOW - LAST_ANNOUNCE)) -ge "$UNANSWERED_EVERY" ]; then
    announce_artifact
    announce_daemon
    announce_unanswered
    LAST_ANNOUNCE=$NOW
  fi
  OUT=$(drain || echo '{"total":0}')
  N=$(echo "$OUT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('total',0))" 2>/dev/null || echo 0)
  if [ "$N" -gt 0 ]; then
    PRIMER=$(mktemp "$PRIMERS/notice-XXXXXX.json")
    # The strong asker: fold the member's outstanding debt into the primer, so
    # the question is asked where an answer is possible — inside the wake that
    # is happening anyway. Costs one read; never causes a fire on its own.
    UN=$(unanswered 2>/dev/null || echo '{}')
    printf '%s' "$OUT" | UN="$UN" FOR_PLUGIN="$PLUGIN" python3 -c '
import json,os,sys
try: d=json.load(sys.stdin)
except Exception: d={}
try: u=json.loads(os.environ.get("UN") or "{}")
except Exception: u={}
d["unanswered"]={k:u.get(k,[]) for k in ("i_owe","owed_to_me")}
# WHO THIS IS FOR — the one fact the primer never stated. It recorded from_plugin on
# every notice and the recipient nowhere, so a misdelivered work list was
# indistinguishable from a correct one by reading it, and the four days between notice
# 160 and the diagnosis were spent without the evidence being on disk anywhere.
# Stamped OUTSIDE the unanswered fold on purpose: the fold is the path that failed on the
# 7 primers nobody could attribute, and an owner that only survives the happy path
# re-creates exactly them.
d["for_plugin"]=os.environ["FOR_PLUGIN"]
json.dump(d,sys.stdout)
' > "$PRIMER" 2>/dev/null || echo "$OUT" > "$PRIMER"
    echo "[hestia-watch] $N notice(s) for $PLUGIN -> $PRIMER"
    if [ -n "$FIRE" ]; then
      # Success: primer is spent, remove it. Failure: KEEP it — the drain was
      # consume-once, so the primer is the only copy of the work list.
      if "$FIRE" "$PRIMER"; then
        rm -f "$PRIMER"
      else
        RC=$?
        WHY=$(classify_fire_failure "$RC")
        echo "[hestia-watch] fire command failed rc=$RC why=$WHY (notices preserved in $PRIMER)"
        report_unreachable "$PRIMER" "fire-rc=$RC;why=$WHY"
      fi
    else
      python3 -c "import json;d=json.load(open('$PRIMER'));[print(f\"  {n['kind']} from {n['from_plugin']}: {n.get('pointer_uri','')}\") for n in d['notices']]"
    fi
  fi
  sleep "$IVL"
done
