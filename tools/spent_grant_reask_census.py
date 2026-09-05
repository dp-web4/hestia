#!/usr/bin/env python3
"""Re-ask chains rooted at a SPENT grant — the arm #602's census excludes.

#602 measures never-claimed grants and asks whether the member re-filed. That filter
drops the population where the same unit mismatch costs more: grants that WERE claimed.
Measured 2026-09-05 over 2026-08-18 23:25Z -> 2026-09-05 19:20Z (80,000 chain hops,
460 escalations with an `opened` row):

    claimed (grant spent)        131
    approved, never claimed      221   <- #602's population
    withdrawn                     85

Session-scoped re-ask within 600s: spent 17.6% vs unspent 9.0%. Matched on
(plugin, marker) as #602 does: 38.2% vs 16.3%. Spending the grant roughly doubles the
chance the member asks again, at every window, under both scopings.

The qualitative split matters more than the rate. The unspent arm's re-ask carries a
DIFFERENT act_digest every time (0 identical at 60/300/600s, both scopings) — that is
the unit mismatch #602 names. The spent arm carries 12 IDENTICAL-digest re-asks within
600s: the member re-issuing byte-identical bytes after a grant for them was approved and
consumed, and the operator approving again. Verified not to be #774 (claim consumed /
write never happened): `--specimens` joins each claim instant to `outcome` rows in the
same session and finds the first write landed. It is an edit-test-resplice loop.

CAVEATS, all load-bearing:
  * (plugin, marker) is coarse. One marker is 172 of 460 rows and one plugin is 318 of
    460, so co-seat traffic inflates the unscoped arm. Prefer --scope session.
  * 233 of 460 `opened` rows carry a null host_session_id, so the session-scoped arm
    drops real same-session pairs. It is a FLOOR, not an estimate.
  * 87 of 460 rows carry a null act_digest. Those are excluded from the
    identical/differs split rather than counted as "differs".
  * `success: true` on an `outcome` row is the shell wrapper's exit code, not the
    operation's. Bind it to the target text before believing it.
  * `gate_escalation_claimed` records that the GRANT was consumed, never that the WRITE
    landed. That join has to be done by hand against `outcome` target text, which only
    works while the target survives the 220-char preview truncation. #602 criterion (d)
    is the ledger that would make it unnecessary.

Usage:
    python3 tools/spent_grant_reask_census.py [--max 80000] [--scope session|marker]
    python3 tools/spent_grant_reask_census.py --specimens
"""
from __future__ import annotations

import argparse
import datetime
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chain_walk import ChainWalker, payload  # noqa: E402

ESC_TYPES = (
    "gate_escalation_opened",
    "gate_escalation_decided",
    "gate_escalation_claimed",
    "gate_escalation_withdrawn",
    "gate_escalation_expired",
)
WINDOWS = (60, 300, 600, 1800, 3600)


def ts(s: str) -> float:
    return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).timestamp()


def collect(max_entries: int, cache: str):
    """Chain rows for every escalation event. Cached: a walk is ~1ms/hop."""
    if cache and os.path.exists(cache):
        return json.load(open(cache))
    walker = ChainWalker()
    rows, n = [], 0
    for entry in walker.walk(max_entries=max_entries):
        n += 1
        if entry.get("eventType") not in ESC_TYPES:
            continue
        p = payload(entry)
        rows.append({
            "t": entry.get("timestamp"),
            "type": entry.get("eventType"),
            "esc": p.get("escalation_id"),
            "plugin": p.get("plugin_id"),
            "marker": p.get("marker"),
            "digest": p.get("act_digest"),
            "session": p.get("host_session_id"),
            "status": p.get("status"),
            "opened_via": p.get("opened_via"),
            "reason": (p.get("reason") or "")[:300],
            "stated": (p.get("stated_reason") or "")[:200],
        })
    print(f"walked {n} entries, kept {len(rows)} escalation rows", file=sys.stderr)
    if cache:
        json.dump(rows, open(cache, "w"))
    return rows


def index(rows):
    """escalation_id -> {opened, decided, claimed, withdrawn, expired}, earliest of each."""
    esc = {}
    for r in rows:
        e = r["esc"]
        if not e:
            continue
        d = esc.setdefault(e, {})
        k = r["type"].rsplit("_", 1)[1]
        if k not in d or ts(r["t"]) < ts(d[k]["t"]):
            d[k] = r
    return esc


def populations(esc):
    opened = sorted((ts(v["opened"]["t"]), e, v) for e, v in esc.items() if "opened" in v)
    claimed = [x for x in opened if "claimed" in x[2]]
    unclaimed = [x for x in opened
                 if "decided" in x[2]
                 and x[2]["decided"].get("status") == "approved"
                 and "claimed" not in x[2]]
    withdrawn = [x for x in opened if "withdrawn" in x[2]]
    return opened, claimed, unclaimed, withdrawn


