#!/usr/bin/env python3
"""Peek another plugin's live scope map (read-only) for a specific request id.

Usage: HESTIA_PEEK_PLUGIN=cbp-being python3 kimi-wake-1028h-peek.py scope-bb1f34877eab
Modeled on kimi-scope-status.py; connects as kimi-code, queries the named plugin's view.
"""
import json
import os
import sys
import urllib.request

EP = os.environ.get("HESTIA_ENDPOINT", "http://127.0.0.1:7711/mcp")
PEEK = os.environ.get("HESTIA_PEEK_PLUGIN", "cbp-being")


def post(payload, hdrs=None):
    req = urllib.request.Request(
        EP, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream", **(hdrs or {})})
    r = urllib.request.urlopen(req, timeout=30)
    return r.read().decode(), r.headers.get("mcp-session-id")


def rpc(h, name, args):
    body, _ = post({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                    "params": {"name": name, "arguments": args}}, h)
    for line in body.splitlines():
        if line.startswith("data: {"):
            env = json.loads(line[6:])
            return json.loads(env["result"]["content"][0]["text"])
    raise SystemExit("no data frame: " + body[:400])


_, sid = post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
               "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                          "clientInfo": {"name": "kimi-scope-peek", "version": "1"}}})
h = {"mcp-session-id": sid} if sid else {}
post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, h)
rpc(h, "hestia_connect", {"plugin_id": "kimi-code", "host_agent": "kimi-code-cli",
                          "instance_name": "scope-peek-kimi-code"})
out = rpc(h, "hestia_scope_status", {"plugin_id": PEEK})
want = sys.argv[1] if len(sys.argv) > 1 else None
for r in out.get("requests", []):
    if want and want not in r.get("request_id", ""):
        continue
    print(json.dumps(r, indent=2))
