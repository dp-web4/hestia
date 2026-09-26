#!/usr/bin/env python3
"""What does the witness chain think "the same act" IS? Measured, not read.

`derivation.rs:460` scores a deny 0.0 -- "retry-after-deny (re-ran the blocked act)", the
FLOOR of temperament -- when it finds a later policy_decision matching this signature:

    deny_sig = (session_id, tool_name, payload_sha256, target)
    retried  = same session, same tool, later position, within 10 minutes, AND
               (payload_sha256 non-empty AND equal) OR (target non-empty AND equal)

The comment at :491 says "`retried` only matches another POLICY_DECISION carrying the same
payload hash." That is not what the code does -- the disjunction also matches on `target`.
Two producer facts decide which arm actually carries the predicate, and neither is visible
from derivation.rs:

  1. The ONE deny recorder (`_shared/hestia_gate_mechanism.py:435 witness_decision_unified`)
     sends NO payload hash under any name. Nothing in the tree writes `payload_sha256`.
  2. `_extract_target(...)` (same file, :203) returns, for a shell tool,
     `cmd.split()[0]` -- THE BARE VERB. Its comment is about closing a case-sensitivity
     hole that left target EMPTY for codex; closing it made target PRESENT, and nobody
     measured the GRAIN of what it made present.

So the question this asks the chain: if the surviving arm is the verb, then every `git` in
a session is the same act as every other `git`, and the floor score fires on a coincidence.

WHY IT MATTERS MORE THAN IT LOOKS. `retried` sits in an else-if chain ABOVE the careful
`recast` detector (0.35, dual-sided receipt, explicitly conservative) -- so a false retry
PREEMPTS the accurate one. And the branches above it that would rescue a member --
escalation-opened/approved/denied -- all gate on `escalated`, which needs `answers_deny`,
which is null on every row ever written (hestia#537). The one defense is structurally dead,
so a false 0.0 always lands.

Sections:
  A. POPULATION -- how many rows carry each signature arm, and the VINTAGE of each. An arm
     that was alive once and is dead now reads identical to a live one in a lifetime count.
  B. GRAIN -- distinct targets vs rows, biggest collision classes, and the same for
     `attempted`, which sits on the SAME ROW and is never consulted by the predicate.
  C. THE PREDICATE, RUN -- reimplemented from derivation.rs. Every match is classified by
     comparing the two `attempted` summaries: IDENTICAL (a true retry), DIFFERS (the member
     is scored 0.0 for running something else), or UNDETERMINED (a side has no `attempted`
     -- counted separately rather than folded into either, since a missing field is not
     evidence of sameness).
  D. IMPACT -- the mean-temperament understatement per member, bounded both ways: the false
     rows really scored 0.0, and the truth is somewhere in [0.35 recast, 0.85 comply].

Confounds handled: cross-plugin rows sharing a session are excluded and counted; the
escalation/appeal preemption is measured per-deny against `answers_deny`/`deny_hash` rather
than assumed; the corpus head moves under the walk, so counts are as-of the run.

Read-only.

    python3 tools/retry_signature_grain.py          # MAX_ENTRIES=60000 by default
"""
from __future__ import annotations

import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chain_walk import ChainWalker, payload  # noqa: E402

RETRY_WINDOW = timedelta(minutes=10)
MAX = int(os.environ.get("MAX_ENTRIES", "60000"))
ESCALATED_DENY, APPEALED_DENY = set(), set()


def ts(e):
    t = e.get("timestamp")
    if not isinstance(t, str):
        return None
    try:
        return datetime.fromisoformat(t.replace("Z", "+00:00"))
    except ValueError:
        return None


