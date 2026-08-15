#!/usr/bin/env python3
"""Read-only census of resident member sessions (#320 cost model, per machine).

Why this exists: #320's second-machine measurement (Thor, 2026-08-11) found 161
resident sessions with `host_session_id: null` on **every one**. The reuse scan
sits behind `if let Some(hsid) = host_session_id.as_deref()`, so on Thor no
connect ever enters the O(n) scan — which corrected the issue's own cost model
from "lock time" to "RAM + a coordination surface that is wrong by ~80x", and
reordered the fix toward a shared liveness predicate/TTL over an index.

That correction is machine-scoped. dp flagged it in the same comment: *"Whether
the hook sends one on other seats is worth checking — the null-only population
may itself be the bug."* Nobody has taken the reading on CBP. This script takes
it, because #423 currently names #320's scan half as its leading root cause and
that claim has no payer unless some population on this machine carries a
`host_session_id`.

Method (identical to the Thor reading, so the two are comparable): `initialize`
+ `resources/read` on `hestia://session/siblings`. Mints no session, writes
nothing, and — unlike a probe that connects — does not perturb the population it
is counting.

Usage: python3 tools/session_residency_census.py [--json]
"""
import json
import os
import sys
import urllib.request
from collections import Counter
from pathlib import Path

ENDPOINT_FILE = Path.home() / ".hestia" / "endpoint"
PROTOCOL_VERSION = "2025-06-18"


def endpoint() -> str:
    env = os.environ.get("HESTIA_MCP_ENDPOINT")
    if env:
        return env
    if ENDPOINT_FILE.exists():
        return ENDPOINT_FILE.read_text().strip()
    return "http://127.0.0.1:7711/mcp"


class Client:
    def __init__(self, url: str, timeout: float = 15.0):
        self.url = url
        self.timeout = timeout
        self.session = None
        self._id = 0

    def post(self, method: str, params=None, notify: bool = False):
        self._id += 1
        body = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            body["params"] = params
        if not notify:
            body["id"] = self._id
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        req = urllib.request.Request(
            self.url, data=json.dumps(body).encode(), headers=headers, method="POST"
        )
        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            sid = resp.headers.get("Mcp-Session-Id")
            if sid:
                self.session = sid
            raw = resp.read().decode()
        if not raw.strip():
            return {}
        if raw.lstrip().startswith("event:") or "\ndata:" in raw or raw.startswith("data:"):
            payloads = [ln[5:].strip() for ln in raw.splitlines() if ln.startswith("data:")]
            raw = payloads[-1] if payloads else "{}"
        return json.loads(raw)


def read_siblings(c):
    # accepts this module's Client or the latency probe's (which spells it _post)
    post = getattr(c, "post", None) or c._post
    resp = post("resources/read", {"uri": "hestia://session/siblings"})
    if "result" not in resp:
        raise SystemExit(f"resources/read failed: {json.dumps(resp)[:600]}")
    contents = resp["result"].get("contents") or []
    if not contents:
        raise SystemExit("resources/read returned no contents")
    text = contents[0].get("text", "")
    return json.loads(text)


def sessions_of(doc):
    """The resource shape has moved before; accept the plausible spellings and
    say which one answered rather than silently reading an empty list."""
    if isinstance(doc, list):
        return doc, "toplevel-list"
    for key in ("sessions", "siblings", "members", "live_sessions"):
        v = doc.get(key)
        if isinstance(v, list):
            return v, key
    raise SystemExit(
        f"no session list found; top-level keys were {sorted(doc)!r}"
    )


def main() -> int:
    as_json = "--json" in sys.argv
    c = Client(endpoint())
    init = c.post("initialize", {
        "protocolVersion": PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": {"name": "session-residency-census", "version": "0"},
    })
    if "result" not in init:
        raise SystemExit(f"initialize failed: {json.dumps(init)[:600]}")
    c.post("notifications/initialized", {}, notify=True)

    doc = read_siblings(c)
    sessions, list_key = sessions_of(doc)

    hsid = Counter(
        "present" if s.get("host_session_id") else "null" for s in sessions
    )
    agents = Counter(s.get("host_agent") or "<none>" for s in sessions)
    roles = Counter(s.get("role") or "<none>" for s in sessions)
    stamps = sorted(s.get("connected_at") for s in sessions if s.get("connected_at"))
    # the population that would actually pay the O(n) reuse scan
    scanners = [s for s in sessions if s.get("host_session_id")]
    scanner_agents = Counter(s.get("host_agent") or "<none>" for s in scanners)

    out = {
        "endpoint": c.url,
        "list_key": list_key,
        "resident_sessions": len(sessions),
        "host_session_id": dict(hsid),
        "by_host_agent": dict(agents.most_common()),
        "by_role": dict(roles.most_common()),
        "oldest": stamps[0] if stamps else None,
        "newest": stamps[-1] if stamps else None,
        "scan_entrants": len(scanners),
        "scan_entrants_by_host_agent": dict(scanner_agents.most_common()),
    }
    if as_json:
        print(json.dumps(out, indent=2))
        return 0

    print(f"endpoint            : {out['endpoint']}  (list key {list_key!r})")
    print(f"RESIDENT SESSIONS   : {out['resident_sessions']}")
    print(f"host_session_id     : {out['host_session_id']}")
    print(f"by host_agent       : {out['by_host_agent']}")
    print(f"by role             : {out['by_role']}")
    print(f"oldest / newest     : {out['oldest']} .. {out['newest']}")
    print()
    print(f"SCAN ENTRANTS       : {out['scan_entrants']}  "
          f"(connects carrying a host_session_id — the only ones that enter the")
    print( "                      O(n) reuse scan; if 0, an index on this machine")
    print( "                      optimizes a scan nothing runs)")
    print(f"  by host_agent     : {out['scan_entrants_by_host_agent']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
