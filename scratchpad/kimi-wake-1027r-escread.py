#!/usr/bin/env python3
"""wake-1027r: full escalation resource read + factor scan for a1d902db / 1597c869."""
import json
import os
import sys
import urllib.request

EP = os.environ.get("HESTIA_ENDPOINT", "http://127.0.0.1:7711/mcp")
PLUGIN = os.environ.get("HESTIA_MESH_PLUGIN", "kimi-code")


def post(payload, hdrs=None):
    req = urllib.request.Request(
        EP, data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream", **(hdrs or {})})
    r = urllib.request.urlopen(req, timeout=60)
    return r.read().decode(), r.headers.get("mcp-session-id")


def frames(body):
    for line in body.splitlines():
        if line.startswith("data: {"):
            yield json.loads(line[6:])


_, sid = post({"jsonrpc": "2.0", "id": 1, "method": "initialize",
               "params": {"protocolVersion": "2024-11-05", "capabilities": {},
                          "clientInfo": {"name": "kimi-esc-read", "version": "1"}}})
h = {"mcp-session-id": sid} if sid else {}
post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}, h)
body, _ = post({"jsonrpc": "2.0", "id": 2, "method": "tools/call",
                "params": {"name": "hestia_connect", "arguments":
                           {"plugin_id": PLUGIN, "host_agent": f"{PLUGIN}-cli",
                            "instance_name": f"esc-read-{PLUGIN}"}}}, h)

for uri in sys.argv[1:]:
    body, _ = post({"jsonrpc": "2.0", "id": 3, "method": "resources/read",
                    "params": {"uri": uri}}, h)
    for env in frames(body):
        contents = env.get("result", {}).get("contents", [])
        for c in contents:
            d = json.loads(c.get("text", "{}"))
            slim = {k: d.get(k) for k in
                    ("escalation_id", "status", "tool_name", "opened_at", "expires_at",
                     "decided_at", "decided_by", "consumed_at", "stated_reason",
                     "stated_detail", "marker", "note", "source")}
            print(json.dumps(slim, indent=1))
            se = d.get("settled_entry") or {}
            if se:
                print("settled:", se.get("eventType"), se.get("timestamp"),
                      (se.get("hash") or "")[:16])
                ed = se.get("eventData", {})
                print("settled_data:", json.dumps({k: ed.get(k) for k in
                      ("factors_by", "factors_concurring", "factors_dissenting",
                       "factors_present", "lapsed_at", "decided_by", "decision",
                       "tool_name") if k in ed})[:600])
            fp = d.get("factors_present")
            if isinstance(fp, list):
                for f in fp:
                    print("factor:", f.get("by"), "dissent=", f.get("dissent"),
                          "at=", f.get("at"), "|", (f.get("argument") or "")[:180])
            print("=====")
