#!/usr/bin/env python3
"""Wake-1046: full request rows + chain entries for the three cbp-being petitions."""
import json, os, urllib.request

EP = os.environ.get("HESTIA_ENDPOINT", "http://127.0.0.1:7711/mcp")
PLUGIN = os.environ.get("HESTIA_MESH_PLUGIN", "kimi-code")
IDS = ["scope-0bbe6e4be55a", "scope-4a95f370881c", "scope-aab8ec45db8d"]


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
    raise SystemExit("no data frame")


_, sid = post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
               "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                          "clientInfo": {"name": "kimi-wake1046", "version": "1"}}})
h = {"mcp-session-id": sid} if sid else {}
post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, h)
rpc(h, "hestia_connect", {"plugin_id": PLUGIN, "host_agent": f"{PLUGIN}-cli",
                          "instance_name": f"wake1046-{PLUGIN}"})

out = rpc(h, "hestia_scope_status", {"plugin_id": PLUGIN})
for r in out.get("requests", []):
    if r.get("request_id") in IDS:
        print("=== status row ===")
        print(json.dumps(r, indent=1))

d = rpc(h, "hestia_query_history", {"filter": {"limit": 500}})
entries = d.get("entries", [])
print(f"chain window: {len(entries)} entries")
for e in entries:
    blob = json.dumps(e)
    if any(i.split("-", 1)[1] in blob for i in IDS):
        print("=== chain entry ===")
        print(json.dumps(e, indent=1))
