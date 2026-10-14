#!/usr/bin/env python3
"""Walk the witness chain backward from head looking for any entry naming a scope id.

Prints every matching entry plus any session_started / daemon-lifecycle marker seen
on the way, and stops once timestamps fall below the target window.
"""
import importlib.util, json, sys

spec = importlib.util.spec_from_file_location(
    "hm", "/home/dp/ai-workspace/hestia/plugins/member-mesh/hestia-mesh.py")
hm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hm)

NEEDLE = sys.argv[1]                      # e.g. scope-14e57e4945f4
STOP_TS = sys.argv[2]                     # e.g. 2026-10-14T03:10:00  (walk stops below this)

h, s = hm.connect()
# find head
out = hm.rpc(h, "hestia_query_history", {"filter": {"limit": 1}})
head = out["entries"][0]
print(f"head: pos={head['chainPosition']} ts={head['timestamp']}", flush=True)

cursor = head["hash"]
hops = 0
matches = []
lifecycle = []
while True:
    e = hm.rpc(h, "hestia_query_history", {"filter": {"hash": cursor}})
    ent = e.get("entry") or e
    if "_hestia_error" in e or "_jsonrpc_error" in e:
        print("walk terminated:", json.dumps(e)[:300], flush=True)
        break
    ts = ent.get("timestamp", "")
    et = ent.get("eventType", "")
    blob = json.dumps(ent)
    if NEEDLE in blob:
        matches.append(ent)
        print(f"MATCH pos={ent.get('chainPosition')} ts={ts} type={et}", flush=True)
        print(json.dumps(ent)[:900], flush=True)
    if et in ("session_started", "daemon_started", "daemon_stopped", "deploy", "restart"):
        lifecycle.append((ent.get("chainPosition"), ts, et))
        print(f"LIFECYCLE pos={ent.get('chainPosition')} ts={ts} type={et}", flush=True)
    hops += 1
    if hops % 500 == 0:
        print(f"...pos={ent.get('chainPosition')} ts={ts} hops={hops}", flush=True)
    if ts < STOP_TS:
        print(f"reached stop horizon at pos={ent.get('chainPosition')} ts={ts}", flush=True)
        break
    prev = ent.get("prevHash")
    if not prev or set(prev) == {"0"}:
        print("genesis reached", flush=True)
        break
    cursor = prev

print(f"\nDONE hops={hops} matches={len(matches)} lifecycle={len(lifecycle)}", flush=True)
