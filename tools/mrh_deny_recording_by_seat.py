#!/usr/bin/env python3
"""Are gate-1b (MRH scope) decisions recorded, and is recording uniform across seats?

WHY THIS EXISTS
---------------
On 2026-08-26 the claude-code seat took five `mrh.command` denies inside twelve
minutes, all of the form

    hestia: deny [mrh.command] - 'Bash' command reaches outside your granted scope:
    'hestia' is not granted (granted: metalinxx)

while `git -C <workspace>/hestia log --oneline -1` returned rc=0 TWICE in the same
span, once twenty seconds after a deny. So `hestia` was granted, and the deny said it
was not. Worse, two denies minutes apart rendered grant sets of DIFFERENT cardinality:

    deny A  "'<workspace root>' is not granted (granted: metalinxx+4-lab+4-life+ACT+
             ...+web4-trust-core)"                                      -> 26 names
    deny B  "'hestia' is not granted (granted: metalinxx)"              ->  1 name

`evaluate()` builds that set as `list(pol.scope) + launch_cwd_repo(profile, ws)`, and
`launch_cwd_repo` returns AT MOST ONE segment, so a 26->1 swing is a change in
`pol.scope` — the per-agent policy — not in the cwd grant.

None of that is diagnosable after the fact, because the effective grant set is stated
in exactly one place: an stderr string handed to the agent, which is not written to the
chain. That is what this probe measures.

WHAT IT MEASURES
----------------
Walks the witness chain and counts `policy_decision` rows by (seat, decision, rule),
separating rows whose `reason` starts with `mrh.` from society-preset rule_ids. The
question it answers is not "how many denies" but "does a seat's gate-1b outcome reach
the chain at all", and the positive control is the OTHER seats: if kimi-code and codex
produce `mrh.*` rows in the same window where claude-code produces none, the absence is
a property of that seat's shim, not of the window or of the chain.

RESULT 2026-08-26 (8000 hops, 2026-08-25T05:05Z .. 2026-08-26T07:11Z, ~26h)

    policy_decision by (seat, decision, rule)
       127  ('claude-code', 'warn', 'warn-network')
        59  ('claude-code', 'warn', 'warn-memory-write')
        59  ('kimi-code',   'deny', '?')
        25  ('kimi-code',   'deny', 'mrh')
        23  ('codex',       'deny', '?')
        17  ('claude-code', 'deny', 'deny-destructive-commands')
         5  ('codex',       'deny', 'mrh')
         5  ('kimi-code',   'deny', 'deny-destructive-commands')
         4  ('claude-code', 'warn', 'warn-file-delete')
         4  ('kimi-code',   'warn', 'warn-file-delete')
         1  ('codex',       'deny', 'deny-destructive-commands')

    mrh.* rows: 30 total — kimi-code 25, codex 5, claude-code 0.

claude-code's recorded decisions are EXCLUSIVELY society-preset rule_ids. Five gate-1b
denies were enforced against it during that window; zero were recorded.

WHAT THIS CORRECTS
------------------
#622 (mine) concluded that `evaluate()` decides gate 1a/1b in-process and returns before
the daemon that writes `policy_decision`, so "only society-preset rule_ids appear on
policy_decision" — and generalised that to the mechanism. The generalisation is WRONG:
kimi-code and codex reach `policy_decision` with `mrh.*` reasons thirty times in the
same 26 hours. The ordering argument holds for the claude-code shim and does not hold
fleetwide. The hole is one seat's shim, not the core's evaluation order.

The narrow #622 claim (this seat's scope denies never land) is CORROBORATED here with a
denominator and a positive control, which it previously lacked.

USAGE
    python3 tools/mrh_deny_recording_by_seat.py [hops]     # default 8000

Requires the chainwalk wrapper (private-context/hestia-local/probes/chainwalk.py); the
windowed `hestia_query_history` path caps at 500 rows and cannot span a day.
"""
import collections
import json
import os
import sys

CHAINWALK_DIRS = [
    os.path.expanduser("~/ai-workspace/private-context/hestia-local/probes"),
    "/mnt/c/exe/projects/ai-agents/private-context/hestia-local/probes",
]


