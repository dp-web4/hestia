#!/usr/bin/env python3
"""Read scope petition ff6e53552207 status as kimi-code, looking at cbp-being's records."""
import json
from os import getenv
import urllib.request

EP = getenv("HESTIA_ENDPOINT", "http://127.0.0.1:7711/mcp")
TIMEOUT = 30.0

def post(payload, hdrs=None):
    req = urllib.request.Request(
        EP, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream", **(hdrs or {})})
    r = urllib.request.urlopen(req, timeout=TIMEOUT)
    return r.read().decode(), r.headers.get("mcp-session-id")

def rpc(h, name, args):
    body, _ = post({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                    "params": {"name": name, "arguments": args}}, h)
    for line in body.splitlines():
        if line.startswith("data: {"):
            env = json.loads(line[6:])
            return json.loads(env["result"]["content"][0]["text"])
    raise SystemExit("no data frame: " + body[:500])

_, sid = post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
               "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                          "clientInfo": {"name": "kimi-31670-read", "version": "1"}}})
h = {"mcp-session-id": sid} if sid else {}
post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, h)
rpc(h, "hestia_connect", {"plugin_id": "kimi-code", "host_agent": "kimi-code-cli",
                          "instance_name": "scope-read-kimi-code",
                          "role": "role:constellation:interactive-dev"})
out = rpc(h, "hestia_scope_status", {"plugin_id": "cbp-being"})
for r in out.get("requests", []):
    if "ff6e53552207" in r.get("request_id", ""):
        print(json.dumps(r, indent=2))
