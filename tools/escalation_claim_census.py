#!/usr/bin/env python3
"""Did the governance grant get spent, and if not, what did the member do instead?

Answers three questions off one chain walk, and prints the tables published to
#668 (closure verification) and #602 (the unit mismatch, quantified):

  1. CLAIM RATE, per escalation and per act -- the #668 metrics, so a closed issue's
     fix can be re-checked on a later window instead of assumed.
  2. ID INFLATION -- escalations minted per distinct act, and the gap distribution
     between re-opens of an IDENTICAL act. #668's signature for "one member action
     trips the gate several times" is a sub-second median here.
  3. THE UNCLAIMED SPLIT -- for each approved-but-never-claimed grant, did the same
     plugin reopen at the same marker soon after, and did the act CHANGE?

        RE-FILED (digest differs) -> the member was still working the target; the
            grant could not follow the act, because a claim binds the act TEXT.
            This is #602: the operator decides per-fix, the mechanism asks per-hunk.
        RE-FILED (digest identical) -> #601, the flap case.
        ABANDONED -> nothing followed. Consistent with a discovery gap.

WHY THE SPLIT IS NOT A PROOF. "Re-filed" is same-plugin + same-marker + inside a
window. It is a PROXY FOR INTENT. `plugins/*/hooks` is a coarse marker and some
reopens under it are unrelated work, so the sweep prints the whole window curve
rather than one number -- the share runs 10% at 60s to 47% at 3600s, and picking a
single window is a choice the reader should make knowingly.

TWO PAYLOAD TRAPS, recorded so the next reader does not pay for them:
  * `gate_escalation_decided` has NO `granted` key. The field is `status: "approved"`.
    A reader keyed on `granted` gets 0 approvals out of a healthy chain.
  * Per #700/#658 neither `opened` nor `decided` carries a timestamp of its own. The
    CHAIN ENTRY's timestamp is the witnessed one; use it. (`claimed` does carry
    `decided_at` plus `secs_from_decision_to_use`, which is why claim lag is exact.)

Usage:  MAX_ENTRIES=40000 python3 tools/escalation_claim_census.py
"""
import sys, os, collections
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chain_walk import ChainWalker, payload
from datetime import datetime

WINDOWS = (60, 120, 300, 600, 1800, 3600)
MAX_ENTRIES = int(os.getenv("MAX_ENTRIES") or "40000")


def _epoch(ts):
    try:
        return datetime.fromisoformat(ts).timestamp()
    except (TypeError, ValueError):
        return None


def collect(max_entries):
    w = ChainWalker()
    opened, decided, claimed, withdrawn, claim_lag = {}, {}, set(), set(), []
    walked = 0
    for e in w.walk(max_entries=max_entries):
        walked += 1
        t = e.get("eventType") or ""
        if not t.startswith("gate_escalation_"):
            continue
        p = payload(e)
        eid = p.get("escalation_id")
        if not eid:
            continue
        at = _epoch(e.get("timestamp"))
        if t == "gate_escalation_opened":
            opened[eid] = {"at": at, "plugin": p.get("plugin_id"),
                           "marker": p.get("marker"), "digest": p.get("act_digest")}
        elif t == "gate_escalation_decided":
            decided[eid] = {"at": at, "ok": p.get("status") == "approved"}
        elif t == "gate_escalation_withdrawn":
            withdrawn.add(eid)
        elif t == "gate_escalation_claimed":
            claimed.add(eid)
            claim_lag.append(p.get("secs_from_decision_to_use"))
    return walked, opened, decided, claimed, withdrawn, claim_lag


