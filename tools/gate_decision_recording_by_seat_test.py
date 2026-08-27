#!/usr/bin/env python3
"""Pins for the recording census — the classifier and the two refusal arms.

The arms that matter are the NEGATIVE ones. A census that names a seat whenever it
sees no rows will name every seat on a short walk, publishing a fleetwide hole that
a longer walk refutes. So: A pins the classifier on both sides, B pins that the
census refuses to name anybody without a positive control, and C pins that it
refuses to name a seat that appears nowhere in the window.

D is the arm codex's review of #638 asked for, and it is the one with teeth. The
first version of this classifier keyed the split on `rule_id` blankness, which is
correct on every row on the chain TODAY and is not a producer contract: `rule_id`
is caller-optional, the daemon side of that argument has already landed, and the
only reason it is blank on in-process rows is that the shared hook sender does not
send it yet. D constructs the row that exists the day one does — in-process, with a
rule id — and pins that it still classifies as in-process. Under the old
discriminator that row reads as a daemon preset, and the census reports the
recording hole CLOSED while it is open. That is the failure mode being pinned: not
a crash, a plausible wrong answer.

The daemon is not touched. Every arm runs against synthetic rows, so this is a test
of the JUDGEMENT, not of the chain.

Usage: ./gate_decision_recording_by_seat_test.py     (runtime <1s, no daemon needed)
"""
import collections
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

spec = importlib.util.spec_from_file_location(
    "gdrbs", os.path.join(HERE, "gate_decision_recording_by_seat.py"))
gdrbs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gdrbs)

failures = []
checks = 0


def check(label, ok, detail=""):
    global checks
    checks += 1
    print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f"  <- {detail}"))
    if not ok:
        failures.append(label)


GATE = "plugin-gate:test-seat"  # the shape `tool_witness_decision` actually receives


def survey_of(rows):
    """Build the shape survey() returns, from (seat, decision, adjudicator, rule_id, reason)."""
    r = {"hops": 8000, "oldest": "2026-08-26T00:00:00Z", "newest": "2026-08-26T15:00:00Z",
         "rows": collections.Counter(), "seat_class": collections.Counter(),
         "seat_cat": collections.defaultdict(collections.Counter)}
    for seat, decision, adjudicator, rule_id, reason in rows:
        row = {"reason": reason}
        if adjudicator is not None:
            row["adjudicator"] = adjudicator
        if rule_id is not None:
            row["rule_id"] = rule_id
        kind, cat = gdrbs.producer(row)
        r["rows"][(seat, decision, kind, cat)] += 1
        r["seat_class"][(seat, kind)] += 1
        if kind == "gate":
            r["seat_cat"][seat][cat] += 1
    return r


def render(r):
    lines = []
    gdrbs.report(r, out=lines.append)
    return "\n".join(lines)


print("\nA. the classifier — `adjudicator` decides the PRODUCER, reason names the category")
check("A1 no adjudicator is a DAEMON decision, named from rule_id",
      gdrbs.producer({"rule_id": "warn-network", "reason": "Network access flagged"})
      == ("daemon", "warn-network"))
check("A2 an adjudicator is an IN-PROCESS decision, named from reason",
      gdrbs.producer({"adjudicator": GATE, "rule_id": "",
                      "reason": "mrh.command: not granted"})
      == ("gate", "mrh.command"))
check("A3 a MISSING rule_id key on a daemon row is named, never dropped",
      gdrbs.producer({"reason": "some preset fired"}) == ("daemon", "(no rule_id)"))
# The whole first token, not its prefix: two different checks share `mrh.` and only
# one of them may have a control in a given window.
check("A4 mrh.command and mrh.path do NOT collapse into one category",
      gdrbs.producer({"adjudicator": GATE, "reason": "mrh.command: x"})
      != gdrbs.producer({"adjudicator": GATE, "reason": "mrh.path: y"}))
check("A5 a whitespace-only adjudicator counts as ABSENT, not as a caller named ' '",
      gdrbs.producer({"adjudicator": "   ", "rule_id": "warn-file-delete",
                      "reason": "File deletion flagged"})
      == ("daemon", "warn-file-delete"))
check("A6 an adjudicator with a blank reason is named, never dropped",
      gdrbs.producer({"adjudicator": GATE, "rule_id": "", "reason": ""})
      == ("gate", "(blank)"))
check("A7 a null adjudicator is ABSENT, not the string 'None'",
      gdrbs.producer({"adjudicator": None, "rule_id": "warn-network", "reason": "x"})
      == ("daemon", "warn-network"))