def main():
    w = ChainWalker()
    rows = []
    for e in w.walk(max_entries=MAX):
        et = e.get("eventType")
        if et == "gate_escalation_opened":
            ad = payload(e).get("answers_deny")
            if ad: ESCALATED_DENY.add(ad)
            continue
        if et == "appeal":
            dh = payload(e).get("deny_hash")
            if dh: APPEALED_DENY.add(dh)
            continue
        if et != "policy_decision":
            continue
        p = payload(e)
        t = ts(e)
        if t is None:
            continue
        rows.append({
            "hash": e.get("hash") or "",
            "pos": e.get("chainPosition") or e.get("chain_position"),
            "t": t,
            "session": p.get("session_id") or "",
            "tool": p.get("tool_name") or "",
            "sha": p.get("payload_sha256") or "",
            "target": p.get("target") or "",
            "decision": p.get("decision") or "",
            "attempted": p.get("attempted") or "",
            "plugin": p.get("plugin_id") or "",
        })
    rows.sort(key=lambda r: r["t"])
    n = len(rows)
    print(f"policy_decision rows walked: {n}")
    if not n:
        return 1

    # -- A. population of the payload arm ------------------------------------
    sha_rows = [r for r in rows if r["sha"]]
    with_sha, with_target = len(sha_rows), sum(1 for r in rows if r["target"])
    print(f"\nA. THE TWO SIGNATURE ARMS")
    print(f"   payload_sha256 non-empty : {with_sha}/{n} ({100*with_sha/n:.1f}%)")
    print(f"   target         non-empty : {with_target}/{n} ({100*with_target/n:.1f}%)")
    if sha_rows:
        print(f"   payload arm by plugin    : {dict(Counter(r['plugin'] for r in sha_rows))}")
        print(f"   payload arm VINTAGE      : {min(r['t'] for r in sha_rows).date()}"
              f" .. {max(r['t'] for r in sha_rows).date()}")
        print(f"   whole-corpus vintage     : {rows[0]['t'].date()} .. {rows[-1]['t'].date()}")
        d30 = max(r["t"] for r in rows) - timedelta(days=3)
        recent = [r for r in rows if r["t"] >= d30]
        rs = sum(1 for r in recent if r["sha"])
        print(f"   LAST 3 DAYS              : {rs}/{len(recent)} rows carry a payload hash")

    # -- B. grain -------------------------------------------------------------
    tgt = Counter(r["target"] for r in rows if r["target"])
    att = Counter(r["attempted"] for r in rows if r["attempted"])
    print(f"\nB. GRAIN OF THE SURVIVING ARM")
    print(f"   distinct targets   : {len(tgt)} over {sum(tgt.values())} rows")
    print(f"   distinct attempted : {len(att)} over {sum(att.values())} rows")
    print(f"   -> a target names {sum(tgt.values())/max(1,len(tgt)):.1f} rows on average;"
          f" an attempted names {sum(att.values())/max(1,len(att)):.1f}")
    print("   biggest collision classes (target -> rows, distinct commands inside):")
    per_target_cmds = defaultdict(set)
    for r in rows:
        if r["target"] and r["attempted"]:
            per_target_cmds[r["target"]].add(r["attempted"])
    for t_, c in tgt.most_common(8):
        print(f"     {t_!r:24} {c:5} rows, {len(per_target_cmds.get(t_, ())):4} distinct commands")

    # -- C. the real predicate ------------------------------------------------
    denies = [r for r in rows if r["decision"] == "deny"]
    matched = matched_same_cmd = matched_diff_cmd = unmatched = undet = verb_only = 0
    cross_plugin = set(); victims = Counter(); true_retry = Counter(); falses = []
    examples = []
    by_session = defaultdict(list)
    for r in rows:
        by_session[r["session"]].append(r)
    for d in denies:
        end = d["t"] + RETRY_WINDOW
        hit = None
        for e in by_session[d["session"]]:
            if e["pos"] is not None and d["pos"] is not None and e["pos"] <= d["pos"]:
                continue
            if e["t"] > end or e["tool"] != d["tool"]:
                continue
            if e["plugin"] != d["plugin"]:
                cross_plugin.add(d["pos"])
                continue
            if (d["sha"] and e["sha"] == d["sha"]) or (d["target"] and e["target"] == d["target"]):
                hit = e
                break
        if hit is None:
            unmatched += 1
            continue
        matched += 1
        if not (hit["attempted"] and d["attempted"]):
            undet += 1
        elif hit["attempted"] != d["attempted"]:
            matched_diff_cmd += 1
            falses.append((d, hit))
            victims[d["plugin"]] += 1
            if d["target"] and "/" not in d["target"]:
                verb_only += 1
            if len(examples) < 6:
                examples.append((d, hit))
        else:
            matched_same_cmd += 1
            true_retry[d["plugin"]] += 1
    print(f"\nC. THE PREDICATE, RUN")
    print(f"   deny rows                        : {len(denies)}")
    print(f"   scored RETRY-AFTER-DENY          : {matched}")
    print(f"   ...where the command is IDENTICAL: {matched_same_cmd}   (a true retry)")
    print(f"   ...where the command DIFFERS     : {matched_diff_cmd}"
          + (f"  <-- {100*matched_diff_cmd/matched:.1f}% of all matches,"
             f" {100*matched_diff_cmd/max(1,matched_diff_cmd+matched_same_cmd):.1f}% of DECIDABLE ones"
             if matched else ""))
    print(f"        ...of those, matched on a BARE VERB target (no '/'): {verb_only}")
    print(f"   ...UNDETERMINED (a side has no `attempted`): {undet}")
    print(f"   no retry found                   : {unmatched}")
    print(f"   same-session-but-CROSS-PLUGIN rows skipped: {len(cross_plugin)} denies touched")
    print(f"\n   WHO ATE A FALSE 0.0 : {dict(victims)}")
    print(f"   who truly retried   : {dict(true_retry)}")
    preempted = sum(1 for d, _ in falses if d["hash"] in ESCALATED_DENY or d["hash"] in APPEALED_DENY)
    print(f"\n   CONFOUND CHECK — retry sits in an else-if chain after escalation/appeal.")
    print(f"   escalation_opened rows seen: {len(ESCALATED_DENY)}, appeal rows seen: {len(APPEALED_DENY)}")
    print(f"   of the {len(falses)} false matches, PREEMPTED by an escalation/appeal: {preempted}")
    print(f"   -> false 0.0 that ACTUALLY LANDS: {len(falses)-preempted}")
    # -- D. does it move a score? --------------------------------------------
    print(f"\nD. TEMPERAMENT IMPACT (retry=0.0 is the FLOOR; comply-after-deny=0.85, recast=0.35)")
    per = defaultdict(lambda: [0, 0])          # plugin -> [denies, false-zeros]
    for d in denies:
        per[d["plugin"]][0] += 1
    landed = Counter(d["plugin"] for d, _ in falses
                     if d["hash"] not in ESCALATED_DENY and d["hash"] not in APPEALED_DENY)
    for pl, c in landed.items():
        per[pl][1] = c
    for pl, (nd, fz) in sorted(per.items(), key=lambda kv: -kv[1][1]):
        if not nd:
            continue
        # counterfactual: those rows scored SOMETHING >= 0.35 instead of 0.0
        lo = fz * 0.35 / nd      # if every one was really a recast
        hi = fz * 0.85 / nd      # if every one was really compliance
        print(f"   {pl:12} denies={nd:5}  false 0.0={fz:4}  "
              f"mean temperament understated by {lo:.3f}..{hi:.3f}")
    for d, h in examples:
        print(f"\n   --- scored as a retry, but:")
        print(f"       target={d['target']!r} plugin={d['plugin']}")
        print(f"       DENIED : {d['attempted'][:110]}")
        print(f"       'RETRY': {h['attempted'][:110]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
