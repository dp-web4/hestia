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
# HANDED DOWN BY A DEPLOYING PREDECESSOR (see maybe_self_deploy). After a self-deploy
# this process is executing a private snapshot under $STATE, but the file the fleet
# DEPLOYS is still the canonical repo path -- so the predecessor passes it, and drift is
# measured against the file operators actually update rather than against our own copy.
WATCH_SOURCE="${HESTIA_WATCH_SOURCE:-${BASH_SOURCE[0]}}"
# Resolved once, from the same source path the drift snapshot above hashes, so a
# helper is loaded from the copy that is actually running rather than from a cwd
# that is nobody's guarantee.
WATCH_DIR="$(cd "$(dirname "$WATCH_SOURCE")" && pwd)"
sha256_file() {
  python3 - "$1" <<'PY'
import hashlib, sys
h = hashlib.sha256()
with open(sys.argv[1], "rb") as fh:
    for chunk in iter(lambda: fh.read(1024 * 1024), b""):
        h.update(chunk)
print(h.hexdigest())
PY
}
watch_source_hash() { sha256_file "$WATCH_SOURCE"; }

# THE BYTES THIS INTERPRETER IS READING, not the bytes at a pathname.
#
# Bash holds the script open on a descriptor for the life of the process and reads the
# not-yet-parsed tail from it, so /proc/<pid>/fd/<n> is the SAME open file description
# bash itself reads -- opening it does not re-resolve the path. Measured on this host:
# replace the script by rename underneath a running process and this fd still hashes the
# ORIGINAL bytes (readlink additionally reports "(deleted)"), while hashing "$0" returns
# the impostor that never executed. That is the difference between naming what is running
# and naming what happens to be at a name.
#
# The descriptor number is DISCOVERED, never assumed. Bash takes the highest FREE fd:
# 255 normally, 254 when the parent handed us 255, 249 with 250-255 taken (all measured).
# Hardcoding 255 does not fail loudly -- it hashes an unrelated inherited fd.
#
# KNOWN BLIND SPOT, pinned by a test rather than left to be discovered: a same-length
# IN-PLACE rewrite of our own inode is followed by this fd, because it is the same inode.
# It is invisible here and to every other spelling; a length-CHANGING in-place rewrite
# corrupts the running parse instead. Rename-replace -- the shape maybe_self_deploy and
# every sane deploy actually use -- is the case this closes.
watch_own_fd_path() {
  local want="$1" fd n target best=""
  for fd in /proc/$$/fd/*; do
    n="${fd##*/}"
    case "$n" in ''|*[!0-9]*) continue ;; esac
    target="$(readlink "$fd" 2>/dev/null || true)"
    target="${target% (deleted)}"
    if [ -n "$target" ] && [ "$target" = "$want" ]; then
      if [ -z "$best" ] || [ "$n" -gt "$best" ]; then best="$n"; fi
    fi
  done
  if [ -z "$best" ]; then return 1; fi
  printf '/proc/%s/fd/%s\n' "$$" "$best"
}

# HOW the baseline was obtained, printed beside it. A bare hash on a log line has already
# been misread as a commit sha in a published table: it is a CONTENT hash, and recovering
# a commit from it needs a reverse lookup that only succeeds while some commit still holds
# those exact bytes. The origin token says which question the number answers.
#   own-fd                     -- hashed from the descriptor bash is reading (authoritative)
#   own-fd-handover-mismatch   -- self-derived, and the predecessor's claim DISAGREED
#   handover                   -- /proc unavailable; believed the predecessor
#   path-reread                -- believed the pathname; a baseline for bytes we may not run
#   unavailable                -- no baseline was ever captured
WATCH_STARTUP_ORIGIN="unavailable"
WATCH_STARTUP_SHA256=""
WATCH_SELF_FD_PATH="$(watch_own_fd_path "${BASH_SOURCE[0]}" 2>/dev/null || true)"
if [ -n "$WATCH_SELF_FD_PATH" ]; then
  WATCH_STARTUP_SHA256="$(sha256_file "$WATCH_SELF_FD_PATH" 2>/dev/null || true)"
  if [[ "$WATCH_STARTUP_SHA256" =~ ^[0-9a-f]{64}$ ]]; then
    WATCH_STARTUP_ORIGIN="own-fd"
  fi
fi
# The predecessor's claim is now a CROSS-CHECK, not the source. As the source it meant an
# operator who exported the pair could tell a fresh watcher what it was running; `unset`
# bounded that lie to one process but did not remove it. Self-derivation removes the need
# to believe it at all, and keeping the comparison converts a lie -- or a snapshot that
# moved between hash and exec -- from a silent adoption into a reportable disagreement.
WATCH_HANDOVER_SHA256="${HESTIA_WATCH_STARTUP_SHA256:-}"
if [ "$WATCH_STARTUP_ORIGIN" = "own-fd" ]; then
  if [[ "$WATCH_HANDOVER_SHA256" =~ ^[0-9a-f]{64}$ ]] && \
     [ "$WATCH_HANDOVER_SHA256" != "$WATCH_STARTUP_SHA256" ]; then
    WATCH_STARTUP_ORIGIN="own-fd-handover-mismatch"
  fi
fi
# Fall back exactly as before when /proc gives us nothing: the handover, then the path.
if [ "$WATCH_STARTUP_ORIGIN" = "unavailable" ]; then
  WATCH_STARTUP_SHA256="$WATCH_HANDOVER_SHA256"
  if [[ "$WATCH_STARTUP_SHA256" =~ ^[0-9a-f]{64}$ ]]; then
    WATCH_STARTUP_ORIGIN="handover"
  fi
fi
if [ "$WATCH_STARTUP_ORIGIN" = "unavailable" ]; then
  WATCH_STARTUP_SHA256="$(watch_source_hash 2>/dev/null || true)"
  if [[ "$WATCH_STARTUP_SHA256" =~ ^[0-9a-f]{64}$ ]]; then
    WATCH_STARTUP_ORIGIN="path-reread"
  fi
fi
if ! [[ "$WATCH_STARTUP_SHA256" =~ ^[0-9a-f]{64}$ ]]; then
  WATCH_STARTUP_SHA256="unavailable"
  WATCH_STARTUP_ORIGIN="unavailable"
