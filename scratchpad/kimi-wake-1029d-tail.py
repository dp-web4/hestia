#!/usr/bin/env python3
"""wake-1029d: fetch the witness-chain tail to record the 3 reply sends' ids + binding."""
import importlib.util
import json

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()

body, _ = hm.post({"jsonrpc": "2.0", "id": 9, "method": "tools/call",
                   "params": {"name": "hestia_query_history",
                              "arguments": {"filter": {"limit": 12}}}}, h)
for line in body.splitlines():
    if line.startswith("data: {"):
        env = json.loads(line[6:])
        res = env.get("result", env)
        try:
            data = json.loads(res["content"][0]["text"])
        except Exception:
            data = res
        entries = data.get("entries", [])
        for e in entries:
            kind = e.get("kind") or e.get("event") or ""
            if "notice" in str(kind):
                print(json.dumps(e, indent=1)[:1200])
                print("---")
        break
