#!/usr/bin/env python3
"""Minimal MCP JSON-RPC client for the local hestia daemon (kimi-code seat)."""
import json, os, sys, urllib.request

EP = os.getenv("HESTIA_ENDPOINT", "http://127.0.0.1:7711/mcp")

def post(payload, hdrs=None):
    req = urllib.request.Request(EP, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream", **(hdrs or {})})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode(), r.headers.get("mcp-session-id")

def rpc(h, name, args):
    body, _ = post({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                    "params": {"name": name, "arguments": args}}, h)
    for line in body.splitlines():
        if not line.startswith("data: {"):
            continue
        envelope = json.loads(line[6:])
        if "error" in envelope and "result" not in envelope:
            return {"_hestia_error": {"code": "jsonrpc_error", "data": envelope["error"]}}
        try:
            return json.loads(envelope["result"]["content"][0]["text"])
        except (KeyError, IndexError, TypeError, json.JSONDecodeError):
            return {"raw_result": envelope.get("result")}
    return {"raw_body": body[:2000]}

def connect():
    _, sid = post({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {
        "protocolVersion": "2024-11-05", "capabilities": {},
        "clientInfo": {"name": "hestia-mesh", "version": "1"}}})
    h = {"mcp-session-id": sid} if sid else {}
    post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, h)
    c = rpc(h, "hestia_connect", {"plugin_id": "kimi-code", "host_agent": "kimi-code-cli",
                                  "instance_name": "mesh-kimi-code",
                                  "role": "role:constellation:mesh-worker"})
    return h, c

if __name__ == "__main__":
    h, c = connect()
    print("CONNECT:", json.dumps(c)[:300], file=sys.stderr)
    out = rpc(h, sys.argv[1], json.loads(sys.argv[2]) if len(sys.argv) > 2 else {})
    print(json.dumps(out, indent=2))