fi
unset WATCH_HANDOVER_SHA256
# Consumed. Not inherited by the fired CLI, and not inherited by a successor that did
# not get it from us -- these two say "your predecessor verified this", and only a
# predecessor is entitled to say it.
unset HESTIA_WATCH_SOURCE HESTIA_WATCH_STARTUP_SHA256
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
WATCH_LAST_ALARM_KEY=""
# The argv this process was started with, captured at TOP LEVEL. Inside a function
# `"$@"` is that function's own arguments, which is precisely how a re-exec loses the
# plugin id and the fire command and comes back up watching nothing.
WATCH_ARGV=("$@")
# Last drifted disk hash seen, so a deploy needs the SAME new bytes on two consecutive
# passes. The tree this mesh executes from has concurrent writers -- three watchers and
# whatever session is awake in it -- and a file caught mid-write hashes to bytes nobody
# ever committed. One sample is not a version; it is a race.
WATCH_DRIFT_SEEN_SHA256=""

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
  # The latch key is state:reason, not state alone. While `drift` had exactly one
  # reason, state was a lossless stand-in for the instruction; the direction
  # resolver above gave it three, two of which are OPPOSITE remedies. CBP's
  # standing case walks between them: a watcher restarted while the shared
  # checkout is behind latches on source-behind-daemon, then a sibling merge and
  # pull move the checkout PAST the daemon's build — and a state-only latch
  # swallows that edge, so the one instruction this check exists to deliver
  # (rebuild+restart, the daemon is the stale side) is never spoken. Measured,
  # not reasoned: kimi-code's review of #176 drove the flip and the second edge
  # did not fire. Latch on what the alarm SAYS, so a changed remedy is an edge.
  # The same line closes a second, older silence in the other direction: the
  # UNVERIFIABLE branch prints its reason, and daemon-unreachable ->
  # build-provenance-unknown (a daemon that restarts into a build reporting no
  # provenance) is a different sentence that state alone could not tell apart.
  if [ "$STATE" = "ok" ]; then
    WATCH_DAEMON_LAST_ALARM_KEY=""
  elif [ "$STATE:$REASON" != "$WATCH_DAEMON_LAST_ALARM_KEY" ]; then
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
    WATCH_DAEMON_LAST_ALARM_KEY="$STATE:$REASON"
  fi
}
WATCH_DAEMON_STATE="unverifiable"
WATCH_DAEMON_REASON="not-yet-checked"
WATCH_DAEMON_RUNNING="unavailable"
WATCH_DAEMON_SOURCE="unavailable"
WATCH_DAEMON_LAST_ALARM_KEY=""

announce_daemon() {
  check_daemon_drift refresh
  echo "[hestia-watch] DAEMON state=$WATCH_DAEMON_STATE reason=$WATCH_DAEMON_REASON running=$WATCH_DAEMON_RUNNING source=$WATCH_DAEMON_SOURCE"
}

announce_artifact() {
  # Re-measure here even though the loop also checks every pass. The periodic line
  # is the level-triggered gauge that survives log rotation; it must never depend on
  # a prior one-shot alarm still being visible.
  check_artifact_drift
  echo "[hestia-watch] ARTIFACT plugin=$PLUGIN state=$WATCH_ARTIFACT_STATE reason=$WATCH_ARTIFACT_REASON startup_sha256=$WATCH_STARTUP_SHA256 startup_origin=$WATCH_STARTUP_ORIGIN disk_sha256=$WATCH_CURRENT_SHA256 started=$WATCH_STARTED_AT"
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
  # last non-ok state:reason rather than a boolean so unverifiable -> drift emits
  # the new, actionable condition once. Returning to ok clears the edge memory.
  # The reason joins the key to match check_daemon_drift, where it is load-bearing.
  # Here it changes NOTHING reachable today and the honest note is why: the only
  # two unverifiable reasons are startup-baseline-unavailable and
  # disk-hash-unavailable, and the first is absorbing — WATCH_STARTUP_SHA256 is
  # assigned once at startup and tested first, so a run that enters it never
  # leaves it, and no flip between reasons exists to swallow. This line is
  # alignment, not a repair; it earns its place by removing a difference between
  # two otherwise identical latches that a reader would have to re-derive.
  if [ "$STATE" = "ok" ]; then
    WATCH_LAST_ALARM_KEY=""
  elif [ "$STATE:$REASON" != "$WATCH_LAST_ALARM_KEY" ]; then
    if [ "$STATE" = "drift" ]; then
      echo "[hestia-watch] ARTIFACT DRIFT — restart required; startup_sha256=$WATCH_STARTUP_SHA256 startup_origin=$WATCH_STARTUP_ORIGIN disk_sha256=$CURRENT"
    else
      echo "[hestia-watch] ARTIFACT UNVERIFIABLE — reason=$REASON startup_sha256=$WATCH_STARTUP_SHA256 startup_origin=$WATCH_STARTUP_ORIGIN disk_sha256=$CURRENT"
    fi
    WATCH_LAST_ALARM_KEY="$STATE:$REASON"
  fi
}