def main():
    walked, opened, decided, claimed, withdrawn, claim_lag = collect(MAX_ENTRIES)
    ts = [o["at"] for o in opened.values() if o["at"]]
    if not ts:
        print("no escalations in this window")
        return
    print(f"chain entries walked : {walked}")
    print(f"window               : {datetime.fromtimestamp(min(ts)):%Y-%m-%d %H:%M} "
          f".. {datetime.fromtimestamp(max(ts)):%Y-%m-%d %H:%M}")
    approved = [k for k, v in decided.items() if v["ok"]]
    unclaimed = [k for k in approved if k not in claimed]
    print(f"escalations opened   : {len(opened)}")
    print(f"  withdrawn          : {len(withdrawn)}")
    print(f"  decided            : {len(decided)}  "
          f"(approved {len(approved)}, denied {len(decided)-len(approved)})")
    print(f"  approved + claimed : {len(approved)-len(unclaimed)}")
    print(f"  approved UNCLAIMED : {len(unclaimed)}  "
          f"({100.0*len(unclaimed)/max(1,len(approved)):.1f}%)")

    # --- #668 metrics -------------------------------------------------------
    hasd = {k: v for k, v in opened.items() if v["digest"]}
    acts = collections.defaultdict(list)
    for k, v in hasd.items():
        acts[v["digest"]].append(k)
    appr_acts = {d for d, ids in acts.items() if any(k in approved for k in ids)}
    clm_acts = {d for d, ids in acts.items() if any(k in claimed for k in ids)}
    print()
    print("#668 metrics (its window 2026-08-18..08-27 in parentheses)")
    print(f"  act_digest coverage: {100.0*len(hasd)/max(1,len(opened)):.0f}%   (~50%, vintage cutover)")
    print(f"  distinct acts      : {len(acts)}   INFLATION {len(hasd)/max(1,len(acts)):.2f}x   (1.50x)")
    print(f"  PER-ACT claim rate : {100.0*len(clm_acts)/max(1,len(appr_acts)):.1f}%   (11.4%)")
    print(f"  PER-ESC claim rate : {100.0*len([k for k in approved if k in claimed])/max(1,len(approved)):.1f}%   (20.9-23.3%)")
    gaps = []
    for d, ids in acts.items():
        if len(ids) < 2:
            continue
        tt = sorted(o for o in (opened[i]["at"] for i in ids) if o)
        gaps += [round(b - a) for a, b in zip(tt, tt[1:])]
    if gaps:
        gaps.sort()
        print(f"  identical-act re-open gap: n={len(gaps)} min {gaps[0]}s "
              f"median {gaps[len(gaps)//2]}s max {gaps[-1]}s   (median 1s == the storm signature)")
    lags = sorted(x for x in claim_lag if isinstance(x, (int, float)))
    if lags:
        print(f"  claim lag decision->use  : n={len(lags)} min {lags[0]}s "
              f"median {lags[len(lags)//2]}s max {lags[-1]}s")

    # --- the unclaimed split, swept over the window ------------------------
    by_key = collections.defaultdict(list)
    for eid, o in opened.items():
        if o["at"] is not None:
            by_key[(o["plugin"], o["marker"])].append((o["at"], eid))
    for v in by_key.values():
        v.sort()

    print()
    print("unclaimed grants: did the member come back to the same target?")
    print(f"  {'window':>8} {'re-filed':>9} {'abandoned':>10} {'re-filed%':>10} "
          f"{'digest differs':>15} {'identical':>10}")
    per_window = {}
    for W in WINDOWS:
        r = a = diff = same = 0
        refiled_ids = []
        for eid in unclaimed:
            o = opened.get(eid)
            t0 = (decided.get(eid) or {}).get("at") or (o or {}).get("at")
            if not o or t0 is None:
                continue
            later = [x for x in by_key[(o["plugin"], o["marker"])]
                     if x[1] != eid and t0 <= x[0] <= t0 + W]
            if later:
                r += 1
                refiled_ids.append((eid, o, len(later)))
                for _, e2 in later:
                    if opened[e2]["digest"] == o["digest"]:
                        same += 1
                    else:
                        diff += 1
            else:
                a += 1
        per_window[W] = refiled_ids
        print(f"  {W:>8} {r:>9} {a:>10} {100.0*r/max(1,r+a):>9.1f}% {diff:>15} {same:>10}")

    print()
    print("per plugin (approved / unclaimed / re-filed at 1800s):")
    agg = collections.defaultdict(lambda: [0, 0, 0])
    for eid in approved:
        pl = (opened.get(eid) or {}).get("plugin")
        agg[pl][0] += 1
        if eid not in claimed:
            agg[pl][1] += 1
    for eid, o, _ in per_window.get(1800, []):
        agg[o.get("plugin")][2] += 1
    for k, v in sorted(agg.items(), key=lambda kv: -kv[1][0]):
        print(f"  {str(k):<22} {v[0]:>4} {v[1]:>5} {v[2]:>5}")

    print()
    print("sample RE-FILED at 1800s (grant given; member reopened at same marker):")
    for eid, o, cnt in per_window.get(1800, [])[:12]:
        print(f"  {eid}  {str(o['plugin']):<12} marker={str(o['marker'])[:32]:<32} reopens={cnt}")


if __name__ == "__main__":
    main()
