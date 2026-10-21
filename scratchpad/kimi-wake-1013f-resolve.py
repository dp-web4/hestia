#!/usr/bin/env python3
"""Resolve this wake's three pointers in ONE MCP session; save full JSON."""
import json, sys
sys.path.insert(0, "/home/dp/.kimi-code/hestia-instance")
import mcp_call

URIS = [
    "hestia://scope/scope-8a6fe2bac525",
    "hestia://escalation/84ebc732b022e857#corroborate-or-dissent",
    "hestia://scope/scope-55af36c71c49#peer-decide",
]

h, sid = mcp_call.connect()
out = {}
for uri in URIS:
    body, _ = mcp_call.post({"jsonrpc": "2.0", "id": 6, "method": "resources/read",
                             "params": {"uri": uri}}, h)
    rec = None
    for line in body.splitlines():
        if line.startswith("data: {"):
            env = json.loads(line[6:])
            contents = env.get("result", {}).get("contents", [])
            if contents:
                try:
                    rec = json.loads(contents[0].get("text", ""))
                except ValueError:
                    rec = {"_raw": contents[0].get("text", "")}
            elif "error" in env:
                rec = {"_error": env["error"]}
            break
    out[uri] = rec
path = "/home/dp/ai-workspace/hestia/scratchpad/kimi-wake-1013f-records.json"
with open(path, "w", encoding="utf-8") as f:
    json.dump(out, f, indent=1)
print(f"wrote {len(out)} records to {path}")
