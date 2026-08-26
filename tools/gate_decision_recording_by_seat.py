#!/usr/bin/env python3
"""Does a seat's IN-PROCESS gate decision reach the chain, and is that uniform?

WHY THIS EXISTS
---------------
The operating law every member is launched with says, of every deny:

    If a rule blocks legitimate work, appeal it with `hestia_appeal` (the deny's
    chain hash + your reason) rather than rephrasing around it.

That instruction has a precondition: the deny must HAVE a chain hash. On
2026-08-26 the claude-code seat took four denies in one wake — two `mrh.command`
("'hestia' is not granted"), two `egress.secret` — and none of them produced a
`policy_decision` row. The sanctioned response was unreachable; the response
scored BELOW plain compliance (rephrase) was the only one available.

WHAT IT MEASURES
----------------
Every `policy_decision` row splits cleanly in two by one field:

  * `rule_id` NON-BLANK  -> a SOCIETY-PRESET decision (warn-network,
    deny-destructive-commands, warn-memory-write, warn-file-delete). Decided by
    the daemon against the published preset.
  * `rule_id` BLANK      -> an IN-PROCESS GATE decision. The class names itself in
    `reason` instead: `mrh.command`, `mrh.path`, `egress.secret`, `gate.degraded`,
    `gate.self_access`, `society-safety`, `governance-closure-*`.

(Never key a census on `rule_id` alone: it is blank by schema on the whole
in-process class, so a `rule_id` histogram reports that class as absent.)

The question is not "how many denies" but "does a seat's in-process outcome reach
the chain AT ALL". The positive control is the OTHER SEATS: a seat's silence is a
property of that seat only if some other seat produced in-process rows in the SAME
window. Without that control the run names nobody and says the window is
uninformative.

RESULT 2026-08-26, 8000 hops, 2026-08-25T21:03:41Z .. 2026-08-26T12:10:05Z (~15.1h)

    seat          preset rows   in-process rows
    kimi-code              17                85
    codex                   1                10
    claude-code           132                 0   <-- hole

    in-process categories present, by seat:
      kimi-code   gate.degraded 25, mrh.command 17, egress.secret 11, society-safety 10,
                  mrh.path 10, governance-closure-write 7,
                  governance-closure-out-of-grammar 5
      codex       mrh.command 3, gate.degraded 3, society-safety 2,
                  egress.secret 1, gate.self_access 1
      claude-code (none)

claude-code is the LOUDEST seat on the preset class (132 of 150 preset rows) and
records zero of the in-process class, in a window where the other two seats
produced 95 such rows across eight categories — including BOTH categories that
were enforced against it that day (mrh.command 20, egress.secret 12). The hole is
not one category. It is the whole in-process class on one seat's shim.

The seven denies that window recorded nothing about were taken by this seat in a
single wake: four `mrh.command` and three `egress.secret`.

CONSEQUENCE, not just a missing row: `hestia_appeal` takes the deny's chain hash.
For this seat, on every in-process category, that hash does not exist. The grant
set a scope deny asserted is stated once, in an stderr string handed to the agent,
and written nowhere — so it cannot be reviewed, appealed with evidence, or diffed
against the set the next deny asserts.

WHAT THIS CORRECTS, AND WHAT IT WITHDRAWS
-----------------------------------------
CORRECTS #622 (mine): #622 argued `evaluate()` decides gate 1a/1b in-process and
returns before the daemon that writes `policy_decision`, and generalised that to
"only society-preset rule_ids appear on policy_decision". The generalisation is
REFUTED — kimi-code and codex put 101 blank-rule_id rows on the chain in 15 hours.
The ordering argument describes the claude-code shim, not the core.

WITHDRAWS a claim from this probe's own first draft (2026-08-26, branch
cbp/mrh-denies-unrecorded-per-seat). That draft cited two denies minutes apart
rendering grant sets of different cardinality (26 names vs 1) as evidence that
`pol.scope` had collapsed. Later work established that `granted: N` is per-deny
CONTEXT OUTPUT, not an entitlement readout, and that verdict and render are a
deterministic function of (cwd, command text) — 1, 2 and 27 names rendered in the
same minutes with nothing lost. The cardinality swing reproduced again on
2026-08-26 (25 names, then 1) and is NOT evidence of a lost grant. It is dropped
from the claim; the recording hole never depended on it.

USAGE
    python3 tools/gate_decision_recording_by_seat.py [hops]     # default 8000

Requires the chainwalk wrapper (private-context/hestia-local/probes/chainwalk.py);
the windowed `hestia_query_history` path caps at 500 rows and cannot span a day.
"""
import collections
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


