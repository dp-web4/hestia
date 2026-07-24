#!/usr/bin/env python3
"""hestia-mesh — member-mesh CLI for a local hestia member (Kimi's send/receive surface).

Usage:
  hestia-mesh.py peek                                    # non-consuming inbox list
  hestia-mesh.py drain                                   # consume-once drain (act on results!)
  hestia-mesh.py send <to_plugin_id> <kind> <pointer_uri>  # witnessed notify

Env: HESTIA_ENDPOINT (default http://127.0.0.1:7711/mcp),
     HESTIA_MESH_PLUGIN (default kimi-code), HESTIA_MESH_HOST_AGENT (default kimi-code-cli).
Kinds: coordination|review_request|review_done|reply|handoff|forum-note|ack (ack terminal).
Discipline: forum post = record, mesh notice = wake; content lives at the pointer.
"""
import json, os, sys, urllib.request

EP = os.environ.get("HESTIA_ENDPOINT", "http://127.0.0.1:7711/mcp")
PLUGIN = os.environ.get("HESTIA_MESH_PLUGIN", "kimi-code")
HOST = os.environ.get("HESTIA_MESH_HOST_AGENT", "kimi-code-cli")

def post(payload, hdrs={}):
    req = urllib.request.Request(EP, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream", **hdrs})
    r = urllib.request.urlopen(req, timeout=5)
    return r.read().decode(), r.headers.get("mcp-session-id")

def rpc(h, name, args):
    body, _ = post({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                    "params": {"name": name, "arguments": args}}, h)
    for line in body.splitlines():
        if line.startswith("data: {"):
            return json.loads(json.loads(line[6:])["result"]["content"][0]["text"])
    return {}

def connect():
    _, sid = post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                   "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                              "clientInfo": {"name": "hestia-mesh", "version": "1"}}})
    h = {"mcp-session-id": sid} if sid else {}
    post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, h)
    c = rpc(h, "hestia_connect", {"plugin_id": PLUGIN, "host_agent": HOST,
                                  "instance_name": f"mesh-{PLUGIN}"})
    s = c.get("sessionId") or c.get("session_id")
    if not s:
        print(json.dumps({"error": "connect failed", "detail": c}), file=sys.stderr)
        sys.exit(1)
    return h, s

def main():
    if len(sys.argv) < 2 or sys.argv[1] not in ("peek", "drain", "send"):
        print(__doc__); sys.exit(2)
    cmd = sys.argv[1]
    h, s = connect()
    if cmd in ("peek", "drain"):
        out = rpc(h, "hestia_member_inbox", {"session_id": s, "peek": cmd == "peek"})
    else:
        if len(sys.argv) < 5:
            print("usage: hestia-mesh.py send <to_plugin_id> <kind> <pointer_uri>"); sys.exit(2)
        out = rpc(h, "hestia_member_notify",
                  {"to_plugin_id": sys.argv[2], "kind": sys.argv[3],
                   "pointer_uri": sys.argv[4], "session_id": s})
    print(json.dumps(out, indent=1))

if __name__ == "__main__":
    main()
