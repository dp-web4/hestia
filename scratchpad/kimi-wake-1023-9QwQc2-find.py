#!/usr/bin/env python3
"""Locate scope request 5823dd46c9f0 across members, as kimi-code."""
import json
from os import getenv
import urllib.request

EP = getenv("HESTIA_ENDPOINT", "http://127.0.0.1:7711/mcp")
TIMEOUT = 30.0
TARGET = "5823dd46c9f0"

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
            content = env["result"]["content"][0]["text"]
            try:
                return json.loads(content)
            except json.JSONDecodeError:
                return {"_raw": content}
    raise SystemExit("no data frame: " + body[:500])

_, sid = post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
               "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                          "clientInfo": {"name": "kimi-31765-find", "version": "1"}}})
h = {"mcp-session-id": sid} if sid else {}
post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, h)
rpc(h, "hestia_connect", {"plugin_id": "kimi-code", "host_agent": "kimi-code-cli",
                          "instance_name": "scope-find-kimi-code",
                          "role": "role:constellation:interactive-dev"})

for member in ["claude-code", "cbp-being", "codex", "kimi-code", "gemini"]:
    try:
        out = rpc(h, "hestia_scope_status", {"plugin_id": member})
    except SystemExit as e:
        print(f"== {member}: ERROR {e}")
        continue
    reqs = out.get("requests", []) if isinstance(out, dict) else []
    hits = [r for r in reqs if TARGET in r.get("request_id", "")]
    print(f"== {member}: {len(reqs)} requests, {len(hits)} match")
    for r in hits:
        print(json.dumps(r, indent=2))
