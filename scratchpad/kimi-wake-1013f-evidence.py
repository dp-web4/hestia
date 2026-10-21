#!/usr/bin/env python3
"""Pull escalation evidence bundle + poll status for 84ebc732b022e857."""
import json, sys
sys.path.insert(0, "/home/dp/.kimi-code/hestia-instance")
import mcp_call

h, sid = mcp_call.connect()
out = {}
for name, args in [
    ("hestia_escalation_evidence", {"escalation_id": "84ebc732b022e857"}),
    ("hestia_gate_escalation_poll", {"escalation_id": "84ebc732b022e857", "session_id": sid}),
]:
    body, _ = mcp_call.post({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
                             "params": {"name": name, "arguments": args}}, h)
    rec = None
    for line in body.splitlines():
        if line.startswith("data: {"):
            env = json.loads(line[6:])
            content = env.get("result", {}).get("content", [])
            if content:
                try:
                    rec = json.loads(content[0].get("text", ""))
                except ValueError:
                    rec = {"_raw": content[0].get("text", "")}
            elif "error" in env:
                rec = {"_error": env["error"]}
            break
    out[name] = rec
path = "/home/dp/ai-workspace/hestia/scratchpad/kimi-wake-1013f-evidence.json"
with open(path, "w", encoding="utf-8") as f:
    json.dump(out, f, indent=1)
print(f"wrote {path}")
