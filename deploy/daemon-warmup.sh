#!/usr/bin/env bash
# hestia daemon warm-up — runs as ExecStartPost so the ~5.7s cold first-connect
# (issue #423: reputation-store page-in on the DeltaClass-era build) is paid HERE,
# inside the restart, never on a member's gate call. Bounded; failure is non-fatal
# (the daemon still serves — members would just meet the cold path as before).
set -u
EP="${HESTIA_ENDPOINT:-http://127.0.0.1:7711/mcp}"
DEADLINE=$(( $(date +%s) + 45 ))
python3 - "$EP" <<'PY' 2>/dev/null
import json, sys, time, urllib.request
ep = sys.argv[1]
def post(payload, sid=None, timeout=20):
    h = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if sid:
        h["Mcp-Session-Id"] = sid
    r = urllib.request.urlopen(
        urllib.request.Request(ep, json.dumps(payload).encode(), h), timeout=timeout)
    r.read()
    return r.headers.get("Mcp-Session-Id")
t0 = time.time()
for attempt in range(20):
    try:
        sid = post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                    "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                               "clientInfo": {"name": "systemd-warmup", "version": "1"}}})
        post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, sid)
        # The call that pays the cold cost (measured 5.7s cold / 1ms warm) — and the
        # cost is PER-PLUGIN (measured: warming claude-code left the codex path cold),
        # so warm every registered member. Labeled as the warm-up: honest witness grain.
        for pid in ("claude-code", "kimi-code", "codex", "gemini"):
            post({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                  "params": {"name": "hestia_connect",
                             "arguments": {"plugin_id": pid,
                                           "host_agent": "systemd-warmup",
                                           "host_session_id": "systemd-warmup"}}})
        print(f"warm in {time.time()-t0:.1f}s after {attempt+1} attempt(s)")
        break
    except Exception:
        time.sleep(1.5)
PY
exit 0
