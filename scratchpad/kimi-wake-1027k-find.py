#!/usr/bin/env python3
"""Wake 1027k: find the chain lifecycle of scope-f21489a368ff
(notice 29598, cbp-being -> kimi-code, queued 2026-10-21T05:48:53Z — the
long-standing i_owe row). Walks newest->oldest, prints any entry whose
payload names the id, stops provably older than the request.
"""
import json
import sys

sys.path.insert(0, "/home/dp/ai-workspace/hestia/tools")
from chain_walk import ChainWalker, payload

WANT = ("scope-f21489a368ff",)
STOP_EPOCH = 1792363200  # 2026-10-21T00:00:00Z — before notice 29598's request
MAX = 200_000


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
                "path", "path_as_asked", "grant_path", "modes", "once", "status",
                "reason", "granted", "expires_at", "revoked_by", "revoke_reason",
                "act", "rule", "origin", "invited_peers") if k in p}
            print(json.dumps({
                "pos": e.get("position"), "ts": e.get("timestamp"),
                "eventType": e.get("eventType"), "hash": (e.get("hash") or "")[:16],
                "hits": hits, "fields": keep}, indent=1))
        if ep is not None and ep < STOP_EPOCH:
            print(f"STOP: reached {e.get('timestamp')} after {scanned} entries "
                  f"(older than the request)", file=sys.stderr)
            return
    print(f"STOP: walk exhausted after {scanned} entries", file=sys.stderr)


if __name__ == "__main__":
    main()
