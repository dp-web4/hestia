#!/usr/bin/env python3
"""Does a seat's IN-PROCESS gate decision reach the chain, and is that uniform?

WHY THIS EXISTS
---------------
The operating law every member is launched with says, of every deny:

    If a rule blocks legitimate work, appeal it with `hestia_appeal` (the deny's
    chain hash + your reason) rather than rephrasing around it.

That instruction has a precondition: the deny must HAVE a chain hash. On
2026-08-26 the claude-code seat took seven in-process denies in one wake — four
`mrh.command` ("'hestia' is not granted"), three `egress.secret` — and none of
them produced a `policy_decision` row. The sanctioned response was unreachable;
the response scored BELOW plain compliance (rephrase) was the only one available.
(An eighth was enforced against this seat while the fix below was being written,
with the same result — see the re-run in RESULT.)

WHAT IT MEASURES
----------------
Every `policy_decision` row splits in two by its PRODUCER, and the field that
names the producer is `adjudicator`:

  * `adjudicator` ABSENT   -> a DAEMON decision, evaluated against the published
    preset inside the hub (`handler.rs`, the gate branch of the action surface and
    `gate_direct_tool`). Neither site writes the key at all. Its category is the
    `rule_id` the preset carries: warn-network, deny-destructive-commands, ...
  * `adjudicator` PRESENT  -> a CALLER-REPORTED decision: a seat's own IN-PROCESS
    gate, telling the hub what it already enforced. `tool_witness_decision` takes
    it via `require_string`, so a row of this class CANNOT exist without one; the
    observed values are exactly `plugin-gate:<seat>`. The class names itself in
    `reason`: `mrh.command`, `mrh.path`, `egress.secret`, `gate.degraded`,
    `gate.self_access`, `society-safety`, `governance-closure-*`.

WHY NOT `rule_id`, WHICH WOULD WORK TODAY. This probe's first version keyed the
split on `rule_id` blankness. Measured over the same 8000 hops, the two
discriminators agree on every one of 262 rows — the 2x2 is perfectly diagonal,
zero disagreements — so nothing in the published census changes. But that
agreement is an accident of the SENDER, not a contract. On the caller path
`rule_id` is `optional_string(...).unwrap_or_default()`, and the daemon side of
that argument has ALREADY landed: `witness_decision_threads_caller_rule_id_to_-
reputation_row` pins it, and its own comment says it must land before any hook
sends the arg. The shared hook sender simply does not send it yet. The day one
does, every in-process row grows a non-blank `rule_id`, a `rule_id`-keyed census
silently reclassifies the entire class as presets, and this probe reports the
recording hole as CLOSED while it is open — no error, no crash, a plausible
answer. `adjudicator` cannot fail that way in either direction: the caller path
is refused without it and the daemon path never emits it.

(Corollary, and the reason the first version was wrong twice over: a census keyed
on `rule_id` blankness reads blank as "the in-process class", and a census keyed
on `rule_id` VALUES reads blank as "absent". Both rest on the same soft
dependency — a field whose emptiness is a property of who is calling this week.)

The question is not "how many denies" but "does a seat's in-process outcome reach
the chain AT ALL". The positive control is the OTHER SEATS: a seat's silence is a
property of that seat only if some other seat produced in-process rows in the SAME
window. Without that control the run names nobody and says the window is
uninformative.

RESULT 2026-08-26, 8000 hops, 2026-08-25T21:23:28Z .. 2026-08-26T12:20:59Z (~15.0h),
re-measured on the `adjudicator` discriminator after codex's review of #638:

    seat          daemon rows   in-process rows
    kimi-code              16                85
    codex                   1                10
    claude-code           150                 0   <-- hole

    in-process categories present, by seat:
      kimi-code   gate.degraded 25, mrh.command 17, egress.secret 11, society-safety 10,
                  mrh.path 10, governance-closure-write 7,
                  governance-closure-out-of-grammar 5
      codex       mrh.command 3, gate.degraded 3, society-safety 2,
                  egress.secret 1, gate.self_access 1
      claude-code (none)

    the two discriminators, cross-tabulated over the same 262 rows:
      adjudicator ABSENT  & rule_id NON-BLANK   167
      adjudicator PRESENT & rule_id BLANK        95
      disagreements                               0
      adjudicator values: plugin-gate:kimi-code 85, plugin-gate:codex 10

The observed `adjudicator` is `plugin-gate:<seat>` on all 95 caller-reported rows
and absent on all 167 daemon rows — an independent second seat (codex) reproduced
that same shape in a shifted window. The reclassification therefore moves NO row:
it makes the same measurement on a field that cannot drift.

This file as shipped, re-run 2026-08-26T12:25:05Z over the next 8000 hops
(2026-08-25T21:29:00Z ..), through the tracked public reader: claude-code 166
daemon / 0 in-process, codex 1 / 10, kimi-code 16 / 85. And a live datapoint from
the wake that wrote this fix: an `mrh.command` deny was enforced against this seat
at 12:2x while the probe was open, and it appears in none of these rows.

claude-code is the LOUDEST seat on the daemon class (150 of 167 daemon rows) and
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
REFUTED — kimi-code and codex put 95 caller-reported in-process rows on the chain
in 15 hours. The ordering argument describes the claude-code shim, not the core.

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

Reads the chain through its TRACKED SIBLING, `chain_walk.ChainWalker` — no private
dependency, so a clean public checkout can reproduce this. (The first version
imported a wrapper that lives only in a private MRH, which made a public artifact
unrunnable by any member without that repo. Caught by codex on #638.) The windowed
`hestia_query_history` path caps at 500 rows and cannot span a day; the walker
chains `prevHash` past that cap.
"""
import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from chain_walk import ChainWalker, payload  # noqa: E402


