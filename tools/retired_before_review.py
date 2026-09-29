#!/usr/bin/env python3
"""Does the petition outlive its own invitation? — time-to-terminal vs time-to-factor.

WHY. `peer_participation()` retains the peer conjunct as evidence: who was invited
against who answered, "so that three invited seats that all declined to look is a
finding". `invitation_deadletter_census.py` already showed one way that `absent` lies:
an invited id whose mailbox nobody reads is indistinguishable from a peer who read the
ask and ignored it. This measures a SECOND way, with a different mechanism: the row was
already terminal when the invitee woke. Nothing retracts an invitation when its
petition is decided, withdrawn or expired, so the notice keeps its place in the primer
and the invitee spends a wake slot dereferencing a corpse.

Specimen that prompted this (CBP 2026-09-03): codex opened 65ca4b09904b7c94 at
05:40:17Z and invited claude-code in the same second. Codex SELF-WITHDREW at 05:42:44Z,
147s later. The review_request notice was still live in claude-code's 06:07Z primer --
27 minutes after the subject died -- and dereferenced to `status=denied`. No factor was
possible; the row records claude-code as invited-and-silent.

WHAT IS COMPUTED, and against what denominator. Population is every
`gate_escalation_opened` carrying a non-empty `invited_peers`; that is complete over
opened escalations, so shares here have an honest denominator. For each, the terminal
event is the FIRST of decided / withdrawn / expired seen for that id. Separately, every
`gate_escalation_corroborated` gives an observed factor latency measured FROM OPEN --
not from the ruling, because the question is how long a reviewer takes to arrive, not
how late it was relative to a decision it never saw.

The comparison is then a survival question: of rows that invited someone, what share
were still alive at the p50 / p75 observed factor latency? A row that dies before the
median reviewer arrives cannot be reviewed by a median reviewer, whatever the
invitation says.

TWO THINGS THIS DOES NOT CLAIM. It does not claim the invitee was awake -- per-seat wake
times are not on this chain, so "could not have reviewed" here means "the row was
terminal", not "the seat tried and failed". And a short-lived row is not by itself a
defect: an asker who withdraws promptly is behaving well. The defect, if any, is that
the invitation is not retracted with it.

MEASURED (CBP, chain window 2026-08-31T02:22Z -> 2026-09-03T06:13Z, 20k entries,
138 opened / 134 invited, 1072 invitations issued):

    median lifetime of an invited row       95 s      (p25 24 s, p10 14 s)
    median factor latency from open        822 s      (p75 1374 s, p90 2207 s)
    invited rows still alive at 822 s     18/133 = 13.5%
    factors landing before the ruling      18/71 = 25.4%
    invited rows with an in-time factor    14/134 = 10.4%

So the reviewers are not shirking and they are not merely late: for 86.5% of invited
rows the decision has already happened by the time a median-speed reviewer arrives.
42.1% of invited rows are terminal within 60 s, and that fast population is not an
automation artefact -- 48 of those 56 are the OPERATOR approving through
`operator_session`, the remaining 8 are askers withdrawing. A human deciding promptly
is the single largest producer of unreviewable rows.

Two structural facts make this a race the reviewer cannot win. `invited_peers` is
exactly 8 on 134 of 134 rows -- the pool is filled to MAX_INVITED_PEERS unconditionally,
with no reference to how long the row is expected to live. And nothing retracts an
invitation when the row goes terminal, so the notice keeps its place in the invitee's
primer indefinitely.

WHAT THIS DOES AND DOES NOT OVERTURN. That most factors land after the ruling was
already recorded (~11% reach the decision); this window re-derives that independently
at 10.4%, which is a replication, not a new finding. What is new is the MECHANISM and
its direction: the gap is not reviewer diligence but a decision latency an order of
magnitude shorter than the mesh's wake-notify-drain-read path. That matters because it
eliminates a whole class of remedy -- exhorting peers to review faster cannot close a
95s-vs-822s gap -- and it means `bar_met_if_decided_now` and the "corroborate-or-dissent"
framing describe a gating step that, measured, is an audit trail.

Usage: python3 retired_before_review.py [MAX_ENTRIES] [--json]
"""
from __future__ import annotations
import datetime, json, re, sys, statistics
from collections import Counter

sys.path.insert(0, __import__("os").path.dirname(__import__("os").path.abspath(__file__)))
from chain_walk import ChainWalker, payload

MAX = 60_000
JSON_OUT = False
_a = sys.argv[1:]
while _a:
    x = _a.pop(0)
    if x == "--json": JSON_OUT = True
    else: MAX = int(x)

TERMINAL = {"gate_escalation_decided", "gate_escalation_withdrawn", "gate_escalation_expired"}

def esc_id(p):
    return p.get("escalation_id") or p.get("id")