# THE ALARM THAT HAD NO RECOVERY.
#
# `check_artifact_drift` above has been correct, level-triggered and hourly for twenty
# days, and it changed nothing -- because the only sentence it can say is "restart
# required" and it says it to a log no member reads, on behalf of a process no member
# can restart. This file already names that defect, one function down, about a
# different alarm: "The alarm existed and the recovery did not, which is this corpus's
# recurring defect wearing recovery's clothes." The drift alarm is the next instance.
#
# MEASURED, CBP 2026-08-26. The claude-code and kimi-code watchers were executing
# a8dccda (2026-08-06) while origin/main was three mesh commits ahead. One of the three
# is ebc3719, which stops this script reporting a DELIVERED primer as undelivered.
# In one member's primer that morning: 41 non-delivery labels on rc=124 -- the one rc
# that proves delivery -- of which 40 were filed by the two stale-vintage watchers.
# The 41st was codex's, queued 2026-08-25T18:37:02Z, 4h35m BEFORE codex restarted into
# the current bytes at 23:12:38Z. THE DENOMINATOR IS ONE MEMBER'S PRIMER, not the
# fleet: codex, reviewing this PR from its own retained snapshots, counted seven unique
# rc=124 rows attributed via watch-codex, and the 18:37:02Z batch filed four notices --
# only one of which reached the primer counted here. Post-restart, on either
# denominator, that seat has filed zero. The fix works. It was merged. It was not in
# force.
#
# WHY NOBODY APPLIED IT BY HAND. There is no moment to apply it in. The session that
# reads the alarm is a descendant of its own watcher's cgroup, so `systemctl restart`
# is suicide; the other stale seat was mid-wake behind a foreground `timeout -k 30
# 1800`. Three members waking each other makes "idle at the instant a human looks"
# close to a null set. A remedy only a human can apply, to a machine that is never
# idle when the human is there, is not a remedy.
#
# FOUR CONJUNCTS. Each one removes a way this could be worse than the staleness it
# fixes; none of them is decoration.
#
#   drift          -- nothing to deploy otherwise.
#
#   stable twice   -- the same NEW hash on two consecutive passes, not one sighting.
#                     Concurrent writers; a half-written file is not a version.
#
#   MERGED, BYTE   -- the disk bytes must be byte-identical to `origin/main:<path>`.
#     FOR BYTE        This is the conjunct that carries the design. Deploying
#                     "whatever changed" would make the fleet's in-force vintage a
#                     function of whoever last hit save in a shared worktree, which is
#                     strictly WORSE than being stale: stale is at least stable and
#                     nameable, and this file's whole vintage story depends on that.
#                     Deploying "what was merged" closes the last link of
#                     committed -> routed -> merged -> IN FORCE, and refuses to close
#                     it for bytes that skipped the earlier ones.
#
#                     NOT `git hash-object` against `rev-parse origin/main:<path>`,
#                     which is the obvious spelling and is WRONG HERE. This tree lives
#                     on a Windows mount with `core.autocrlf=input`, so the clean
#                     filter normalises CRLF on the way in: a CRLF-mangled working copy
#                     has the SAME blob id as the clean merged file. Measured on this
#                     box -- identical blob, and `bash -n` accepts the mangled file too,
#                     so the parse conjunct does not catch it either. Both guards would
#                     have waved it through. Comparing the RAW BYTES of `git show`
#                     against the same sha256 the startup snapshot already computes puts
#                     no filter anywhere in the path, and costs one hash.
#
#   SAME OBJECT    -- the hash, the parse and the `exec` all name ONE private file
#                     under $STATE holding the `git show` output, placed by rename.
#                     Checking a PATHNAME and then exec'ing that pathname binds
#                     nothing in a tree with concurrent writers: the replacement that
#                     lands in between is what runs. Rehashing just before exec
#                     narrows that window and does not close it.
#
#   parses         -- `bash -n`. Unreachable unless origin/main itself carries a syntax
#                     error, and kept for exactly that case: the unit is Restart=always,
#                     so exec'ing into a file that does not parse is a fleet-wide crash
#                     loop rather than a deploy. Cheap insurance against the one input
#                     the merged-bytes conjunct cannot vet.
#
# FAIL CLOSED. Any conjunct that cannot be answered -- source not tracked, no
# origin/main, git absent, hash unavailable -- declines to deploy and says which one,
# leaving today's behaviour exactly as it is. The polarity is deliberate: an
# auto-deployer that fires when it cannot verify is the bug it is here to fix.
#
# WHERE IT RUNS is the safety argument, and it is structural rather than a heuristic.
# The fire is FOREGROUND (`if "$FIRE" "$PRIMER"; then`), so the top of the loop is the
# one point in this script where this watcher provably has no wake in flight. A deploy
# that can only happen where there is no wake can never cut one short.
#
# `exec` and not `systemctl restart`: same pid, the unit never goes inactive, MainPID
# does not move, nothing else in the cgroup is signalled -- and the successor reads the
# file from byte zero, which is the entire point, since a long-running bash executes
# the buffer it began with and can otherwise resume at a stale byte offset.
#
# BOOTSTRAP, SAID OUT LOUD: this function cannot deploy itself. The seats that predate
# it need exactly one manual restart, ever, and then never another one.
maybe_self_deploy() {
  if [ "$WATCH_ARTIFACT_STATE" != "drift" ]; then
    WATCH_DRIFT_SEEN_SHA256=""
    return 0
  fi
  [[ "$WATCH_CURRENT_SHA256" =~ ^[0-9a-f]{64}$ ]] || return 0

  if [ "$WATCH_CURRENT_SHA256" != "$WATCH_DRIFT_SEEN_SHA256" ]; then
    WATCH_DRIFT_SEEN_SHA256="$WATCH_CURRENT_SHA256"
    return 0
  fi

  local REL SNAP SNAP_NEW SNAP_SHA

  # A FAILING COMMAND MUST PRODUCE A HELD VERDICT, NOT AN EXIT. Codex review of #636,
  # blocking 2, and it was not hypothetical: under `set -euo pipefail` the previous
  # spelling `REL="$(git ... | head -1)"` made a non-repo working directory kill the
  # WHOLE WATCHER with rc=128 before the "not tracked" branch below could ever print.
  # CI reproduced it -- watch_artifact_identity_test.py runs this script from a bare
  # temp dir, and the watcher died mid-test. `if !` puts the status in a condition
  # (where errexit is suspended), and the first line is taken with an expansion rather
  # than a pipe, so nothing but git's own status decides the verdict.
  if ! REL="$(git -C "$WATCH_DIR" ls-files --full-name -- "$WATCH_SOURCE" 2>/dev/null)"; then
    echo "[hestia-watch] ARTIFACT DRIFT held — cannot ask git whether the source is tracked; deploy declined"
    return 0
  fi
  REL="${REL%%$'\n'*}"
  if [ -z "$REL" ]; then
    echo "[hestia-watch] ARTIFACT DRIFT held — source is not tracked in a git repo; deploy declined"
    return 0
  fi

  # THE BYTES CHECKED MUST BE THE BYTES `exec` OPENS. Codex review of #636, blocking 1.
  # Hashing and parsing a PATHNAME and then exec'ing that same pathname binds nothing:
  # this tree has concurrent writers, and a replacement landing between the last check
  # and the open is precisely what gets executed. Re-hashing just before exec narrows
  # the window; it does not close it.
  #
  # So `git show` is materialised into a private file under $STATE (0700, one per
  # plugin, and the flock above guarantees a single watcher per plugin writes it), and
  # the hash, the `bash -n` and the `exec` all name THAT file. The final `mv` is a
  # rename, so the inode verified is the inode executed, and a predecessor still
  # running from the old snapshot keeps its own open inode rather than being truncated
  # underneath itself.
  #
  # What the successor loses by running from $STATE -- the canonical path it should
  # keep watching, and the hash of what it is really executing -- is handed to it
  # explicitly on the exec line.
  SNAP="$STATE/self-deploy/watch-$PLUGIN.sh"
  SNAP_NEW="$SNAP.new"
  mkdir -p "$STATE/self-deploy" && chmod 700 "$STATE/self-deploy"
  # Branching on git's status, NOT on the digest. The previous spelling ended in
  # `|| true`, which threw away rc=128 for an unreadable origin/main and kept the
  # hasher's stdout: sha256 of EMPTY INPUT, e3b0c442... If the drifted disk file were
  # also empty the two would match, `bash -n` would accept it, and the watcher would
  # deploy an empty script under Restart=always -- fail-OPEN on the exact conjunct this
  # function advertises as fail-closed.
  if ! git -C "$WATCH_DIR" show "origin/main:$REL" > "$SNAP_NEW" 2>/dev/null; then
    echo "[hestia-watch] ARTIFACT DRIFT held — cannot read origin/main:$REL; deploy declined"
    return 0
  fi
  SNAP_SHA="$(sha256_file "$SNAP_NEW" 2>/dev/null || true)"
  if [[ ! "$SNAP_SHA" =~ ^[0-9a-f]{64}$ ]]; then
    echo "[hestia-watch] ARTIFACT DRIFT held — cannot hash origin/main:$REL; deploy declined"
    return 0
  fi
  if [ "$SNAP_SHA" != "$WATCH_CURRENT_SHA256" ]; then
    echo "[hestia-watch] ARTIFACT DRIFT held — disk bytes are not origin/main:$REL (disk=$WATCH_CURRENT_SHA256 main=$SNAP_SHA); merged bytes deploy, edited bytes do not"
    return 0
  fi
  if ! "${BASH:-bash}" -n "$SNAP_NEW" 2>/dev/null; then
    echo "[hestia-watch] ARTIFACT DRIFT held — origin/main:$REL does not parse; deploy declined"
    return 0
  fi
  if ! mv -f "$SNAP_NEW" "$SNAP"; then
    echo "[hestia-watch] ARTIFACT DRIFT held — cannot place the verified snapshot at $SNAP; deploy declined"
    return 0
  fi

  echo "[hestia-watch] ARTIFACT DEPLOY plugin=$PLUGIN — exec into merged bytes; was=$WATCH_STARTUP_SHA256 now=$WATCH_CURRENT_SHA256 ref=origin/main:$REL snapshot=$SNAP_SHA"
  # `exec bash "$path"` and not `exec "$path"`: the executable bit does not survive on
  # the Windows mount this tree lives on, which is why the unit invokes the script
  # through bash to begin with.
  HESTIA_WATCH_SOURCE="$WATCH_SOURCE" HESTIA_WATCH_STARTUP_SHA256="$SNAP_SHA" \
    exec "${BASH:-bash}" "$SNAP" "${WATCH_ARGV[@]}"
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

# ...and ASK BEFORE RE-FIRING (2026-08-05). The retry above decides on `$FIRE`'s exit
# code, which is a fact about the harness and not about whether the notices were handled.
# A wake that ran, replied, committed and pushed, and then hit the launcher's timeout,
# returns nonzero and gets its work list retained — this mesh's own rc=124 reports are
# 9/9 false for exactly that reason. The retention is then re-fired at every watcher
# restart, in `mktemp` alphabetical order, one model wake apiece.
#
# Measured on CBP the day this was written: 18 retained primers for `claude-code`
# carrying 46 notices; 31 were of a kind the daemon counts and NONE of the 31 was still
# owed, and the remaining 15 were `ack`/`review_done`, kinds that never await a response
# at all. Zero undischarged work, 18 wakes queued to re-deliver it — including the one
# that woke the session that found this, for a notice answered six minutes after it was
# first drained, two days earlier.
#
# So consult the daemon. `i_owe` is the mesh's OWN predicate for "this notice awaits my
# response"; a notice absent from it is discharged by the same rule every other surface
# in this system uses, and a kind outside `MEMBER_KINDS_AWAIT_RESPONSE` can never appear
# there — which is correct, it was never owed one. Naming no kind list here is
# deliberate: the daemon's constant stays the single definition.
#
# Every failure direction FIRES ANYWAY. A wasted wake is recoverable; a work list
# retired on a false "spent" is not, and consume-once means there is no second copy.
# So the guard judges only notices inside a WINDOW where absence from the fold carries
# information, and treats everything else as unmeasured:
#   - RPC fails, daemon down, refusal payload -> unknown                       -> fire
#   - notice OLDER than SPENT_MAX_AGE_SECS — past the point where the daemon prunes
#     the inbox (7d), so absence means "pruned", not "answered"                 -> fire
#   - notice YOUNGER than SPENT_MIN_AGE_SECS — this is the trap, and it points the
#     unsafe way. `i_owe` shows a row only if it is older than the floor, so a LARGER
#     floor hides MORE unanswered notices, and every hidden row reads as discharged.
#     Under #155 (every tool is `additionalProperties: true` with zero declared
#     properties) a misspelled `older_than_secs` is discarded into a success and
#     MEMBER_UNANSWERED_DEFAULT_SECS (6h) applies without saying so — which would
#     retire the primer of a notice stranded forty minutes ago.       -> fire, UNLESS
#     the fold says out loud which floor it applied. See below.
# Nothing above can produce a false "spent". That asymmetry is the whole design.
#
# THE FLOOR IS NOW VERIFIED RATHER THAN ASSUMED (2026-08-06).
# The original min-age rule made the verdict "independent of whether the argument was
# honoured at all" by refusing to judge anything younger than 6h. That is sound, and its
# price is the modal case on this mesh: a notice answered PROMPTLY is never retirable,
# because for its whole first 6h it sits in the unmeasurable band. Measured on CBP the
# day this was written — three retained primers for claude-code (notices 1177/1178/1179,
# 1199/1200/1201, 1208), every one of them absent from `i_owe` at floor 0, every one of
# them blocked from retirement by this check alone, and the wake that found it was
# re-fire attempt 1 of 3 for notice 1208, answered 45 minutes earlier.
#
# `hestia_member_unanswered` echoes `older_than_secs` in its response, and the echo is
# the APPLIED floor, not the requested one. Measured against the live daemon, all four
# cells, same session:
#     older_than_secs=0            -> echo 0      i_owe 7 rows
#     omitted                      -> echo 21600  i_owe 1 row
#     older_than_seconds=0 (#155)  -> echo 21600  i_owe 1 row   <- the trap, reported
#     older_than_secs=60           -> echo 60     i_owe 7 rows
# The misspelled cell is the one that matters: the daemon does not parrot the request,
# it reports the default it fell back to. So "was my floor honoured" is answerable
# rather than assumable, and the min-age band shrinks to the floor the fold ADMITS to.
# Every failure direction still fires: echo absent (an older daemon), echo non-integer,
# or echo > 0 all fall back to the conservative 6h band unchanged.
SPENT_MAX_AGE_SECS="${SPENT_MAX_AGE_SECS:-518400}"   # 6d — deliberately INSIDE the daemon's 7d inbox TTL
SPENT_MIN_AGE_SECS="${SPENT_MIN_AGE_SECS:-21600}"    # 6h — MEMBER_UNANSWERED_DEFAULT_SECS, the fallback when the fold will not say

# THE FOLD TRAVELS AS A FILE, NOT AN ARGUMENT (2026-09-02). This function took the fold
# as `$2` and handed it to python as one argv string. Linux caps a single argument at
# MAX_ARG_STRLEN = 131072 bytes (32 pages; measured on CBP: 131,000 passes, 131,072
# fails). A fold past that never reaches the judge: bash prints "Argument list too
# long", the function returns nonzero, and nonzero is the "unmeasured -> fire" arm
# below. Every failure direction fires, by design — so a fold that outgrew an argument
# turned the guard into a no-op that fires EVERY retained primer, discharged or not,
# to the attempt budget, at every restart. The fold crosses the line on its own: at
# floor 0 the claude-code fold was 388,367 bytes on 2026-09-02 (738 `owed_to_me` rows;
# the guard reads only `i_owe`, but the whole fold is one string), and the kimi-code
# watcher's journal that day shows "Argument list too long" before 8 of 8 surviving
# stale passes, 21 consecutive stale re-fires from 04:22Z to 10:26Z, four of them on
# notices already answered with `binding_verified: true` in August. Each re-fire adds
# rows to the peer's fold, so the storm feeds the condition that causes it.
#
# $1 = primer path, $2 = PATH TO the `unanswered` fold, fetched once per pass. Exit 0
# ONLY when every notice in the primer is inside the measurable window and absent from
# `i_owe`. `stale_primer_discharged_test.py` case 7 pads the fold past 128 KiB.
primer_spent() {
  python3 - "$1" "$SPENT_MAX_AGE_SECS" "$2" "$SPENT_MIN_AGE_SECS" <<'PY'
import datetime, json, sys
primer, max_age, fold_path, min_age = sys.argv[1], int(sys.argv[2]), sys.argv[3], int(sys.argv[4])
try:
    with open(fold_path, encoding="utf-8") as f:
        fold = json.load(f)
    notices = json.load(open(primer)).get("notices") or []
except Exception:
    raise SystemExit(1)                     # unreadable either side -> unmeasured
# A refusal, an error envelope or a truncated body is not an empty debt. The key must
# be PRESENT: `.get("i_owe") or []` would read every one of those as "nothing owed".
if not isinstance(fold, dict) or not isinstance(fold.get("i_owe"), list):
    raise SystemExit(1)
if not notices:
    raise SystemExit(1)                     # nothing to judge -> leave the old path alone
# The fold's own statement of the window it covers. `unanswered_now` asks for 0; this
# reads what was actually applied. A bool is not an int here on purpose (True == 1).
applied = fold.get("older_than_secs")
if isinstance(applied, int) and not isinstance(applied, bool) and 0 <= applied < min_age:
    min_age = applied                       # the fold covers this band; trust it that far
owed = {n.get("id") for n in fold["i_owe"] if isinstance(n, dict)}
now = datetime.datetime.now(datetime.timezone.utc)
for n in notices:
    if n.get("id") is None or n.get("id") in owed:
        raise SystemExit(1)
    try:
        q = datetime.datetime.fromisoformat(str(n.get("queued_at", "")).replace("Z", "+00:00"))
    except ValueError:
        raise SystemExit(1)
    age = (now - q).total_seconds()
    if age > max_age or age < min_age:
        raise SystemExit(1)
raise SystemExit(0)
PY
}

# PAST THE DAEMON'S TTL THERE IS NOBODY TO PAY (2026-09-02). A notice older than the
# inbox TTL (7d, `INBOX_TTL_SECS`) has been pruned from `member_notices`: the daemon
# answers `member_notice_recipient` with no row, so a disposition bound to it is
# witnessed `binding_verified: false`; the sender's `owed_to_me` cannot hold it either,
# so nothing the member does can discharge anything. The old rule fired it anyway
# ("absence means pruned, not answered"), and the member woke, answered mail the ledger
# had forgotten, and read its own unverifiable binding as "a TTL-aged notice can never
# close". On CBP 2026-09-02, 11 of kimi-code's 21 consecutive stale re-fires were on
# notices 8–15 days old, every one already answered on the chain in August.
#
# Set aside, never deleted: `.expired` keeps the only copy, and the journal line names
# every id so the member can read the pointers by hand if the work still matters. Only
# when EVERY notice in the list is past the TTL — a list with one live notice is still
# a live list, and the live notice is what the attempt budget is for.
EXPIRED_AGE_SECS="${EXPIRED_AGE_SECS:-604800}"   # 7d — the daemon's INBOX_TTL_SECS, exactly

# $1 = primer path. Exit 0 ONLY when every notice in it is older than the daemon's TTL.
primer_expired() {
  python3 - "$1" "$EXPIRED_AGE_SECS" <<'PY'
import datetime, json, sys
primer, ttl = sys.argv[1], int(sys.argv[2])
try:
    notices = json.load(open(primer)).get("notices") or []
except Exception:
    raise SystemExit(1)
if not notices:
    raise SystemExit(1)
now = datetime.datetime.now(datetime.timezone.utc)
for n in notices:
    try:
        q = datetime.datetime.fromisoformat(str(n.get("queued_at", "")).replace("Z", "+00:00"))
    except ValueError:
        raise SystemExit(1)
    if (now - q).total_seconds() <= ttl:
        raise SystemExit(1)
raise SystemExit(0)
PY
}

# One fold, on disk, for a whole pass. Prints the path; empty on failure. The caller
# removes it. `unanswered_now` failing yields an empty file, which `primer_spent` reads
# as unmeasured — the refusal arm, unchanged.
fold_to_file() {
  local f
  f="$(mktemp "${TMPDIR:-/tmp}/hestia-fold-$PLUGIN.XXXXXX")" || return 1
  unanswered_now > "$f" 2>/dev/null || true
  echo "$f"
}

# Wrapped in a function only so it can run AFTER `mesh_rpc` is defined; it is still
# called from the startup path, in the same place, before the first poll.
# THE WALK YIELDS TO THE LOOP (kimi-code, reply 9164, 2026-09-02). This pass used to
# FIRE every surviving list, synchronously, before the main loop below ever ran. Each
# fire is a full wake (kimi-code on CBP: 4.5-27.5 min, mean 16.6), and the kimi-code
# watcher restarted on 2026-09-01 21:22 PDT with 149 retained lists: at that rate the
# first `drain` was ~41 hours away. Measured in its journal the next day: zero
# "notice(s) for kimi-code" lines, zero ARTIFACT, zero DAEMON, eight consecutive
# "RETRYING stale primer" -- fresh mail queued daemon-side while the watcher re-delivered
# August. The fold it judged against was also a single snapshot from hour 0.
#
# So the startup pass now only JUDGES: set aside what is discharged, expired or out of
# attempts (no fire, cheap, every list named in the journal). What survives is fired
# from the main loop, ONE per tick, and only on a tick whose drain found no fresh mail
# -- the member's own inbox always goes first. Between attempts on the same list the
# loop waits `STALE_RETRY_BACKOFF_SECS` (6h): the old cadence was "once per restart",
# which was days, and a member out of credits for a night would otherwise burn all
# three attempts in six minutes. The FIRST attempt is not held back -- a retained list
# whose launcher merely timed out is retried on the next quiet tick, and if the session
# inside did the work, the judge (re-run against a FRESH fold at fire time) retires it
# instead.
STALE_RETRY_BACKOFF_SECS="${STALE_RETRY_BACKOFF_SECS:-21600}"

# judge_stale_primer <primer> <fold_file>: 0 = set aside (never to be fired), 1 = live.
judge_stale_primer() {
  local stale="$1" fold_file="$2" attempts_file="$1.attempts" attempts
  # Before the attempt budget, not after: a discharged list should retire on the
  # first pass that can prove it, whatever the counter says.
  if [ -n "$fold_file" ] && primer_spent "$stale" "$fold_file"; then
    echo "[hestia-watch] STALE PRIMER ALREADY DISCHARGED (the daemon owes nothing for any notice in it) — retired without a fire: $stale.discharged"
    mv -f "$stale" "$stale.discharged" 2>/dev/null && rm -f "$attempts_file"
    return 0
  fi
  if primer_expired "$stale"; then
    echo "[hestia-watch] STALE PRIMER EXPIRED (every notice is past the daemon's ${EXPIRED_AGE_SECS}s inbox TTL: pruned, unbindable, owed to nobody) — set aside without a fire; the ids above are the only record, read them by hand if the work still matters: $stale.expired"
    mv -f "$stale" "$stale.expired" 2>/dev/null && rm -f "$attempts_file"
    return 0
  fi
  attempts="$(cat "$attempts_file" 2>/dev/null || echo 0)"
  [[ "$attempts" =~ ^[0-9]+$ ]] || attempts=0
  if [ "$attempts" -ge "$STALE_MAX_ATTEMPTS" ]; then
    echo "[hestia-watch] STALE PRIMER exhausted ($attempts/$STALE_MAX_ATTEMPTS) — set aside: $stale.exhausted"
    mv -f "$stale" "$stale.exhausted" 2>/dev/null && rm -f "$attempts_file"
    return 0
  fi
  return 1
}

# The startup pass: name every retained list in the journal and judge it. Fires nothing.
retry_stale_primers() {
  local fold_file live=0
  ls "$PRIMERS"/notice-*.json >/dev/null 2>&1 || return 0
  fold_file="$(fold_to_file || true)"
  for stale in "$PRIMERS"/notice-*.json; do
    [ -e "$stale" ] || break
    echo "[hestia-watch] STALE PRIMER (undelivered notices from a failed fire): $stale"
    python3 -c "import json,sys;d=json.load(open(sys.argv[1]));[print(f\"    id={n.get('id')} {n.get('kind')} from {n.get('from_plugin')} queued={n.get('queued_at','')}: {n.get('pointer_uri','')}\") for n in d.get('notices',[])]" "$stale" 2>/dev/null || true
    [ -n "$FIRE" ] || continue
    judge_stale_primer "$stale" "$fold_file" || live=$((live + 1))
  done
  [ -n "$fold_file" ] && rm -f "$fold_file"
  [ "$live" -gt 0 ] && echo "[hestia-watch] $live retained primer(s) survive the judge; the loop will fire them one per quiet tick, the inbox first"
  return 0
}

# stale_primer_due <primer>: the first attempt is immediate; later ones wait the backoff
# measured from the previous attempt (the `.attempts` file's mtime).
stale_primer_due() {
  local attempts_file="$1.attempts" last now
  [ -e "$attempts_file" ] || return 0
  last="$(stat -c %Y "$attempts_file" 2>/dev/null || echo 0)"
  now="$(date +%s)"
  [ $((now - last)) -ge "$STALE_RETRY_BACKOFF_SECS" ]
}

# One quiet tick, one retained list: re-judged against a fresh fold, then fired.
fire_one_stale_primer() {
  local fold_file attempts_file attempts rc
  ls "$PRIMERS"/notice-*.json >/dev/null 2>&1 || return 0
  for stale in "$PRIMERS"/notice-*.json; do
    [ -e "$stale" ] || break
    stale_primer_due "$stale" || continue
    fold_file="$(fold_to_file || true)"
    if judge_stale_primer "$stale" "$fold_file"; then
      [ -n "$fold_file" ] && rm -f "$fold_file"
      continue                              # set aside; look for the next one
    fi
    [ -n "$fold_file" ] && rm -f "$fold_file"
    attempts_file="$stale.attempts"
    attempts="$(cat "$attempts_file" 2>/dev/null || echo 0)"
    [[ "$attempts" =~ ^[0-9]+$ ]] || attempts=0
    echo $((attempts + 1)) > "$attempts_file"
    echo "[hestia-watch] RETRYING stale primer (attempt $((attempts + 1))/$STALE_MAX_ATTEMPTS): $stale"
    if "$FIRE" "$stale"; then
      rm -f "$stale" "$attempts_file"
      echo "[hestia-watch] stale primer DELIVERED on retry: $stale"
    else
      rc=$?
      echo "[hestia-watch] stale retry failed rc=$rc (preserved, will retry after ${STALE_RETRY_BACKOFF_SECS}s): $stale"
    fi
    return 0                                # one fire per tick
  done
  return 0
}

# JUDGE INSIDE THE WINDOW (2026-09-02). The startup pass judges once, and a
# watcher restarts rarely: the kimi-code watcher on CBP ran 2026-08-20 -> 09-01 without
# one. Every primer retained in between was first judged after the 6d judging window
# had closed, so `primer_spent` could only say "unmeasured" and the pass fired all of
# them — 45 of the 57 claude-code retained primers were in that state the day this was
# written, 3 were provably discharged, 9 owed. This sweep asks the same question on a
# cadence and does the ONE thing that is safe on a cadence: set aside what the daemon says
# is discharged (and, since the walk moved into the loop, what is expired or out of
# attempts — the same judge). It never fires: firing is the loop's job, one list per
# quiet tick, held to `STALE_RETRY_BACKOFF_SECS` between attempts on the same list.
# `DISCHARGE_SWEEP_EVERY` is its own knob only so the test can turn it.
DISCHARGE_SWEEP_EVERY="${DISCHARGE_SWEEP_EVERY:-3600}"

retire_discharged_primers() {
  local fold_file n=0
  ls "$PRIMERS"/notice-*.json >/dev/null 2>&1 || return 0
  fold_file="$(fold_to_file || true)"
  [ -n "$fold_file" ] || return 0
  for stale in "$PRIMERS"/notice-*.json; do
    [ -e "$stale" ] || break
    judge_stale_primer "$stale" "$fold_file" && n=$((n + 1))
  done
  rm -f "$fold_file"
  [ "$n" -gt 0 ] && echo "[hestia-watch] discharge sweep set aside $n retained primer(s)"
  return 0
}

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
# The journal wants the 6h floor; `primer_spent` asks for a floor of ZERO so the fold it
# reads is the complete debt rather than the stale tail. Asked-for-and-zero, not absent:
# the argument is sent explicitly, because omitting it is not "no floor" — the daemon
# substitutes MEMBER_UNANSWERED_DEFAULT_SECS (6h) for a missing OR misspelled key and
# reports success either way (#155), so the only way to actually get zero is to say so.
# The guard does NOT depend on this having worked — see SPENT_MIN_AGE_SECS — but a fold
# that covers everything is still the right thing to ask for, and `older_than_secs` is
# the daemon's real parameter name (any other spelling is discarded into a success).
unanswered_now() { mesh_rpc hestia_member_unanswered '{"older_than_secs": 0}'; }

# THE PETITIONS YOU HOLD. `hestia_member_unanswered` asks "what have you not
# answered"; nothing ever asked the mirror question — "what have you ASKED that
# is still open" — and the member is the only party that can retire the moot
# ones. An auto-minted escalation is opened FOR the member by the gate on a
# refused write, so a member routinely holds petitions it never chose to file
# and has no surface that names them: `hestia_gate_escalation_poll` needs an id
# you already know, and the id is printed once, into a refusal, in a wake that
# has usually ended. Measured on CBP 2026-08-19: 30 of 30 lapses were
# gate-auto-minted and `gate_escalation_withdrawn` had fired twice, ever.
#
# Unattributed by design (`session_id` optional, no scope wall), but `mesh_rpc`
# passes it, which is what populates `you_may_rule` — always false on your own
# rows. That is the point: the move on your own open petition is not to rule it,
# it is `hestia_gate_arbitrate_escalation approve:false`, which files it as
# `self_withdrawn` with no independence claimed. Costs one read per drain and
# never causes a fire on its own.
open_petitions() { mesh_rpc hestia_gate_pending_escalations '{}'; }

# The startup stale-primer pass. Deferred to here only because it needs `mesh_rpc`;
# it still runs before the first poll, and before the unanswered journal announce.
retry_stale_primers

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
#
# THE EVIDENCE WINDOW IS NOT THE WHOLE LOG (2026-08-05). On any harness that
# echoes its prompt into its own log — `codex exec` does; the claude and kimi
# CLIs do not — the window below contains this fire's PRIMER. And since #187 the
# primer quotes the PREVIOUS wake's final output verbatim. So the phrases this
# function greps for can arrive from a fire that already happened, and the
# classification goes STICKY: a member that once failed one way carries that
# failure's text forward in every subsequent primer, where it can be re-read as
# the current cause indefinitely. Two correct features composing into a wrong
# answer — last-words (#187, 2026-08-03) contaminated the input of a classifier
# written two days earlier (389c645, 2026-08-01), and neither change was wrong.
#
# Specimen: `codex-20260804-225003.log`. All three "Operation not permitted"
# lines (32, 34, 43) sit INSIDE the quoted block (23-50); the real failure,
# "out of credits", is at 57-58. It classified correctly only because the
# credits test runs BEFORE the EPERM test — a priority accident, not evidence.
# Reverse that fire's cause and the answer is `egress-blocked` from text about
# a wake two days gone, pointing the reader at codex's sandbox: a defect that
# IS real on this member and therefore maximally plausible, which is what makes
# the wrong hint expensive rather than merely wrong.
#
# So classify only what follows the prompt. Two anchors, LAST match wins:
#   - the last-words closing delimiter, and
#   - the prompt's closing sentence, which is present even when last-words is
#     empty and is what excludes the DIGEST — pointer text authored by OTHER
#     members, i.e. the one input to this decision that this member does not
#     control at all.
# A log with neither anchor (a harness that echoes no prompt) falls back to the
# previous behaviour, so this is a no-op for claude and kimi today. The coupling
# to the prompt's wording is real and is guarded from the other side: the
# adoption checks in `tests/classify_evidence_window_test.py` fail if a template
# stops ending with a line this anchor matches. When the anchors are absent from
# a log that DID echo a prompt, the failure mode is a shorter window and more
# `unknown` — evidence lost, never evidence invented.
# THE CLASS WAS A VENDOR-SPELLING BET (2026-08-18). `out of credits` is CODEX's
# wording. kimi spells the identical billing state
# `403 You've reached your usage limit for this billing cycle ... purchase extra
# usage or upgrade your plan`, which matched none of the three patterns, so kimi
# could never be classified out-of-credits — it fell through to `unknown` and the
# report said `why=unknown` about a cause sitting verbatim in the log. Measured on
# the live corpus: real kimi log -> `unknown`, real codex log -> `out-of-credits`,
# same state, two verdicts. 40 kimi logs across three outages (08-08, 08-17, 08-18)
# were mis-reported this way. This is the codex-notice-160 ambiguity the function
# was written to END, reappearing one vendor over: the taxonomy was fine, its
# vocabulary was one vendor wide.
#
# The test could not catch it because its "REAL planted log" was an AUTHORED
# string carrying codex's spelling on BOTH sides of the check — a positive control
# that contains only the sibling it already matches. The plants below are now
# verbatim captures from each vendor's logs.
#
# Widening was checked for theft over all 1449 logs on disk: 42 verdicts move, all
# `unknown -> out-of-credits`, ZERO taken from egress-blocked or timeout.
#
# AND IT HAPPENED A THIRD TIME, SAME SHAPE, THE VENDOR THIS BLOCK IS ABOUT
# (2026-08-26). The 08-18 pass widened codex's vocabulary to cover kimi's and stopped
# there. claude's CLI spells the identical state two more ways —
# `You've hit your session limit · resets 7am (America/Los_Angeles)` and
# `You've hit your weekly limit · resets 11pm (America/Los_Angeles)` — and neither
# carries `usage limit`, `credits`, or any other pattern above. Measured over all 740
# claude logs on disk: 60 carry a claude limit spelling and **60 of 60 classified
# `unknown`**, across five separate outages (08-03, 08-16, 08-17, 08-24, 08-26). Not
# one was ever classified correctly. That is a larger corpus than the 40 kimi logs
# that motivated the previous widening, and it sat under a comment that had already
# named the failure mode in general terms — "the taxonomy was fine, its vocabulary was
# one vendor wide" — while the vocabulary was still one vendor short.
#
# The lesson the 08-18 pass recorded but did not act on: a vendor-spelling bet is not
# fixed by adding the one sibling that bit you. Enumerate every vendor the mesh fires,
# from that vendor's own logs, or the next outage re-files the same report. Three
# vendors fire here; all three spellings are now present, from verbatim captures.
#
# Theft re-checked over all 1960 logs now on disk: 60 verdicts move, all
# `unknown -> out-of-credits`, ZERO taken from egress-blocked or timeout.
#
# This widening makes the claude FALSE POSITIVE below slightly more reachable, and
# that is an accepted trade, stated rather than hidden: the FP needs a claude fire
# failing rc not-0 and not-124 whose own prose discusses limits, costs a wrong `why=`
# hint that nothing downstream branches on, and has occurred twice in 740 logs. The FN
# it removes is 60 for 60, live, and each one publishes `why=unknown` about a cause
# sitting verbatim on line 1 of the log it just read.
# KNOWN FALSE POSITIVE, latent not live: claude's log has NEITHER anchor (its CLI
# echoes no prompt), so its window is the member's OWN PROSE — and prose ABOUT an
# outage now matches. Two such logs exist already (claude-20260810-155415,
# claude-20260818-073521), both from SUCCEEDED fires, which this function never
# reads. Reaching it needs a claude fire failing with rc not 0 and not 124 (124
# short-circuits above) whose tail discusses credits. Cost is bounded by design —
# nothing downstream branches on the hint — but the structural fix is an anchor in
# claude's log, i.e. a window that is not member prose. Unfixed, deliberately.
classify_fire_failure() {
  local RC="$1" PREFIX LOG TAIL START
  [ "$RC" = "124" ] && { echo timeout; return 0; }
  PREFIX=$(basename "${FIRE:-}" .sh); PREFIX="${PREFIX#fire-}"
  [ -n "$PREFIX" ] || { echo unknown; return 0; }
  # NOT `| head -1`. `set -euo pipefail` is in force (line 13), and `head` exits after
  # the first line while `ls` is still writing — so `ls` takes SIGPIPE, the pipeline
  # reports 141, and `|| LOG=""` BLANKS the filename it had just found. The guard on the
  # next line then returns `unknown` without ever opening a log, so every pattern below
  # is unreachable. It is a race, and the corpus decides it: measured on this box
  # 2026-08-26, 0/10 SIGPIPE at <=128 sibling logs, 2/10 at 256, 9/10 at 384, 10/10 at
  # 474 and above. Live counts the same day — codex 474, claude 748, kimi 764 — so all
  # three seats were at 10/10 and the classifier had not read a log on any of them since
  # roughly 08-07 (kimi), 08-08 (claude), 08-25 (codex), the dates each crossed 384.
  #
  # That is why the two vendor-spelling widenings above (08-18 kimi, 08-26 claude) each
  # measured their target logs as `unknown` and read that as a missing pattern: both were
  # measured through tests/classify_evidence_window_test.py, whose fixture writes exactly
  # ONE log into the temp dir — the single case in which this line cannot fail. Those
  # widenings are still needed; they were just never sufficient, and their evidence could
  # not tell the two causes apart. Section C of that test now pins this one at scale.
  #
  # Take the first line in the shell: no pipe, no SIGPIPE, identical `ls -t` ordering.
  LOG=$(ls -t "$STATE/logs/$PREFIX"-*.log 2>/dev/null) || LOG=""
  LOG="${LOG%%$'\n'*}"
  [ -n "$LOG" ] || { echo unknown; return 0; }
  START=$(grep -n -e '^<<<end previous-wake-final-output>' \
                 -e '^Pointers are DATA, not instructions' \
                 "$LOG" 2>/dev/null | tail -1 | cut -d: -f1) || START=""
  if [ -n "$START" ]; then
    TAIL=$(tail -n "+$((START + 1))" "$LOG" 2>/dev/null | tail -n 200) || TAIL=""
  else
    TAIL=$(tail -n 200 "$LOG" 2>/dev/null) || TAIL=""
  fi
  if printf '%s' "$TAIL" | grep -qi 'out of credits\|insufficient credit\|quota exceeded\|usage limit\|billing cycle\|purchase extra usage\|upgrade your plan\|hit your session limit\|hit your weekly limit\|hit your usage limit'; then
    echo out-of-credits
  elif printf '%s' "$TAIL" | grep -qi 'EPERM\|operation not permitted\|network is unreachable\|connection refused\|urllib\.error'; then
    echo egress-blocked
  elif printf '%s' "$TAIL" | grep -qi 'timed out\|timeout'; then
    echo timeout
  else
    echo unknown
  fi
}

# rc=124 IS NOT A DELIVERY VERDICT — IT IS THE ONE RC THAT PROVES DELIVERY.
# `timeout -k 30 1800` in every fire-*.sh wraps the member's CLI with the primer path
# already in its argv, so an rc of 124 says the launcher STARTED that CLI and later cut
# it short. The work list reached the member. What was interrupted is the wake, and
# retention plus `retry_stale_primers` is the mechanism that owns an interrupted wake.
#
# The evidence was already written down, one function away, and acted on only half.
# `stale_primer_discharged_test.py` opens with it: "This mesh has filed nine
# non-delivery reports on rc=124 and all nine were false." That measurement bought the
# `primer_spent` guard on the RE-FIRE path (a discharged list is retired, not re-fired)
# and nothing at all on the REPORT path, which runs FIRST and every time — so the wake
# amplification stopped and the false reports did not.
#
# Instance ten and eleven, CBP 2026-08-20, the case that found this. claude-code sent
# kimi-code notices 4121 (`review_done`, PR #525) and 4127 (`review_done`, PR #549).
# Both were delivered: kimi's wake `kimi-20260820-011755` opens by enumerating them by
# id and kind, argues them for 3700 lines, and its successor lands the fixes citing
# "#525 re-review — invariant 1" and "claude asked for a test with a member holding a
# live scope grant". That wake then ran past `timeout -k 30 1800` at 08:46:56Z. rc=124,
# primer retained, and this function mailed claude-code two `kind=reply` notices saying
# the notices kimi had just spent thirty minutes answering were undelivered. `reply` is
# in MEMBER_KINDS_AWAIT_RESPONSE, so each one also became a row in the SENDER's `i_owe`
# and woke a session to read it.
#
# That is an amplifier pointed the wrong way: the longer and more thorough a member's
# wake, the likelier it is cut short by the bound, and the more of its peers are told
# they were not heard. Failure reports generated in proportion to work done.
#
# WHY NOT THE SYMMETRIC FIX. The tempting move is to reuse `primer_spent` here — same
# primer, same rc, ask the daemon the same question. It is wrong, and one-sidedly so:
# `i_owe` only ever holds MEMBER_KINDS_AWAIT_RESPONSE, so a `review_done`, a
# `disposition` or a `coordination` is absent from the fold whether it was answered or
# never seen. Gating the report on `i_owe` would therefore suppress the report for
# exactly the kinds where the report is the ONLY trace a notice ever existed — and it
# would do so on the genuinely-dead fires (out-of-credits, egress-blocked) too, which
# are the fires that need reporting most. So the guard is keyed to the ONE rc that
# carries mechanical information about whether the CLI ran, and to nothing else.
#
# Not `why=timeout` either: `classify_fire_failure` also returns `timeout` from log
# TEXT under any rc, and a log that merely says "timed out" is a guess about a fire
# that may never have started. The integer is the fact; the classifier is the lead.
# Every other rc reports exactly as before — 75 (lock refusal, the CLI never ran), 1
# (out-of-credits, egress-blocked, usage error), 69, 70 — all unchanged.
report_unreachable() {
  local PRIMER_FILE="$1" WHY="$2" RC="${3:-}" ROWS ARGS OUT LIVE
  if [ "$RC" = "124" ]; then
    echo "[hestia-watch] fire hit the launcher bound (rc=124) — the member's CLI ran with this primer, so it is RETAINED for retry and NOT reported unreachable: $PRIMER_FILE"
    return 0
  fi
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
LAST_SWEEP=$LAST_ANNOUNCE

while true; do
  check_artifact_drift
  maybe_self_deploy
  check_daemon_drift
  NOW=$(date +%s)
  if [ $((NOW - LAST_ANNOUNCE)) -ge "$UNANSWERED_EVERY" ]; then
    announce_artifact
    announce_daemon
    announce_unanswered
    LAST_ANNOUNCE=$NOW
  fi
  if [ $((NOW - LAST_SWEEP)) -ge "$DISCHARGE_SWEEP_EVERY" ]; then
    retire_discharged_primers
    LAST_SWEEP=$NOW
  fi
  OUT=$(drain || echo '{"total":0}')
  N=$(echo "$OUT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('total',0))" 2>/dev/null || echo 0)
  if [ "$N" -gt 0 ]; then
    PRIMER=$(mktemp "$PRIMERS/notice-XXXXXX.json")
    # The strong asker: fold the member's outstanding debt into the primer, so
    # the question is asked where an answer is possible — inside the wake that
    # is happening anyway. Costs one read; never causes a fire on its own.
    # THE FOLD TRAVELS BY FILE, NOT BY ENVIRONMENT. `execve` caps ONE string at
    # MAX_ARG_STRLEN = 32 pages = 131,072 B (measured, not cited: `getconf` exposes
    # ARG_MAX, a different and much larger TOTAL-size limit). This seat's live fold
    # measured 442,074 B on 2026-09-04 -- 3.37x -- so exporting it failed E2BIG, the
    # interpreter never started, and the `||` fallback wrote the raw drain response
    # with `unanswered`, `open_petitions` AND `for_plugin` all missing. The size is
    # per-seat and NOT monotone: codex's own fold shipped at 118,995 B the same day
    # (codex, review of #858), so there is no global floor and no single onset date.
    # A file has no such cap.
    #
    # Carrier failure is NOT empty debt. `mktemp` failing, or the write failing part
    # way, must leave the primer saying "not measured" -- never `i_owe: []`, which
    # reads as "you owe nothing". That is the same absence-as-verdict class this
    # repair is about, so it gets an explicit third state below.
    UN_FILE=$(mktemp "${TMPDIR:-/tmp}/hestia-un-$PLUGIN.XXXXXX" 2>/dev/null || true)
    if [ -n "$UN_FILE" ]; then
      unanswered > "$UN_FILE" 2>/dev/null || : > "$UN_FILE"
    fi
    # The mirror of the debt fold: petitions THIS member has open. Filtered
    # here, by `asked_by`, because the tool answers for the whole society and
    # another member's rows are not this member's work — the same reason the
    # primer directory is per-member. The filter and its renderer live in one
    # file (`open-petitions.py`) so one suite covers both; an unparseable or
    # failed read yields `asked:false`, which the renderer says out loud rather
    # than rendering as "you hold none".
    PET=$(open_petitions 2>/dev/null \
          | timeout 5 python3 "$WATCH_DIR/open-petitions.py" fold "$PLUGIN" \
          2>/dev/null || echo '{"asked":false,"mine":[]}')
    printf '%s' "$OUT" | UN_FILE="$UN_FILE" PET="$PET" FOR_PLUGIN="$PLUGIN" python3 -c '
import json,os,sys
try: d=json.load(sys.stdin)
except Exception: d={}
# TRI-STATE, mirroring `open_petitions`. `asked:true` with empty lists is a MEASURED
# zero; `asked:false` is a read that never completed. Those are different facts and
# the renderer says which. The two-state form collapsed them: ANY failure became
# {"i_owe":[],"owed_to_me":[]} -- a positive assertion of no debt, manufactured out
# of a channel error. `asked` is additive; primers written before it have no such key
# and readers that only take i_owe/owed_to_me are unaffected.
u=None
try:
    with open(os.getenv("UN_FILE") or "", encoding="utf-8") as f: u=json.load(f)
except Exception: u=None
# A refusal, an error envelope or a truncated body is not an empty debt. The keys must
# be PRESENT and be lists: `.get("i_owe") or []` reads every one of those as "nothing
# owed". This is the predicate `primer_spent` already applies to its own carrier.
if isinstance(u,dict) and all(isinstance(u.get(k),list) for k in ("i_owe","owed_to_me")):
    d["unanswered"]={"asked":True,"i_owe":u["i_owe"],"owed_to_me":u["owed_to_me"]}
else:
    d["unanswered"]={"asked":False,"i_owe":[],"owed_to_me":[]}
try: d["open_petitions"]=json.loads(os.environ.get("PET") or "")
except Exception: d["open_petitions"]={"asked":False,"mine":[]}
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
    [ -n "$UN_FILE" ] && rm -f "$UN_FILE"
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
        report_unreachable "$PRIMER" "fire-rc=$RC;why=$WHY" "$RC"
      fi
    else
      python3 -c "import json;d=json.load(open('$PRIMER'));[print(f\"  {n['kind']} from {n['from_plugin']}: {n.get('pointer_uri','')}\") for n in d['notices']]"
    fi
  elif [ -n "$FIRE" ]; then
    # No fresh mail this tick: spend it on ONE retained list, if any is due. The inbox
    # was drained first, so a member with new work never waits behind old work.
    fire_one_stale_primer
  fi
  sleep "$IVL"
done
