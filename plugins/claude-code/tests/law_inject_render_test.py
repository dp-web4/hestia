#!/usr/bin/env python3
"""The rendered-law shapes that review caught, asserted so they cannot come back.

kimi's review of #59 found three defects by feeding `render()` and `fetch_law()` shapes the
happy path never produces. All three were reachable, none was visible from the diff, and the
first one contradicted the PR's own central invariant. The convention this follows is
`plugins/member-mesh/tests/fire_concurrency_test.py`: assert on the REAL functions, with no
seam that exists only for the test.

WHAT THE INVARIANT IS. A failed lookup and an empty law are DIFFERENT STATES and must render
differently. "No rules resolve for this identity" is a legitimate thing to say; saying it
about a lookup that failed is a false assurance that the member is ungoverned — worse than
silence, because it gives a reason to believe.

Cases 1-3 are the failure shapes. Case 4 is the counterfactual that keeps the guard honest:
a genuine empty law must still take the empty-law branch, or the fix would have "passed" by
declaring every law a failure.

Usage: ./law_inject_render_test.py     (no daemon required — these are pure-function tests)
"""
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
HOOK = os.path.join(HERE, "..", "hooks", "law_inject.py")

spec = importlib.util.spec_from_file_location("law_inject", HOOK)
law_inject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(law_inject)

FAILURES = []
UNGOVERNED = "ungoverned by policy at this layer"


def check(name, cond, detail=""):
    print(f"  {'PASS' if cond else 'FAIL'}  {name}" + (f"  — {detail}" if detail and not cond else ""))
    if not cond:
        FAILURES.append(name)


def raises(fn):
    try:
        fn()
    except Exception as e:
        return e
    return None


print("case 1: an in-band error envelope is a FAILED LOOKUP, not an empty law")
envelope = {"_hestia_error": {"code": "hestia.operating_law_unattributed",
                              "message": "no live session"}}
err = raises(lambda: law_inject._must_be_a_law(envelope))
check("_must_be_a_law rejects an _hestia_error envelope", err is not None)
check("the refusal names the daemon's code, so the NOT LOADED text can be diagnosed",
      err is not None and "operating_law_unattributed" in str(err), str(err))
# The defect in full: had this reached render(), THIS is what the agent would have read.
check("an envelope never reaches the ungoverned sentence",
      UNGOVERNED not in law_inject.render(envelope) or err is not None)

print("case 2: an unparseable response ({} from _rpc) is a FAILED LOOKUP")
check("_must_be_a_law rejects {}", raises(lambda: law_inject._must_be_a_law({})) is not None)
check("_must_be_a_law rejects a non-dict",
      raises(lambda: law_inject._must_be_a_law("<html>502</html>")) is not None)
# Directly the trap: render({}) says you are ungoverned. That is WHY the guard is upstream.
check("render({}) alone would have claimed ungoverned — guard must be upstream, and is",
      UNGOVERNED in law_inject.render({}))

print("case 3: a literal pipe in law text does not break the table")
piped = {"identity": {"plugin_id": "claude-code", "role": "role:constellation:member"},
         "law_hash": "abc123", "layers": ["society"], "lists_bound": [],
         "law": [{"decision": "allow",
                  "law": "rm is PERMITTED alone: no &&, ;, |, newline or $(...) alongside it"}]}
row = [ln for ln in law_inject.render(piped).splitlines() if ln.startswith("| **allow**")][0]
check("the law's own pipe is escaped", "\\|" in row, row)
check("the row still has exactly 2 columns",
      len([c for c in row.split("|") if c.strip()]) == 2 or row.count("|") - row.count("\\|") == 3,
      f"unescaped separators: {row.count('|') - row.count(chr(92) + '|')} (want 3) :: {row}")
check("the law text survives escaping intact",
      "newline" in row and "PERMITTED" in row, row)
check("the column header names what the column holds",
      "| decision | law text |" in law_inject.render(piped))

print("case 4: COUNTERFACTUAL — a genuine empty law must still say so")
empty = {"identity": {"plugin_id": "claude-code", "role": "role:constellation:member"},
         "law_hash": "abc123", "layers": [], "lists_bound": [], "law": []}
check("_must_be_a_law lets a real empty law through",
      raises(lambda: law_inject._must_be_a_law(empty)) is None)
check("and it renders as the explicit empty law", UNGOVERNED in law_inject.render(empty))
check("...distinguishably from a failure, which says NOT LOADED instead",
      "NOT LOADED" not in law_inject.render(empty))

print("case 5: the budget is a whole-run deadline, not a per-call allowance")
check("TOTAL_BUDGET is under the settings.json timeout of 5s",
      law_inject.TOTAL_BUDGET < 5.0, f"TOTAL_BUDGET={law_inject.TOTAL_BUDGET}")
law_inject._DEADLINE = law_inject.time.monotonic() - 1.0  # already spent
check("an exhausted deadline raises rather than blocking forever",
      isinstance(raises(law_inject._remaining), TimeoutError))
law_inject._DEADLINE = law_inject.time.monotonic() + 10.0
check("a live deadline never yields a non-positive urlopen timeout",
      law_inject._remaining() >= law_inject._MIN_SLICE)
law_inject._DEADLINE = None

print()
if FAILURES:
    print(f"FAILED ({len(FAILURES)}): " + ", ".join(FAILURES))
    sys.exit(1)
print("all green")
