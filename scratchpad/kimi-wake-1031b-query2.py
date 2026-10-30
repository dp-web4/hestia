#!/usr/bin/env python3
"""Full record for scope-0e8497c61bd5, all fields, no truncation."""
import importlib.util, json, datetime

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

h, s = hm.connect()
body, _ = hm.post({"jsonrpc": "2.0", "id": 7, "method": "resources/read",
                   "params": {"uri": "hestia://scope/scope-0e8497c61bd5"}}, h)
for line in body.splitlines():
    if line.startswith("data: {"):
        env = json.loads(line[6:])
        text = env["result"]["contents"][0]["text"]
        rec = json.loads(text)
        # print every field except the huge act blob, then the blob tail
        blob = rec.pop("requested_because", "")
        print(json.dumps(rec, indent=1))
        for k in ("created_at", "expires_at"):
            if k in rec and isinstance(rec[k], (int, float)):
                print(k, "=", datetime.datetime.fromtimestamp(rec[k], datetime.timezone.utc).isoformat())
        print("--- requested_because length:", len(blob))
        print("blob head:", blob[:400])
        print("blob tail:", blob[-1200:])
        break