def producer(row):
    """('daemon', rule_id) or ('gate', category) for one policy_decision row.

    THE DISCRIMINATOR IS `adjudicator`, and it is a producer contract rather than
    an observed correlation:

      * `tool_witness_decision` takes `adjudicator` with `require_string` and writes
        it into every row it appends. A caller-reported row without one does not
        exist — the call is refused before anything reaches the chain.
      * The two daemon emit sites (the gate branch of the action surface, and
        `gate_direct_tool`) never write the key in any spelling.

    So presence is decided by WHICH CODE PATH APPENDED THE ROW. Neither `rule_id`
    nor the wording of `reason` has that property: `rule_id` is caller-optional and
    a hook wiring it flips the whole in-process class to the wrong side silently
    (see the module docstring), and a reason prefix reclassifies the day someone
    rewords a message.

    `reason` is still used, but only for the CATEGORY LABEL within the caller class
    — a wording change there mislabels one bucket, it does not move a row across
    the split the finding rests on.
    """
    adj = str(row.get("adjudicator") or "").strip()
    if not adj:
        # Daemon side. Its category is the preset's `rule_id`; a daemon row without
        # one names its rule nowhere, so bucket it visibly instead of dropping it.
        return ("daemon", (row.get("rule_id") or "").strip() or "(no rule_id)")
    reason = str(row.get("reason") or "")
    # The in-process class names itself in the first token of `reason`. Keep the
    # whole token (`mrh.command`, not `mrh`) — `mrh.command` and `mrh.path` are
    # different checks and collapsing them hides which one has a control.
    tok = reason.split(":")[0].split()
    # A caller-reported row with a blank `reason` names its class NOWHERE. Bucket it
    # under a visible name rather than crashing or dropping it: a census that
    # silently loses rows is the failure this file exists to measure.
    return ("gate", tok[0][:48] if tok else "(blank)")


def survey(hops=8000):
    chain = ChainWalker()
    rows = collections.Counter()
    seat_class = collections.Counter()
    seat_cat = collections.defaultdict(collections.Counter)
    n = 0
    newest = oldest = None
    for e in chain.walk(max_entries=hops):
        n += 1
        if newest is None:
            newest = e["timestamp"]
        oldest = e["timestamp"]
        if e.get("eventType") != "policy_decision":
            continue
        p = payload(e)
        seat = p.get("plugin_id")
        kind, cat = producer(p)
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
    out("\nseat            daemon   in-process")
    for s in seats:
        out(f"  {s:<14}{r['seat_class'][(s,'daemon')]:>6}{r['seat_class'][(s,'gate')]:>13}")

    out("\nin-process categories, by seat:")
    for s in seats:
        cats = r["seat_cat"].get(s) or {}
        out(f"  {s:<14}" + (", ".join(f"{c} {n}" for c, n in
                                      collections.Counter(cats).most_common())
                            or "(none)"))

    loud = [s for s in seats if r["seat_class"][(s, "gate")]]
    # A seat is only NAMED if the DAEMON recorded decisions about it (so it was active
    # and reachable) and it reported zero in-process ones. Silence from a seat that
    # appears nowhere is a claim about the window, not about the seat.
    silent = [s for s in seats
              if not r["seat_class"][(s, "gate")] and r["seat_class"][(s, "daemon")]]

    if not loud:
        out(f"\nNO SEAT recorded an in-process gate decision in these {r['hops']} hops "
            f"({r['oldest'][:19]} .. {r['newest'][:19]}).\n"
            "That is an UNINFORMATIVE window, not a finding: with no seat producing a\n"
            "caller-reported row there is no positive control, so silence cannot be\n"
            "attributed to any seat. Walk further (8000 hops covered ~15h and produced\n"
            "95 such rows).")
        return 0

    if not silent:
        out("\nEvery active seat recorded at least one in-process gate decision.\n"
            "No recording hole visible in this window.")
        return 0

    control = collections.Counter()
    for s in loud:
        control.update(r["seat_cat"][s])
    out("\nSeats the DAEMON recorded decisions for, with ZERO in-process ones: "
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
