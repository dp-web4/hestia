#!/usr/bin/env python3
"""Score the precision corpus against the LIVE gate. This is the baseline, and the meter.

Imports the law from the repo checkout and asks it about each case. Read-only with respect to
the gate: it evaluates, it never installs, deploys or edits anything.

WHAT THE NUMBERS MEAN. `false_positive_rate` is the share of harmless acts the gate refuses.
dp, 2026-09-14: friction that frustrates honest effort breeds casual bypasses. Bypass is
silent and hestia#923 documents that it works, so this number is a SECURITY metric, not an
ergonomics one — a rule whose false positives are rising is training the fleet to route
around it. `control_failures` must stay at zero: a change that buys precision by allowing a
real act has made the gate worse, and only the controls can tell those two apart.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "plugins", "_shared"))

from gate_precision_corpus import CASES  # noqa: E402


def _law():
    import hestia_gate_core as core
    return core


def verdict_for(core, case):
    """What the live gate says about one case. Returns (decision, rule, reason)."""
    ev = core.NormalizedEvent(
        tool=case.tool,
        paths=list(case.paths),
        repos=list(case.repos),
        command=case.command,
        cwd=case.cwd,
    )
    prof = core.HarnessProfile(
        member_id="corpus-probe",
        identity_path=os.path.join(HERE, "corpus-probe-identity.json"),
    )
    v = core.evaluate(ev, prof, workspace=os.path.expanduser("~/ai-workspace"))
    dec = getattr(v, "decision", None) or ("deny" if getattr(v, "blocks", False) else "allow")
    return dec, getattr(v, "rule", ""), (getattr(v, "reason", "") or "")[:70]


def main() -> int:
    core = _law()
    fp_total = fp_refused = 0
    ctrl_total = ctrl_leaked = 0
    rows = []

    unscored = []
    for c in CASES:
        if c.reaches != "gate1a":
            unscored.append(c)
            continue
        got, rule, reason = verdict_for(core, c)
        ok = (got == c.expect)
        if c.expect == "allow":
            fp_total += 1
            fp_refused += 0 if ok else 1
        else:
            ctrl_total += 1
            ctrl_leaked += 0 if ok else 1
        rows.append((ok, c, got, rule, reason))

    print("case                                          expect  got    rule")
    print("-" * 84)
    for ok, c, got, rule, reason in rows:
        mark = "  " if ok else "XX"
        print(f"{mark} {c.name:42} {c.expect:6}  {got:5}  {rule}")

    if unscored:
        print()
        print("NOT SCORED — this harness does not reach the layer that refuses them:")
        for c in unscored:
            print(f"   {c.name:42} [{c.reaches}]")
            note = c.unreachable_note or "refused at another layer"
            for k in range(0, len(note), 76):
                print(f"      {note[k:k+76]}")
    rate = (100.0 * fp_refused / fp_total) if fp_total else 0.0
    print()
    print(f"false_positive_rate : {fp_refused}/{fp_total}  ({rate:.0f}% of the harmless acts "
          f"THIS HARNESS CAN ASK ABOUT)")
    print(f"control_failures    : {ctrl_leaked}/{ctrl_total}  (must be 0 — a real act allowed)")
    print()
    if ctrl_leaked:
        print("CONTROLS LEAKED. Precision bought by allowing a real act is not precision.")
        return 2
    print("controls hold." if not ctrl_leaked else "")
    return 0 if fp_refused == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