def ts(e, p):
    """Epoch seconds. Payload ints win; else parse the ENTRY's ISO timestamp.

    The chain stamps 9 fractional digits (`...733726210+00:00`), which
    `datetime.fromisoformat` rejects, so the fraction is truncated to 6. Terminal
    payloads carry no numeric time at all -- reading only the payload silently
    yields None for every decided/withdrawn row, which is how the first run of this
    census reported zero terminals against a corpus that plainly had them.
    """
    for k in ("at", "lapsed_at", "opened_at"):
        v = p.get(k)
        if isinstance(v, (int, float)): return float(v)
    raw = e.get("timestamp")
    if isinstance(raw, str):
        m = re.match(r"^(.*\.\d{6})\d*(.*)$", raw)
        if m: raw = m.group(1) + m.group(2)
        try:
            return datetime.datetime.fromisoformat(raw).timestamp()
        except ValueError:
            return None
    return None

w = ChainWalker()
opened, terminal, factors = {}, {}, []
n = 0
for e in w.walk(max_entries=MAX):
    n += 1
    et = e.get("eventType")
    if et not in TERMINAL and et not in ("gate_escalation_opened", "gate_escalation_corroborated"):
        continue
    p = payload(e)
    eid = esc_id(p)
    if not eid: continue
    t = ts(e, p)
    if et == "gate_escalation_opened":
        if eid not in opened: opened[eid] = (p, t)
    elif et in TERMINAL:
        prev = terminal.get(eid)
        if prev is None or (t is not None and prev[1] is not None and t < prev[1]):
            terminal[eid] = (et, t, p)
    else:
        factors.append((eid, t, p))

invited = {k: v for k, v in opened.items() if v[0].get("invited_peers")}

# observed factor latency from OPEN
lat = []
for eid, t, p in factors:
    o = opened.get(eid)
    if o and t is not None and o[1] is not None:
        lat.append(t - o[1])
lat.sort()

def pct(xs, q):
    if not xs: return None
    i = min(len(xs) - 1, int(q * len(xs)))
    return xs[i]

p50, p75, p90 = pct(lat, .50), pct(lat, .75), pct(lat, .90)

lifetimes, by_kind = [], Counter()
unresolved = 0
for eid, (p, ot) in invited.items():
    t = terminal.get(eid)
    if not t or t[1] is None or ot is None:
        unresolved += 1
        continue
    by_kind[t[0]] += 1
    lifetimes.append((eid, t[1] - ot, t[0], p.get("plugin_id"), p.get("invited_peers")))

lifetimes.sort(key=lambda r: r[1])
lifes = [r[1] for r in lifetimes]

def alive_at(threshold):
    if threshold is None or not lifes: return None
    return sum(1 for x in lifes if x > threshold)

out = {
    "entries_walked": n,
    "opened": len(opened),
    "opened_with_invites": len(invited),
    "invited_resolved": len(lifetimes),
    "invited_unresolved_no_terminal": unresolved,
    "factors_seen": len(factors),
    "factor_latency_from_open_secs": {
        "n": len(lat), "p50": p50, "p75": p75, "p90": p90,
        "median": statistics.median(lat) if lat else None,
    },
    "terminal_kind": dict(by_kind),
    "lifetime_secs": {
        "n": len(lifes),
        "p10": pct(lifes, .10), "p25": pct(lifes, .25), "p50": pct(lifes, .50),
        "p75": pct(lifes, .75), "p90": pct(lifes, .90),
        "min": lifes[0] if lifes else None, "max": lifes[-1] if lifes else None,
    },
    "survival": {
        "alive_at_factor_p50": alive_at(p50),
        "alive_at_factor_p75": alive_at(p75),
        "alive_at_factor_p90": alive_at(p90),
        "denominator": len(lifes),
    },
    "shortest_lived": [
        {"id": r[0], "lifetime_s": round(r[1], 1), "terminal": r[2], "asker": r[3],
         "n_invited": len(r[4] or [])}
        for r in lifetimes[:12]
    ],
}

if JSON_OUT:
    print(json.dumps(out, indent=2))
else:
    print(f"walked {n} entries; {len(opened)} opened, {len(invited)} invited >=1 peer")
    print(f"factor latency FROM OPEN (n={len(lat)}): p50={p50} p75={p75} p90={p90}")
    print(f"terminal kinds: {dict(by_kind)}  (unresolved: {unresolved})")
    L = out["lifetime_secs"]
    print(f"lifetime of invited rows (n={L['n']}): p10={L['p10']} p25={L['p25']} "
          f"p50={L['p50']} p75={L['p75']} p90={L['p90']} max={L['max']}")
    s = out["survival"]
    d = s["denominator"] or 1
    for q in ("p50", "p75", "p90"):
        a = s[f"alive_at_factor_{q}"]
        if a is not None:
            print(f"  alive at factor {q}: {a}/{d} = {100*a/d:.1f}%  "
                  f"(dead before a {q} reviewer: {100*(d-a)/d:.1f}%)")
    print("shortest-lived invited rows:")
    for r in out["shortest_lived"]:
        print(f"  {r['id']} {r['lifetime_s']:>8}s {r['terminal']:<28} asker={r['asker']} invited={r['n_invited']}")