print("\nB. no positive control -> name nobody")
out = render(survey_of([
    ("claude-code", "warn", None, "warn-network", "Network access flagged"),
    ("kimi-code", "warn", None, "warn-file-delete", "File deletion flagged"),
]))
check("B1 says the window is uninformative", "UNINFORMATIVE" in out, out)
check("B2 does NOT name a seat", "claude-code" not in out.split("UNINFORMATIVE")[1], out)
check("B3 does NOT assert a hole", "hole" not in out.lower(), out)
check("B4 tells the reader to walk further", "Walk further" in out, out)

print("\nC. control fired -> name the seat, and only the right one")
out = render(survey_of(
    [("claude-code", "warn", None, "warn-network", "Network access flagged")] * 3
    + [("kimi-code", "deny", "plugin-gate:kimi-code", "", "mrh.command: not granted")] * 2
    + [("kimi-code", "deny", "plugin-gate:kimi-code", "", "egress.secret: forbidden path")]
    + [("codex", "deny", "plugin-gate:codex", "", "gate.degraded")]))
check("C1 names the silent seat", "ZERO in-process ones: claude-code" in out, out)
check("C2 names the seats the control fired on",
      "control fired in the same window on: codex, kimi-code" in out, out)
check("C3 lists the control categories with counts",
      "mrh.command(2)" in out and "egress.secret(1)" in out, out)
check("C4 states the consequence, not just the count",
      "hestia_appeal" in out and "unreachable" in out, out)

print("\nC'. a seat that appears NOWHERE is not named — that is a claim about the window")
out = render(survey_of(
    [("kimi-code", "deny", "plugin-gate:kimi-code", "", "mrh.command: not granted")] * 2
    + [("kimi-code", "warn", None, "warn-file-delete", "File deletion flagged")]))
check("C5 a seat absent from the window entirely cannot be named",
      "codex" not in out, out)
check("C6 with every active seat recording in-process rows, no hole is claimed",
      "No recording hole visible" in out, out)

print("\nD. the regression that the OLD discriminator would have gotten wrong")
# The row that exists the day the shared hook sender wires the already-supported
# `rule_id` argument: caller-reported, adjudicator present, AND carrying a rule id.
wired = {"adjudicator": "plugin-gate:kimi-code", "rule_id": "mrh-scope-deny",
         "reason": "mrh.command: not granted"}
check("D1 an in-process row with a NON-BLANK rule_id is still in-process",
      gdrbs.producer(wired) == ("gate", "mrh.command"), gdrbs.producer(wired))
check("D2 the old rule_id-blankness rule would have called that row a daemon preset",
      bool((wired.get("rule_id") or "").strip()) is True)
# And end to end: a window where every in-process row is wired must still find the
# hole, not report it closed.
out = render(survey_of(
    [("claude-code", "warn", None, "warn-network", "Network access flagged")] * 3
    + [("kimi-code", "deny", "plugin-gate:kimi-code", "mrh-scope-deny",
        "mrh.command: not granted")] * 2
    + [("codex", "deny", "plugin-gate:codex", "egress-secret-deny",
        "egress.secret: forbidden path")]))
check("D3 the census still names claude-code when every in-process row carries a rule id",
      "ZERO in-process ones: claude-code" in out, out)
check("D4 and the wired rows still count as the positive control",
      "control fired in the same window on: codex, kimi-code" in out, out)

print("\nE. `adjudicator` is a producer contract, not an observed correlation")
# Not a behaviour of this module — a pin on WHY the classifier is shaped this way,
# so a reader who wants to move the discriminator has to argue with the source.
#
#   caller path  core/src/server/handler.rs  `tool_witness_decision`:
#       let adjudicator = require_string(args, "adjudicator")?;   <- mandatory
#       ... append_chain("policy_decision", json!({ "adjudicator": adjudicator, ...
#   daemon paths core/src/server/handler.rs  action-surface gate + `gate_direct_tool`:
#       append_chain("policy_decision", json!({ ... }))           <- key never written
#
# Measured 2026-08-26 over 8000 hops / 262 policy_decision rows: the two
# discriminators agree on every row (167 daemon+rule_id, 95 caller+blank, 0
# disagreements), and every observed adjudicator is `plugin-gate:<seat>`.
check("E1 the daemon class is defined by ABSENCE, so an unknown-shaped row lands there",
      gdrbs.producer({}) == ("daemon", "(no rule_id)"))
check("E2 any non-blank adjudicator marks the caller class, whatever its spelling",
      gdrbs.producer({"adjudicator": "some-future-gate", "reason": "x.y: z"})
      == ("gate", "x.y"))

print()
if failures:
    print(f"{len(failures)} of {checks} FAILED: {failures}")
    sys.exit(1)
print(f"ALL {checks} CHECKS PASSED")
