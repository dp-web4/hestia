#!/usr/bin/env bash
# Real-daemon escalation-bar test over the re-stack: an ISOLATED daemon built from the merge
# (port 7797, throwaway home), the patched governed modules swapped in via run_one.py.
# Never :7711. Usage: real_daemon.sh [unpatched]
set -u
SP=/tmp/claude-1000/-home-dp-ai-workspace/9261dc9a-1703-4964-9e72-a076bd468aca/scratchpad
RS=$SP/rs1247
W=/home/dp/ai-workspace/hestia/scratchpad/wt-1247-restack-af33
BIN=$SP/target-hestia-conc-nodbg/debug/hestia
PORT=7797
[ -x "$BIN" ] || { echo "no binary at $BIN"; exit 2; }
out=$(bash "$SP/iso_daemon.sh" start "$BIN" "$PORT") || { echo "$out"; exit 1; }
echo "$out"
home=${out#HOME=}; home=${home%% PID=*}
cleanup() { bash "$SP/iso_daemon.sh" stop "$home/serve.pid"; }
trap cleanup EXIT
# readiness: an MCP initialize must answer
init='{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"rs-ready","version":"1"}}}'
for _ in $(seq 1 120); do
  curl -fsS --max-time 10 -H 'Content-Type: application/json' -H 'Accept: application/json, text/event-stream' \
    -d "$init" "http://127.0.0.1:$PORT/mcp" 2>/dev/null | grep -q '"result"' && break
  sleep 1
done
cd "$W" || exit 1
TH=$HOME/.cache/rs1247-home-rd
mkdir -p "$TH/hestia"
if [ "${1:-}" = unpatched ]; then extra=(RS_UNPATCHED=1); src=(); else extra=(); src=("$W/tools/escalation_bar_real_daemon_test.py"); fi
env -i PATH="$PATH" HOME="$TH" HESTIA_HOME="$TH/hestia" W="$W" "${extra[@]}" \
  HESTIA_ESCALATION_BAR_ENDPOINT="http://127.0.0.1:$PORT/mcp" PYTHONDONTWRITEBYTECODE=1 \
  timeout 1200 python3 "$RS/run_one.py" tools/escalation_bar_real_daemon_test.py
echo "TEST_EXIT $?"
