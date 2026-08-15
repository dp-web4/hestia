#!/usr/bin/env python3
"""The census's `peer-clearable` bucket must read BOTH production clauses.

WHY THIS FILE EXISTS. codex's refutation-first review of PR #455 confirmed the
finding and then found the instrument weaker than the claim it printed: the census
labelled a row peer-clearable from `bar` alone, while production refuses the peer
path first on `asker_basis`. The measured count was right by accident — the live
intersection was 31/31 session — and an accident is not a guard. This test is the
guard, and it FIRES: every clause below is asserted against the shipped `bucket()`,
so the instrument proves the claim it prints instead of restating it in a comment.

The predicate under test, transcribed from the two production constructs rather
than paraphrased:

  core/src/arbiter.rs `eligibility_for` clause 0
      appellant_basis == Asserted  =>  Eligibility::Refused, BEFORE any bar test.
      "The sovereign channels do not rely on NOT-SAME and can still decide."
  core/src/server/gate_escalation.rs `bar_met`
      SingleApprover is satisfied by a lone PeerMember factor;
      SovereignPlusPeer is not.

So peer-clearable == (bar single_approver) AND (asker_basis session). Anything
else is sovereign load or an unknown, and an unknown must not be folded into
either — pre-cutover `gate_escalation_opened` payloads carry no `asker_basis`
(0 of 362 measured), so a default here would silently invent a population.
"""
from __future__ import annotations

import sys

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from sovereign_load_census import bucket  # noqa: E402

CASES = [
    # (bar, asker_basis, expected bucket, why)
    ("single_approver", "session", "peer-clearable",
     "the only shape a live peer can actually clear"),
    ("single_approver", "asserted", "sovereign-only (asserted asker)",
     "clause 0 refuses NOT-SAME outright — no peer door at ANY bar"),
    ("single_approver", "unstated", "single_approver, basis unstated",
     "pre-cutover payload: the instrument cannot tell, and says so"),
    ("sovereign_plus_peer", "session", "sovereign-only",
     "bar_met needs a sovereign channel factor; a proven asker does not change it"),
    ("sovereign_plus_peer", "asserted", "sovereign-only",
     "both clauses point the same way; still one bucket, not a compound"),
    ("sovereign_plus_peer", "unstated", "sovereign-only",
     "basis cannot rescue this bar, so an absent basis changes nothing here"),
    ("unstated", "session", "unstated-bar",
     "no bar in the payload is its own answer, never a default to the cheap one"),
    ("some_future_bar", "session", "unstated-bar",
     "a bar this instrument has never seen must not read as peer-clearable"),
]


def main():
    failures = []
    for bar, basis, want, why in CASES:
        got = bucket({"bar": bar, "asker_basis": basis})
        ok = got == want
        print(f"{'PASS' if ok else 'FAIL'}  ({bar}, {basis}) -> {got!r}")
        print(f"        {why}")
        if not ok:
            failures.append(f"({bar}, {basis}): want {want!r}, got {got!r}")

    # A missing key is not the same as the string "unstated" — the row builder
    # always sets it, but `bucket()` is now importable, so a future caller may not.
    got = bucket({"bar": "single_approver"})
    ok = got == "single_approver, basis unstated"
    print(f"{'PASS' if ok else 'FAIL'}  absent asker_basis key -> {got!r}")
    print("        an omitted field fails closed, exactly like an unstated one")
    if not ok:
        failures.append(f"absent key: got {got!r}")

    # THE NEGATIVE THAT MATTERS. Only one of the eight shapes may be counted as
    # peer-clearable; if a later edit widens the bucket, this catches it even when
    # every positive case above still passes.
    clearable = [(b, ab) for b, ab, _, _ in CASES
                 if bucket({"bar": b, "asker_basis": ab}) == "peer-clearable"]
    if clearable != [("single_approver", "session")]:
        failures.append(f"peer-clearable widened to {clearable}")
    print(f"{'PASS' if not clearable[1:] else 'FAIL'}  exactly one shape is "
          f"peer-clearable: {clearable}")

    if failures:
        print(f"\nFAILED {len(failures)}:")
        for f in failures:
            print(f"  {f}")
        return 1
    print(f"\n{len(CASES) + 2} passed, 0 failed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
