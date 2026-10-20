#!/usr/bin/env python3
"""One-off: list hestia MCP tools matching scope/withdraw/appeal/petition."""
import json
import os
import urllib.request

EP = os.environ.get("HESTIA_ENDPOINT", "http://127.0.0.1:7711/mcp")


def post(payload, hdrs=None):
    req = urllib.request.Request(
        EP, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream", **(hdrs or {})})
    r = urllib.request.urlopen(req, timeout=30)
    return r.read().decode(), r.headers.get("mcp-session-id")


_, sid = post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
               "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                          "clientInfo": {"name": "kimi-tools", "version": "1"}}})
h = {"mcp-session-id": sid} if sid else {}
post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, h)
body, _ = post({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}, h)
for line in body.splitlines():
    if line.startswith("data: {"):
        env = json.loads(line[6:])
        names = [t["name"] for t in env["result"]["tools"]]
        print("\n".join(n for n in names
                        if any(k in n for k in ("scope", "withdraw", "appeal", "petition"))))
        break
