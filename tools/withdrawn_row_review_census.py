#!/usr/bin/env python3
"""Does a self-withdrawal cancel the invitations it issued? -- reviews that land on withdrawn rows.

WHY THIS EXISTS. #645 measures peer factors against the RULING and finds 79% arrive after
it. Its two "withdrawn bucket" instances (d3f643cf 08-28, 24cc622f 09-01) each cost a
reviewer wake on a row the asker had already retired, and the first of them concluded that
a withdrawal "has to land inside ~2 min of the open to save anything". Instance 3
(674656460142f2e4, 2026-09-04) was withdrawn 14.5 s after open and still drew a 135k-token
review twelve hours later, whose factor the daemon then REFUSED as `unknown id` because the
row had been reaped (#544). So the question is not the asker's speed. It is whether the
invitation has any terminal at all once the row it points at is gone.

WHAT THE CHAIN CAN SAY. The invitation is NOT a separately witnessed notice: a
`review_request` invite's `chain_hash` resolves to the `gate_escalation_opened` row itself
(verified 2026-09-05 with `ChainWalker.entry_by_hash`). So invites are counted by their
open row, and the only mesh traffic that names an escalation is what peers SEND BACK --
bounce replies (`#undelivered:`), `review_done`, `ack` -- all of which carry the id in
`pointer_uri`. This joins the two by the 16-hex id.

HORIZON. A withdrawn row is reap-ELIGIBLE at `opened_at + ttl_secs + 600 + 3600`
(`decided_horizon` capped at `expires_at + APPROVAL_CLAIM_WINDOW_SECS`, then
`REAP_KEEP_SECS`; core/src/server/gate_escalation.rs). `reap` runs on the next open, not on
a clock, so "past horizon" here means the factor door MAY be shut, not that it is; the one
probe in hand (codex on 674656460142f2e4, +12.1 h) found it shut. A review_done inside the
horizon is one whose factor could still land; outside it, the review's only record is the
mesh pointer string.

USAGE. python3 tools/withdrawn_row_review_census.py [--since ISO] [--max N] [--list]
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import statistics
import sys
from collections import Counter, defaultdict

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from chain_walk import ChainWalker, payload  # noqa: E402

HEX = re.compile(r"(?<![0-9a-f])[0-9a-f]{16}(?![0-9a-f])")
CLAIM_WINDOW_SECS = 600
REAP_KEEP_SECS = 3600
DEFAULT_TTL = 3600


def _t(ts: str) -> dt.datetime:
    # nanosecond timestamps; fromisoformat takes at most 6 fractional digits
    return dt.datetime.fromisoformat(re.sub(r"(\.\d{6})\d+", r"\1", ts))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--since", default=(dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=48)).strftime("%Y-%m-%dT%H:%M"))
    ap.add_argument("--max", type=int, default=60000)
    ap.add_argument("--list", action="store_true", help="print every late review_done row")
    ap.add_argument("--endpoint", default=None)
    a = ap.parse_args()

    w = ChainWalker(endpoint=a.endpoint) if a.endpoint else ChainWalker()
    rows: dict[str, list] = defaultdict(list)
    ttl: dict[str, int] = {}
    scanned = 0
    for e in w.walk(max_entries=a.max):
        scanned += 1
        ts = e.get("timestamp", "")
        if ts and ts < a.since:
            break
        et = e.get("eventType", "")
        p = payload(e) or {}
        if et.startswith("gate_escalation"):
            eid = p.get("escalation_id")
            if eid:
                rows[eid].append((ts, et, p.get("decided_via") or p.get("corroborated_by") or p.get("plugin_id"), ""))
                if et == "gate_escalation_opened":
                    ttl[eid] = int(p.get("ttl_secs") or DEFAULT_TTL)
        elif et == "member_notice":
            pu = p.get("pointer_uri") or ""
            m = HEX.search(pu)
            if m and "escalation/" in pu:
                rows[m.group(0)].append((ts, "mn:" + str(p.get("kind")), f"{p.get('from_plugin_id')}->{p.get('to_plugin_id')}", pu))

    def first(v, et):
        x = [r[0] for r in v if r[1] == et]
        return min(x) if x else None

    opened = {k for k, v in rows.items() if first(v, "gate_escalation_opened")}
    withdrawn = {k for k, v in rows.items() if first(v, "gate_escalation_withdrawn")}
    out: dict = {"scanned": scanned, "since": a.since, "opened": len(opened), "withdrawn": len(withdrawn)}

    lags = []
    for k in withdrawn:
        o, wd = first(rows[k], "gate_escalation_opened"), first(rows[k], "gate_escalation_withdrawn")
        if o and wd:
            lags.append((_t(wd) - _t(o)).total_seconds())
    if lags:
        out["open_to_withdraw_s"] = {"n": len(lags), "median": round(statistics.median(lags), 1),
                                    "share_le_120s": round(sum(1 for x in lags if x <= 120) / len(lags), 3)}

    rd, late, within, factors_after = [], [], [], 0
    for k in withdrawn:
        v = rows[k]
        o, wd = first(v, "gate_escalation_opened"), first(v, "gate_escalation_withdrawn")
        horizon = (_t(o) + dt.timedelta(seconds=ttl.get(k, DEFAULT_TTL) + CLAIM_WINDOW_SECS + REAP_KEEP_SECS)) if o else None
        for r in v:
            if r[1] == "mn:review_done":
                rd.append((k, r))
                if horizon and _t(r[0]) > horizon:
                    late.append((k, round((_t(r[0]) - _t(wd)).total_seconds() / 3600, 1), r[2]))
                else:
                    within.append((k, r[2]))
            if r[1] == "gate_escalation_corroborated" and wd and r[0] > wd:
                factors_after += 1
    out["withdrawn_with_any_mesh_traffic"] = sum(1 for k in withdrawn if any(r[1].startswith("mn:") for r in rows[k]))
    out["withdrawn_with_bounce_reply"] = sum(1 for k in withdrawn if any("#undelivered:" in r[3] for r in rows[k]))
    out["review_done_on_withdrawn"] = {"rows": len(rd), "escalations": len({k for k, _ in rd})}
    out["review_done_inside_reap_horizon"] = {"rows": len(within), "by_pair": Counter(p for _, p in within)}
    out["review_done_past_reap_horizon"] = {"rows": len(late), "escalations": len({k for k, _, _ in late}),
                                            "by_pair": Counter(p for _, _, p in late)}
    out["factors_landed_after_withdrawal"] = factors_after
    out["caveat"] = "past-horizon = reap-ELIGIBLE (reap runs on the next open, not a clock); the door state is known only where probed"
    print(json.dumps(out, indent=1, default=lambda c: dict(c)))
    if a.list:
        for k, h, p in sorted(late, key=lambda x: -x[1]):
            print(f"late  {k}  +{h}h after withdrawal  {p}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