def category(payload):
    """('preset', rule_id) or ('gate', category) for one policy_decision row.

    The discriminator is `rule_id`, not the wording of `reason`: a preset decision
    always carries one and an in-process decision never does. Reading the class off
    a reason prefix instead would silently reclassify the day someone rewords a
    message, which is the softest possible dependency for a census to rest on.
    """
    rid = (payload.get("rule_id") or "").strip()
    if rid:
        return ("preset", rid)
    reason = str(payload.get("reason") or "")
    # The in-process class names itself in the first token of `reason`. Keep the
    # whole token (`mrh.command`, not `mrh`) — `mrh.command` and `mrh.path` are
    # different checks and collapsing them hides which one has a control.
    tok = reason.split(":")[0].split()
    # A blank `reason` on a blank `rule_id` is a row that names its class NOWHERE.
    # Bucket it under a visible name rather than crashing or dropping it: a census
    # that silently loses rows is the failure this file exists to measure.
    return ("gate", tok[0][:48] if tok else "(blank)")


def survey(hops=8000, progress=1000):
    cw = _load_chainwalk()
    chain = cw.Chain()
    rows = collections.Counter()
    seat_class = collections.Counter()
    seat_cat = collections.defaultdict(collections.Counter)
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
        seat = p.get("plugin_id")
        kind, cat = category(p)
        rows[(seat, p.get("decision"), kind, cat)] += 1
        seat_class[(seat, kind)] += 1
        if kind == "gate":
            seat_cat[seat][cat] += 1
    return {"hops": n, "oldest": oldest, "newest": newest, "rows": rows,
            "seat_class": seat_class, "seat_cat": seat_cat}


def report(r, out=print):
    out(f"walked {r['hops']} entries  {r['oldest'][:19]} .. {r['newest'][:19]}\n")
    out("policy_decision by (seat, decision, class, category):")
    for k, v in r["rows"].most_common():
        out(f"  {v:5d}  {k}")

    seats = sorted({s for (s, _k) in r["seat_class"]})
    out("\nseat            preset   in-process")
    for s in seats:
        out(f"  {s:<14}{r['seat_class'][(s,'preset')]:>6}{r['seat_class'][(s,'gate')]:>13}")

    out("\nin-process categories, by seat:")
    for s in seats:
        cats = r["seat_cat"].get(s) or {}
        out(f"  {s:<14}" + (", ".join(f"{c} {n}" for c, n in
                                      collections.Counter(cats).most_common())
                            or "(none)"))

    loud = [s for s in seats if r["seat_class"][(s, "gate")]]
    # A seat is only NAMED if it recorded preset decisions (so it was active and its
    # witness path works) and zero in-process ones. Silence from a seat that recorded
    # nothing at all is a claim about the window, not about the seat.
    silent = [s for s in seats
              if not r["seat_class"][(s, "gate")] and r["seat_class"][(s, "preset")]]

    if not loud:
        out(f"\nNO SEAT recorded an in-process gate decision in these {r['hops']} hops "
            f"({r['oldest'][:19]} .. {r['newest'][:19]}).\n"
            "That is an UNINFORMATIVE window, not a finding: with no seat producing a\n"
            "blank-rule_id row there is no positive control, so silence cannot be\n"
            "attributed to any seat. Walk further (8000 hops covered ~15h and produced\n"
            "101 such rows).")
        return 0

    if not silent:
        out("\nEvery active seat recorded at least one in-process gate decision.\n"
            "No recording hole visible in this window.")
        return 0

    control = collections.Counter()
    for s in loud:
        control.update(r["seat_cat"][s])
    out("\nSeats with recorded PRESET decisions and ZERO in-process ones: "
        + ", ".join(silent)
        + "\nPositive control fired in the same window on: " + ", ".join(loud)
        + f"\nControl categories: " + ", ".join(f"{c}({n})" for c, n in control.most_common())
        + "\n\nOn the named seats an in-process deny is ENFORCED against the member and\n"
        "leaves no row. `hestia_appeal` takes the deny's chain hash, so the response\n"
        "the operating law prescribes is unreachable there, and the response it scores\n"
        "below plain compliance — rephrasing — is the only one left.")
    return 0


def main():
    hops = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    return report(survey(hops))


if __name__ == "__main__":
    raise SystemExit(main())