def later_asks(opened, esc_id, o, after, window, scope):
    """Escalations opened by the same member at the same marker inside `window`."""
    out = []
    for t2, e2, v2 in opened:
        if e2 == esc_id or t2 <= after or t2 - after > window:
            continue
        o2 = v2["opened"]
        if o2.get("plugin") != o.get("plugin") or o2.get("marker") != o.get("marker"):
            continue
        if scope == "session" and (not o.get("session") or o2.get("session") != o.get("session")):
            continue
        out.append(v2)
    return out


def table(opened, pop, label, anchor, scope):
    print(f"\n### {label}  (n={len(pop)}, scope={scope})")
    print("| window | re-asked | re-ask % | digest differs | digest identical |")
    print("|---|---|---|---|---|")
    for w in WINDOWS:
        hit = same = diff = 0
        for _t, e, v in pop:
            cand = later_asks(opened, e, v["opened"], anchor(v), w, scope)
            if not cand:
                continue
            hit += 1
            d1 = v["opened"].get("digest")
            for v2 in cand:
                d2 = v2["opened"].get("digest")
                if d1 and d2 and d1 == d2:
                    same += 1
                else:
                    diff += 1
        pct = f"{100.0 * hit / len(pop):.1f}%" if pop else "-"
        print(f"| {w}s | {hit} | {pct} | {diff} | {same} |")


def specimens(opened, claimed, max_entries):
    """Identical-digest pairs, joined to outcome rows to test whether write 1 landed."""
    specs = []
    for _t, e, v in claimed:
        after, o = ts(v["claimed"]["t"]), v["opened"]
        if not o.get("session") or not o.get("digest"):
            continue
        for v2 in later_asks(opened, e, o, after, 600, "session"):
            if v2["opened"].get("digest") == o.get("digest"):
                specs.append({"e1": e, "e2": v2["opened"]["esc"], "claim_t": after,
                              "open2_t": ts(v2["opened"]["t"]), "sess": o["session"],
                              "act": o.get("stated") or ""})
    print(f"identical-digest pairs after a spent grant, <=600s, session-scoped: {len(specs)}")
    if not specs:
        return
    lo = min(s["claim_t"] for s in specs) - 300
    hi = max(s["open2_t"] for s in specs) + 300
    walker, outs = ChainWalker(), []
    for entry in walker.walk(max_entries=max_entries):
        if entry.get("eventType") != "outcome":
            continue
        t = ts(entry["timestamp"])
        if not lo <= t <= hi:
            continue
        p = payload(entry)
        outs.append({"t": entry["timestamp"], "ts": t, "sess": p.get("host_session_id"),
                     "tool": p.get("tool_name"), "success": p.get("success"),
                     "target": (p.get("target") or "")[:220]})
    for s in specs:
        win = [o for o in outs if o["sess"] == s["sess"]
               and s["claim_t"] - 2 <= o["ts"] <= s["open2_t"]]
        probe = s["act"].split(": ", 1)[-1][:50]
        hits = [o for o in win if probe and probe in o["target"]]
        print(f"\n{s['e1'][:12]} -> {s['e2'][:12]}  gap={s['open2_t']-s['claim_t']:.0f}s  "
              f"outcomes between={len(win)} act-matching={len(hits)}")
        for o in hits[:2]:
            print(f"   {o['t'][11:19]} {o['tool']} success={o['success']} :: {o['target'][:110]}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--max", type=int, default=80000, help="chain hops to walk")
    ap.add_argument("--scope", choices=("session", "marker", "both"), default="both")
    ap.add_argument("--cache", default="/tmp/esc_rows_cache.json", help="'' to disable")
    ap.add_argument("--specimens", action="store_true",
                    help="join identical-digest pairs to outcome rows (second walk)")
    a = ap.parse_args()

    rows = collect(a.max, a.cache)
    esc = index(rows)
    opened, claimed, unclaimed, withdrawn = populations(esc)
    print(f"escalations with an opened row: {len(opened)}")
    if opened:
        first = datetime.datetime.fromtimestamp(opened[0][0], datetime.timezone.utc)
        last = datetime.datetime.fromtimestamp(opened[-1][0], datetime.timezone.utc)
        print(f"window: {first:%Y-%m-%d %H:%M}Z -> {last:%Y-%m-%d %H:%M}Z")
    print(f"  claimed (grant spent):     {len(claimed)}")
    print(f"  approved, never claimed:   {len(unclaimed)}  <- #602's population")
    print(f"  withdrawn:                 {len(withdrawn)}")

    if a.specimens:
        specimens(opened, claimed, a.max)
        return 0

    scopes = ("session", "marker") if a.scope == "both" else (a.scope,)
    for scope in scopes:
        table(opened, claimed, "re-ask after a SPENT grant",
              lambda v: ts(v["claimed"]["t"]), scope)
        table(opened, unclaimed, "re-ask after an UNSPENT approval (#602 arm)",
              lambda v: ts(v["decided"]["t"]), scope)
        table(opened, withdrawn, "re-ask after a WITHDRAWAL",
              lambda v: ts(v["withdrawn"]["t"]), scope)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
