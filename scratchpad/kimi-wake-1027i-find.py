#!/usr/bin/env python3
"""Wake 1027i: find the chain lifecycle of two scope requests.

- scope-5f4ca2ff3f8f  (notice 33654, claude-code -> kimi-code, 2026-10-27 06:53Z)
- scope-05751db9f43f  (notice 29410, cbp-being  -> kimi-code, 2026-10-20 21:23Z)

Walks newest->oldest, prints any entry whose payload names either id, and stops
once it is provably older than 2026-10-20T00:00:00Z (both requests are newer).
"""
import json
import sys

sys.path.insert(0, "/home/dp/ai-workspace/hestia/tools")
from chain_walk import ChainWalker, payload

WANT = ("scope-05751db9f43f", "scope-5f4ca2ff3f8f", "scope-2d21b66120c4")
STOP_EPOCH = 1792353600  # 2026-10-20T21:20:00Z — just before notice 29410's request
MAX = 120_000


def epoch_of(e):
    ts = e.get("timestamp")
    if isinstance(ts, (int, float)):
        return float(ts)
    if isinstance(ts, str):
        try:
            from datetime import datetime
            return datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
        except ValueError:
            return None
    return None


def main():
    w = ChainWalker()
    scanned = 0
    for e in w.walk(max_entries=MAX):
        scanned += 1
        ep = epoch_of(e)
        blob = json.dumps(e)
        hits = [s for s in WANT if s in blob]
        if hits:
            p = payload(e)
            keep = {k: p.get(k) for k in (
                "request_id", "plugin_id", "decision", "decided_by", "decision_reason",
                "path", "grant_path", "modes", "once", "status", "reason", "granted",
                "expires_at", "revoked_by", "revoke_reason") if k in p}
            print(json.dumps({
                "pos": e.get("position"), "ts": e.get("timestamp"),
                "eventType": e.get("eventType"), "hash": (e.get("hash") or "")[:16],
                "hits": hits, "fields": keep}, indent=1))
        if ep is not None and ep < STOP_EPOCH:
            print(f"STOP: reached {e.get('timestamp')} after {scanned} entries "
                  f"(older than both requests)", file=sys.stderr)
            return
    print(f"STOP: walk exhausted after {scanned} entries", file=sys.stderr)


if __name__ == "__main__":
    main()
