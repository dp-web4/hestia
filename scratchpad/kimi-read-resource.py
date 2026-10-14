#!/usr/bin/env python3
"""One-off: read hestia:// resources as a member (kimi-code), print JSON bodies.

usage: kimi-read-resource.py <uri> [<uri>...]
"""
import json, os, sys, urllib.request

EP = os.environ.get("HESTIA_ENDPOINT", "http://127.0.0.1:7711/mcp")
PLUGIN = os.environ.get("HESTIA_MESH_PLUGIN", "kimi-code")
TIMEOUT = float(os.environ.get("HESTIA_MESH_TIMEOUT", "30"))


def post(payload, hdrs=None):
    req = urllib.request.Request(
        EP, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream", **(hdrs or {})})
    r = urllib.request.urlopen(req, timeout=TIMEOUT)
    return r.read().decode(), r.headers.get("mcp-session-id")


def rpc(h, method, params, i=[100]):
    i[0] += 1
    body, _ = post({"jsonrpc": "2.0", "id": i[0], "method": method, "params": params}, h)
    for line in body.splitlines():
        if line.startswith("data: {"):
            return json.loads(line[6:])
    raise SystemExit("no data frame for " + method)


_, sid = post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
               "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                          "clientInfo": {"name": "kimi-read-resource", "version": "1"}}})
h = {"mcp-session-id": sid} if sid else {}
post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, h)
rpc(h, "tools/call", {"name": "hestia_connect", "arguments": {
    "plugin_id": PLUGIN, "host_agent": f"{PLUGIN}-cli",
    "instance_name": f"read-resource-{PLUGIN}",
    **({"role": os.environ["HESTIA_ROLE"]} if os.environ.get("HESTIA_ROLE") else {})}})

for uri in sys.argv[1:]:
    out = rpc(h, "resources/read", {"uri": uri})
    for c in out.get("result", {}).get("contents", []):
        print("==", uri)
        try:
            print(json.dumps(json.loads(c.get("text", "")), indent=2))
        except Exception:
            print(c.get("text", ""))
