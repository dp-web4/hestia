"""What the gate actually refused, read from the witness chain (hestia #1025's denominator).

WHY THIS EXISTS. #1025 argues gate 1a refuses honest work. That argument needs a rate, not
anecdotes, and I twice concluded the rate could not be measured — first because the JSONL
deny logs held only stale rows, then because `witness.db` is SQLCipher with no query surface.
Both conclusions were wrong in the same way: I inspected the artifacts I happened to know
about instead of asking what read surface the daemon offers. It offers `hestia_query_history`.

WHAT IT SHOWS, AND THE TWO HOLES IT REVEALS (both measured, 2026-09-14, Legion):

  1. The BEING's gate denies are recorded in full — decision, enforced, the exact `attempted`
     args and the `reason` string. Three of them in the window, all `search` refusals.
  2. The SEAT's `egress.secret` denies are NOT. Seventeen of them that day, every one from
     the claude-code PreToolUse shim, and the window that contains that seat's own
     gate-self-access records (41 of them) contains no decision entry for any of them. The
     substring `secret` does not appear anywhere in a 500-entry window.

So the FP class #1025 is about is precisely the class the chain cannot see. The refusals that
get recorded are the ones the being suffers; the ones a seat suffers vanish. That asymmetry
is why "false positives on thor recently" arrived as a report from a person rather than as a
number from the fleet.

  3. `hestia_query_history` returns at most 500 entries and sets `hasMore: true`, and the
     filter keys it honours (hash, limit, tool_name) do not include a cursor or a time
     bound. So the chain can be sampled but not walked: this meter measures a window of a
     few hours, not a history. Stated rather than worked around.

Usage:  python3 tools/gate_deny_meter.py [--limit 500] [--json]
"""
import argparse
import collections
import json
import urllib.request

ENDPOINT = "http://127.0.0.1:7711/mcp"
MAX_WINDOW = 500          # the daemon's cap, whatever we ask for — see hole 3 above


def _rpc(method, params, sid=None, mid=1, endpoint=ENDPOINT):
    body = json.dumps({"jsonrpc": "2.0", "id": mid, "method": method, "params": params}).encode()
    req = urllib.request.Request(endpoint, data=body, headers={
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream"})
    if sid:
        req.add_header("Mcp-Session-Id", sid)
    with urllib.request.urlopen(req, timeout=120) as r:
        return r.headers.get("Mcp-Session-Id"), r.read().decode()


def _payload(raw):
    """The daemon answers SSE; the tool result is JSON inside JSON inside a data: frame."""
    text = "".join(l[6:] for l in raw.splitlines() if l.startswith("data: ") and l[6:].strip())
    return json.loads(json.loads(text)["result"]["content"][0]["text"])


def fetch(limit=MAX_WINDOW, endpoint=ENDPOINT):
    """Recent chain entries. A handshake first: a bare tools/call answers HTTP 422."""
    sid, _ = _rpc("initialize", {"protocolVersion": "2025-06-18", "capabilities": {},
                                 "clientInfo": {"name": "gate-deny-meter", "version": "1"}},
                  endpoint=endpoint)
    _, raw = _rpc("tools/call", {"name": "hestia_query_history",
                                 "arguments": {"filter": {"limit": limit}}},
                  sid=sid, mid=2, endpoint=endpoint)
    return _payload(raw)


def classify(entries):
    """Split the window into the three things it can tell us apart."""
    denies, self_access, other = [], [], 0
    for e in entries:
        d = e.get("eventData", {}) or {}
        if "decision" in d:
            denies.append((e.get("chainPosition"), d))
        elif isinstance(d.get("data"), dict) and "marker" in d["data"]:
            self_access.append((e.get("chainPosition"), d["data"]))
        else:
            other += 1
    return denies, self_access, other


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=MAX_WINDOW)
    ap.add_argument("--endpoint", default=ENDPOINT)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    d = fetch(a.limit, a.endpoint)
    ents = d.get("entries", [])
    denies, self_access, other = classify(ents)

    if a.json:
        print(json.dumps({"window": len(ents), "hasMore": d.get("hasMore"),
                          "denies": [x[1] for x in denies],
                          "self_access": [x[1] for x in self_access]}, indent=2))
        return 0

    span = (ents[-1].get("chainPosition"), ents[0].get("chainPosition")) if ents else (0, 0)
    print(f"window: {len(ents)} entries, chain {span[0]}..{span[1]}, hasMore={d.get('hasMore')}")
    if d.get("hasMore"):
        print("  (the chain is longer than this. There is no cursor and no time filter,")
        print("   so this is a SAMPLE of recent events, never a history — see hole 3.)")

    print(f"\nGATE DECISIONS RECORDED: {len(denies)}")
    by_member = collections.Counter(x[1].get("plugin_id") for x in denies)
    by_rule = collections.Counter(str(x[1].get("reason") or "").split(":")[0] for x in denies)
    for m, n in by_member.most_common():
        print(f"  {n:4}  {m}")
    for r, n in by_rule.most_common():
        print(f"        rule {r}: {n}")
    for pos, x in denies:
        print(f"\n  pos={pos} {x.get('decision')} enforced={x.get('enforced')} "
              f"member={x.get('plugin_id')}")
        print(f"    attempted: {str(x.get('attempted'))[:140]}")
        print(f"    reason   : {str(x.get('reason'))[:200]}")

    print(f"\nGATE SELF-ACCESS EVENTS: {len(self_access)}")
    print("  severities:", dict(collections.Counter(x[1].get("severity") for x in self_access)))

    # THE HOLE, ASSERTED AS A CHECK so this file notices if it is ever closed.
    blob = json.dumps(ents)
    egress = [x for x in denies if "egress" in str(x[1].get("reason", "")).lower()]
    print(f"\negress.secret denies in this window: {len(egress)}")
    if not egress and "secret" not in blob:
        print("  NONE, and the word does not occur anywhere in the window. The seat-side")
        print("  PreToolUse refusals — the exact class #1025 is about — do not reach the")
        print("  chain, while the being's gate denies above do. That asymmetry is hole 2.")
    print(f"\nother entries (outcomes, scope rulings, escalations): {other}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
