#!/usr/bin/env bash
# interactive_live_test.sh — the yield predicate and the heartbeat touch.
#
# The break this guards (dp 2026-07-30): an interactive author's reply was eaten
# by the watcher into a headless instance. The fix has two halves and both are
# tested against the real artifacts, not fixtures of them:
#   A. interactive-live.sh yields ONLY on a fresh heartbeat (the watcher must
#      not starve on a stale or absent one — a dead member's mail must move).
#   B. the kimi gate's heartbeat touch fires on every event, including events
#      that later deny — liveness is proven by activity, not by outcome.
set -u
MESH="$(cd "$(dirname "$0")/.." && pwd)"
D=$(mktemp -d); trap 'rm -rf "$D"' EXIT
P=0; F=0
ok(){ P=$((P+1)); echo "  PASS  $1"; }
no(){ F=$((F+1)); echo "  FAIL  $1"; }

HB="$D/hestia-instance/interactive-heartbeat"

# --- A1: absent heartbeat -> NOT live (wake path preserved)
if WATCH_MEMBER=kimi-code HEARTBEAT_FILE="$HB" "$MESH/interactive-live.sh"; then
  no "A1: absent heartbeat read as live"
else
  ok "A1: absent heartbeat -> watcher keeps the wake path"
fi

# --- A2: fresh heartbeat -> live (watcher yields)
mkdir -p "$(dirname "$HB")" && touch "$HB"
WATCH_MEMBER=kimi-code HEARTBEAT_FILE="$HB" "$MESH/interactive-live.sh" \
  && ok "A2: fresh heartbeat -> yield" || no "A2: fresh heartbeat not honored"

# --- A3: stale heartbeat -> NOT live (a dead interactive session's mail must move)
touch -d "10 minutes ago" "$HB"
if WATCH_MEMBER=kimi-code HEARTBEAT_FILE="$HB" "$MESH/interactive-live.sh"; then
  no "A3: stale (10 min) heartbeat read as live — a dead session would hold mail hostage"
else
  ok "A3: stale heartbeat -> wake path resumes"
fi

# --- A4: HOLD_SECS is honored (a slow-but-alive session can widen its window)
if WATCH_MEMBER=kimi-code HEARTBEAT_FILE="$HB" HOLD_SECS=900 "$MESH/interactive-live.sh"; then
  ok "A4: HOLD_SECS=900 admits the 10-minute-old heartbeat"
else
  no "A4: HOLD_SECS override ignored"
fi

# --- B1: the gate touches the heartbeat on an ordinary event
GATE_HOME="$D/kimi-home"
mkdir -p "$GATE_HOME/.kimi-code/hestia-instance"
cat > "$D/allow-event.json" <<'J'
{"hook_event_name":"PreToolUse","tool_name":"Read","tool_input":{"file_path":"/tmp/x"},"cwd":"/tmp"}
J
HOME="$GATE_HOME" python3 "$MESH/../kimi/hooks/pre_tool_use.py" < "$D/allow-event.json" >/dev/null 2>&1
RC=$?
[ -f "$GATE_HOME/.kimi-code/hestia-instance/interactive-heartbeat" ] \
  && ok "B1: heartbeat written by the gate (rc=$RC)" \
  || no "B1: no heartbeat after a gate call"

# --- B2: and on an event the gate DENIES (liveness is activity, not outcome)
cat > "$D/deny-event.json" <<'J'
{"hook_event_name":"PreToolUse","tool_name":"Read","tool_input":{"file_path":"/home/dp/.ssh/id_rsa"},"cwd":"/tmp"}
J
rm -f "$GATE_HOME/.kimi-code/hestia-instance/interactive-heartbeat"
HOME="$GATE_HOME" python3 "$MESH/../kimi/hooks/pre_tool_use.py" < "$D/deny-event.json" >/dev/null 2>&1
[ -f "$GATE_HOME/.kimi-code/hestia-instance/interactive-heartbeat" ] \
  && ok "B2: heartbeat written even on a denied act" \
  || no "B2: denied act left no heartbeat — the watcher could not tell a punished session from a dead one"

echo
echo "$P passed, $F failed"
[ "$F" -eq 0 ]
