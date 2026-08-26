#!/usr/bin/env python3
"""Pins for the recording census — the classifier and the two refusal arms.

The arms that matter are the NEGATIVE ones. A census that names a seat whenever it
sees no rows will name every seat on a short walk, publishing a fleetwide hole that
a longer walk refutes; and a classifier keyed on `rule_id` alone reports the whole
in-process class as absent, which is how a wrong absence got published once already.
So: A pins the classifier on both sides, B pins that the census refuses to name
anybody without a positive control, and C pins that it refuses to name a seat that
recorded nothing at all.

The daemon is not touched. Every arm runs against synthetic counters, so this is a
test of the JUDGEMENT, not of the chain.

Usage: ./gate_decision_recording_by_seat_test.py     (runtime <1s)
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


def check(label, ok, detail=""):
    print(("  ok   " if ok else "  FAIL ") + label + ("" if ok else f"  <- {detail}"))
    if not ok:
        failures.append(label)


def survey_of(rows):
    """Build the shape survey() returns, from (seat, decision, rule_id, reason)."""
    r = {"hops": 8000, "oldest": "2026-08-26T00:00:00Z", "newest": "2026-08-26T15:00:00Z",
         "rows": collections.Counter(), "seat_class": collections.Counter(),
         "seat_cat": collections.defaultdict(collections.Counter)}
    for seat, decision, rule_id, reason in rows:
        kind, cat = gdrbs.category({"rule_id": rule_id, "reason": reason})
        r["rows"][(seat, decision, kind, cat)] += 1
        r["seat_class"][(seat, kind)] += 1
        if kind == "gate":
            r["seat_cat"][seat][cat] += 1
    return r


def render(r):
    lines = []
    gdrbs.report(r, out=lines.append)
    return "\n".join(lines)


print("\nA. the classifier — rule_id decides the class, reason names the category")
check("A1 a non-blank rule_id is a PRESET decision",
      gdrbs.category({"rule_id": "warn-network", "reason": "Network access flagged"})
      == ("preset", "warn-network"))
check("A2 a blank rule_id is an IN-PROCESS decision, named from reason",
      gdrbs.category({"rule_id": "", "reason": "mrh.command: not granted"})
      == ("gate", "mrh.command"))
check("A3 a MISSING rule_id key is in-process too, not a crash",
      gdrbs.category({"reason": "egress.secret: forbidden path"})
      == ("gate", "egress.secret"))
# The whole first token, not its prefix: two different checks share `mrh.` and only
# one of them may have a control in a given window.
check("A4 mrh.command and mrh.path do NOT collapse into one category",
      gdrbs.category({"rule_id": "", "reason": "mrh.command: x"})
      != gdrbs.category({"rule_id": "", "reason": "mrh.path: y"}))
check("A5 whitespace-only rule_id counts as blank, not as a preset named ' '",
      gdrbs.category({"rule_id": "   ", "reason": "gate.degraded"})
      == ("gate", "gate.degraded"))
check("A6 a blank rule_id AND a blank reason is named, never dropped",
      gdrbs.category({"rule_id": "", "reason": ""}) == ("gate", "(blank)"))

print("\nB. no positive control -> name nobody")
out = render(survey_of([
    ("claude-code", "warn", "warn-network", "Network access flagged"),
    ("kimi-code", "warn", "warn-file-delete", "File deletion flagged"),
]))
check("B1 says the window is uninformative", "UNINFORMATIVE" in out, out)
check("B2 does NOT name a seat", "claude-code" not in out.split("UNINFORMATIVE")[1], out)
check("B3 does NOT assert a hole", "hole" not in out.lower(), out)
check("B4 tells the reader to walk further", "Walk further" in out, out)

print("\nC. control fired -> name the seat, and only the right one")
out = render(survey_of(
    [("claude-code", "warn", "warn-network", "Network access flagged")] * 3
    + [("kimi-code", "deny", "", "mrh.command: not granted")] * 2
    + [("kimi-code", "deny", "", "egress.secret: forbidden path")]
    + [("codex", "deny", "", "gate.degraded")]))
check("C1 names the silent seat", "ZERO in-process ones: claude-code" in out, out)
check("C2 names the seats the control fired on",
      "control fired in the same window on: codex, kimi-code" in out, out)
check("C3 lists the control categories with counts",
      "mrh.command(2)" in out and "egress.secret(1)" in out, out)
check("C4 states the consequence, not just the count",
      "hestia_appeal" in out and "unreachable" in out, out)

print("\nC'. a seat that recorded NOTHING is not named — that is a claim about the window")
out = render(survey_of(
    [("kimi-code", "deny", "", "mrh.command: not granted")] * 2
    + [("kimi-code", "warn", "warn-file-delete", "File deletion flagged")]))
check("C5 a seat absent from the window entirely cannot be named",
      "codex" not in out, out)
check("C6 with every active seat recording in-process rows, no hole is claimed",
      "No recording hole visible" in out, out)

print("\nD. the tool the census replaces would have keyed on rule_id")
# Not a behaviour of this module — a pin on WHY the classifier is shaped this way.
# If someone reintroduces a rule_id histogram, this is the number it would print.
rows = ([("kimi-code", "deny", "", "mrh.command: x")] * 20
        + [("kimi-code", "deny", "", "egress.secret: y")] * 13)
r = survey_of(rows)
check("D1 33 in-process rows carry NO rule_id, so a rule_id census sees none of them",
      r["seat_class"][("kimi-code", "gate")] == 33
      and r["seat_class"][("kimi-code", "preset")] == 0)

print()
if failures:
    print(f"{len(failures)} FAILURE(S): {failures}")
    sys.exit(1)
print("ALL CHECKS PASSED")
