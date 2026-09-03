#!/usr/bin/env python3
"""`hestia_member_unanswered.i_owe` counts undelivered bounces as inbound obligations.

THE CLAIM. When a watcher fails to fire a member, the notice is re-queued with an
`#undelivered:fire-rc=<rc>;why=<why>;via=watch-<member>` suffix appended to its pointer,
carrying the RECIPIENT as `from_plugin`. `hestia_member_unanswered` does not filter those
rows, so a notice *I* sent that never reached a peer comes back as something I OWE THAT
PEER AN ANSWER TO. The responsiveness metric charges a member for its peers' downtime.

THE DISCRIMINATOR, and it is not a heuristic. Every bounce marker names the watcher of the
member in `from_plugin` -- `via=watch-kimi-code` on a row whose `from_plugin` is
`kimi-code`. A genuine reply from kimi cannot be stamped "kimi's watcher failed to fire";
that stamp records a delivery attempt TOWARD kimi. So the test is the identity

    via-watcher == from_plugin

and on the measured corpus it held 150 out of 150, while `via=watch-claude-code` -- the
shape a genuine inbound delivery failure would have -- appeared ZERO times. The bounces
are outbound, all of them.

MEASURED on claude-code, 2026-08-31 (i_owe spanning 2026-08-25..2026-08-29):

    from_plugin   bounced  genuine  total
    codex              86        0     86
    kimi-code          64       41    105
    TOTAL             150       41    191     -> 78.5% of i_owe is a watcher bounce

Every one of the 86 obligations attributed to codex is a bounce; the seat has no genuine
unanswered codex mail at all. That is consistent with codex's wake mortality rather than
with codex having asked 86 unanswered questions.

WHY IT MATTERS BEYOND THE COUNT. The wake primer ALREADY detects this class -- it prints
`!! NOT-AN-ANSWER ... YOUR OWN notice echoed back by the watcher ... nothing is discharged
by it` for exactly these rows. So two surfaces read one store and disagree, and the one
that disagrees is the one that looks like a responsiveness ledger. A member reading
`i_owe` sees a backlog it cannot discharge: there is no author on the other end of a
bounce to answer.

This is a READ-ONLY probe. It does not send, ack, or mutate anything.

Usage:  python3 tools/i_owe_counts_watcher_bounces.py [--json]
Exit:   0 measured, 1 could not measure (daemon unreachable or unattributed).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.error
import urllib.request
from collections import Counter

URL = "http://127.0.0.1:7711/mcp"
PLUGIN = "claude-code"
ROLE = "role:constellation:interactive-dev"

BOUNCE = re.compile(r"#undelivered:fire-rc=(\d+);why=([^;]+);via=watch-([\w-]+)")

_next_id = [0]


def _rpc(method, params=None, sid=None):
    """One JSON-RPC call. The daemon answers SSE, and opens with a bare `data:` keepalive
    before the real frame -- parsing the first `data:` line unconditionally fails here."""
    _next_id[0] += 1
    body = {"jsonrpc": "2.0", "id": _next_id[0], "method": method}
    if params is not None:
        body["params"] = params
    req = urllib.request.Request(
        URL, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "Accept": "application/json, text/event-stream"})
    if sid:
        req.add_header("Mcp-Session-Id", sid)
    with urllib.request.urlopen(req, timeout=30) as resp:
        raw = resp.read().decode()
        hdr_sid = resp.headers.get("Mcp-Session-Id")
    for line in raw.splitlines():
        if line.startswith("data:") and line[5:].strip():
            return json.loads(line[5:]), hdr_sid
    return ({} if not raw.strip() else json.loads(raw)), hdr_sid


def _call(tool, args, sid):
    res, _ = _rpc("tools/call", {"name": tool, "arguments": args}, sid=sid)
    for chunk in res.get("result", {}).get("content", []):
        if chunk.get("type") == "text":
            try:
                return json.loads(chunk["text"])
            except json.JSONDecodeError:
                return {"_text": chunk["text"]}
    return res.get("result", res)


def classify(rows):
    """Split rows into (bounced, genuine) on the via-watcher == from_plugin identity."""
    bounced, genuine, foreign = [], [], []
    for row in rows:
        m = BOUNCE.search(row.get("pointer_uri") or "")
        if not m:
            genuine.append(row)
        elif m.group(3) == row.get("from_plugin"):
            bounced.append(row)
        else:
            # A marker naming somebody else's watcher would NOT be an outbound bounce.
            # None were observed; if one appears it deserves its own reading, not this one.
            foreign.append(row)
    return bounced, genuine, foreign


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", action="store_true", help="emit the fold as JSON")
    args = ap.parse_args()

    try:
        _, sid = _rpc("initialize", {
            "protocolVersion": "2024-11-05", "capabilities": {},
            "clientInfo": {"name": "i-owe-bounce-probe", "version": "1"}})
        _rpc("notifications/initialized", {}, sid=sid)
        conn = _call("hestia_connect",
                     {"plugin_id": PLUGIN, "role": ROLE, "host_agent": PLUGIN}, sid)
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        print(f"could not measure: daemon unreachable ({exc})", file=sys.stderr)
        return 1

    session = conn.get("sessionId") or conn.get("session_id")
    if not session:
        print(f"could not measure: no session from hestia_connect ({conn})", file=sys.stderr)
        return 1

    fold = _call("hestia_member_unanswered",
                 {"plugin_id": PLUGIN, "session_id": session}, sid)
    rows = fold.get("i_owe")
    if rows is None:
        print(f"could not measure: {fold}", file=sys.stderr)
        return 1

    bounced, genuine, foreign = classify(rows)
    per = {}
    for label, group in (("bounced", bounced), ("genuine", genuine)):
        for row in group:
            per.setdefault(row["from_plugin"], Counter())[label] += 1

    if args.json:
        print(json.dumps({
            "total": len(rows), "bounced": len(bounced), "genuine": len(genuine),
            "foreign_marker": len(foreign),
            "by_peer": {k: dict(v) for k, v in per.items()},
            "why": dict(Counter(BOUNCE.search(r["pointer_uri"]).group(2) for r in bounced)),
        }, indent=2))
        return 0

    print(f"{'from_plugin':<14}{'bounced':>9}{'genuine':>9}{'total':>7}")
    for peer in sorted(per):
        b, g = per[peer]["bounced"], per[peer]["genuine"]
        print(f"{peer:<14}{b:>9}{g:>9}{b + g:>7}")
    tb, tg = len(bounced), len(genuine)
    total = tb + tg + len(foreign)
    pct = (100.0 * tb / total) if total else 0.0
    print(f"{'TOTAL':<14}{tb:>9}{tg:>9}{total:>7}")
    print()
    print(f"{pct:.1f}% of i_owe is a watcher bounce -- a notice this seat SENT that never "
          f"reached the peer,\nre-queued under the peer's name and counted back as an "
          f"obligation on the sender.")
    if foreign:
        print(f"NOTE: {len(foreign)} row(s) carry a marker naming a watcher other than "
              f"from_plugin. That is not\nthe outbound-bounce shape and is not counted as "
              f"one; read them individually.")
    print(f"bounce reasons: {dict(Counter(BOUNCE.search(r['pointer_uri']).group(2) for r in bounced))}")
    print(f"via=watch-{PLUGIN} (the shape a genuine inbound delivery failure would have): "
          f"{sum(1 for r in rows if f'via=watch-{PLUGIN}' in (r.get('pointer_uri') or ''))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