def _load_chainwalk():
    for d in CHAINWALK_DIRS:
        if os.path.isfile(os.path.join(d, "chainwalk.py")):
            sys.path.insert(0, d)
            import chainwalk  # noqa: E402
            return chainwalk
    raise SystemExit("chainwalk.py not found in: " + ", ".join(CHAINWALK_DIRS))


def survey(hops=8000, progress=1000):
    cw = _load_chainwalk()
    chain = cw.Chain()
    by = collections.Counter()
    mrh_rows = []
    n = 0
    newest = oldest = None
    for e in chain.walk(max_hops=hops, progress=progress):
        n += 1
        if newest is None:
            newest = e["timestamp"]
        oldest = e["timestamp"]
        if e["eventType"] != "policy_decision":
            continue
        p = cw.payload(e)
        reason = str(p.get("reason"))
        is_mrh = reason.startswith("mrh.")
        by[(p.get("plugin_id"), p.get("decision"),
            "mrh" if is_mrh else (p.get("rule_id") or "?"))] += 1
        if is_mrh:
            mrh_rows.append({
                "pos": e["chainPosition"], "ts": e["timestamp"],
                "seat": p.get("plugin_id"), "decision": p.get("decision"),
                "reason": reason, "rule_id": p.get("rule_id"),
                # kimi's mrh rows carry session_id but host_session_id=None, claude's
                # society rows carry both — the producers differ, which is the lead.
                "session_id": p.get("session_id"),
                "host_session_id": p.get("host_session_id"),
                "attempted": str(p.get("attempted"))[:200],
            })
    return {"hops": n, "oldest": oldest, "newest": newest,
            "counts": by, "mrh_rows": mrh_rows}


def main():
    hops = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    r = survey(hops)
    print(f"walked {r['hops']} entries  {r['oldest'][:19]} .. {r['newest'][:19]}\n")
    print("policy_decision by (seat, decision, rule):")
    for k, v in r["counts"].most_common():
        print(f"  {v:5d}  {k}")

    seats = collections.Counter(x["seat"] for x in r["mrh_rows"])
    all_seats = {k[0] for k in r["counts"]}
    silent = sorted(s for s in all_seats if not seats.get(s))
    loud = sorted(s for s in all_seats if seats.get(s))

    print(f"\nmrh.* policy_decision rows: {len(r['mrh_rows'])}")
    for s in sorted(all_seats):
        # Only flag a seat once some OTHER seat has proved the window can carry the row.
        flag = "   <-- NO gate-1b outcome recorded" if (not seats.get(s) and loud) else ""
        print(f"  {seats.get(s, 0):5d}  {s}{flag}")

    # THE POSITIVE CONTROL IS THE OTHER SEATS. "claude-code has no mrh rows" is only a
    # claim about claude-code if some seat DOES have them in the SAME window; otherwise
    # it is a claim about the window. A 400-hop walk covers ~55 minutes and reports every
    # seat silent, which would publish a fleetwide hole that the 8000-hop walk refutes.
    # Refuse to name a seat unless the control fired.
    if not loud:
        print(f"\nNO SEAT recorded a gate-1b outcome in these {r['hops']} hops "
              f"({r['oldest'][:19]} .. {r['newest'][:19]}).\n"
              "That is an UNINFORMATIVE window, not a finding: with no seat producing an\n"
              "mrh.* row there is no positive control, so silence cannot be attributed to\n"
              "any seat. Walk further (8000 hops covered ~26h and produced 30 rows).")
        return 0

    if silent:
        print("\nSeats with recorded society-preset decisions but ZERO recorded gate-1b\n"
              "outcomes: " + ", ".join(silent)
              + "\nPositive control fired in the same window on: " + ", ".join(loud)
              + "\nA scope deny on the silent seats is enforced against the member and\n"
              "leaves no row, so the grant set it asserted cannot be reviewed, appealed\n"
              "with evidence, or diffed against the grant set asserted by the next deny.")
    else:
        print("\nEvery seat with recorded decisions also recorded at least one gate-1b\n"
              "outcome. No recording hole visible in this window.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
