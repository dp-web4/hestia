#!/usr/bin/env python3
"""wake-1027s: backward chain walk from an anchor hash, collecting entries that name
an escalation id. Anchor via the escalation resource's settled/expired entry; walk
uses hestia_query_history filter.hash pointer lookups (~1ms/hop). Usage:
    kimi-wake-1027s-chainwalk.py <escalation_id> [max_hops]"""
import importlib.util
import json
import sys

sys.path.insert(0, "/home/dp/ai-workspace/hestia/tools")
from claude_daemon_client import call

needle = sys.argv[1]
max_hops = int(sys.argv[2]) if len(sys.argv) > 2 else 1600
ZERO = "0" * 64

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)
h, s = hm.connect()
body, _ = hm.post({"jsonrpc": "2.0", "id": 7, "method": "resources/read",
                   "params": {"uri": f"hestia://escalation/{needle}"}}, h)
doc = None
for line in body.splitlines():
    if line.startswith("data: {"):
        env = json.loads(line[6:])
        doc = json.loads(env["result"]["contents"][0]["text"])
        break
anchor = doc.get("settled_entry") or doc.get("expired_entry") or doc.get("open_entry")
print("anchor:", anchor.get("eventType"), anchor.get("chainPosition"), anchor.get("hash"))

cur, hops, hits = anchor["prevHash"], 0, []
while cur and cur != ZERO and hops < max_hops:
    out = call("hestia_query_history", {"filter": {"hash": cur}})
    e = out.get("entry") or {}
    if not e:
        break
    hops += 1
    if needle in json.dumps(e):
        hits.append(e)
    cur = e.get("prevHash")
print("hops:", hops, "hits:", len(hits))
for e in hits:
    ed = e.get("eventData", {})
    row = {"pos": e.get("chainPosition"), "ts": e.get("timestamp"), "type": e.get("eventType")}
    for k in ("by", "dissent", "stance", "argument", "channel", "independence"):
        if ed.get(k) is not None:
            row[k] = ed[k]
    print(json.dumps(row)[:600])
