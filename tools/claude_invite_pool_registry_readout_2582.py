#!/usr/bin/env python3
"""Read the invitation pool's OWN receipts to settle what populates it.

kimi (notice 2582) and I independently drew the identical 6-name dead pool and
concluded "the pool is the registry". True but incomplete: it does not say why
three demonstrably live seats (claude-code, kimi-code, codex) appear in NO draw,
when handler.rs sorts the pool Live-first and only then caps at MAX_INVITED_PEERS=8.

Live-first ordering means a live member in the registry CANNOT be crowded out by
dead names. So either the live seats are not in the registry, or actor_liveness()
does not call them live. The open entry records both facts, per seat, at invite
time:

  invited_peers            -- who survived the cap
  invitation_evidence      -- [{peer, liveness_at_invite}] for the survivors
  invitation_passed_over   -- [{peer, liveness_at_invite}] the cap dropped

registry size at invite = |invited| + |passed_over| + 1 (the asker, filtered out).

Usage: python3 tools/claude_invite_pool_registry_readout_2582.py [window]
"""
import json
import sys
import urllib.request
from collections import Counter

URL = "http://127.0.0.1:7711/mcp"
WINDOW = int(sys.argv[1]) if len(sys.argv) > 1 else 20000


def rpc(method, params, sid=None, rid=1):
    hdr = {"Content-Type": "application/json", "Accept": "application/json, text/event-stream"}
    if sid:
        hdr["Mcp-Session-Id"] = sid
    req = urllib.request.Request(
        URL,
        data=json.dumps({"jsonrpc": "2.0", "id": rid, "method": method, "params": params}).encode(),
        headers=hdr,
    )
    r = urllib.request.urlopen(req, timeout=120)
    body = r.read().decode()
    out = None
    for line in body.splitlines():
        if line.startswith("data: ") and line[6:].strip().startswith("{"):
            out = json.loads(line[6:])
    return out, r.headers.get("Mcp-Session-Id")


init, sid = rpc("initialize", {"protocolVersion": "2024-11-05", "capabilities": {},
                               "clientInfo": {"name": "claude-code", "version": "1"}})
res, _ = rpc("tools/call", {"name": "hestia_query_history",
                            "arguments": {"filter": {"limit": WINDOW}}}, sid, 2)

text = res["result"]["content"][0]["text"]
try:
    entries = json.loads(text)
except json.JSONDecodeError:
    print(text[:800])
    sys.exit(1)
if isinstance(entries, dict):
    entries = entries.get("entries") or entries.get("history") or []

opened = []
for e in entries:
    payload = e.get("payload") or e.get("data") or {}
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError:
            continue
    kind = e.get("event_type") or e.get("kind") or e.get("event") or payload.get("event")
    if kind and "escalation_opened" in str(kind):
        opened.append((e, payload))

print(f"window={WINDOW} entries={len(entries)} gate_escalation_opened={len(opened)}")

pools, sizes, liveness_by_name, askers = Counter(), Counter(), {}, Counter()
withheld_only = 0
for e, p in opened:
    inv = p.get("invited_peers") or []
    over = p.get("invitation_passed_over") or []
    wh = p.get("invitation_withheld") or []
    ev = p.get("invitation_evidence") or []
    asker = p.get("plugin_id") or e.get("plugin_id") or "?"
    askers[asker] += 1
    if not inv and wh:
        withheld_only += 1
    names = sorted(inv) or sorted(x.get("peer") for x in wh)
    if names:
        pools["|".join(names)] += 1
        sizes[len(inv) + len(over) + 1] += 1
    for row in list(ev) + list(over) + list(wh):
        if isinstance(row, dict) and row.get("peer"):
            liveness_by_name.setdefault(row["peer"], Counter())[str(row.get("liveness_at_invite"))] += 1

print(f"\naskers: {dict(askers)}")
print(f"opens whose invitation was WITHHELD (asker unproven): {withheld_only}")
print(f"\nregistry size implied at invite (|invited|+|passed_over|+1): {dict(sizes)}")
print("\ndistinct pools drawn:")
for pool, n in pools.most_common():
    print(f"  x{n:<4} {pool}")
print("\nliveness_at_invite, per name (the field that decides who survives the cap):")
for name, c in sorted(liveness_by_name.items()):
    print(f"  {name:<38} {dict(c)}")

live_seats = {"claude-code", "kimi-code", "codex"}
seen_live_seats = live_seats & set(liveness_by_name)
print(f"\nlive seats appearing in ANY pool/passed-over/withheld list: {sorted(seen_live_seats) or 'NONE'}")
print("A live seat absent from `invitation_passed_over` too was never IN the registry —")
print("the cap cannot explain it, because passed_over records exactly what the cap dropped.")
