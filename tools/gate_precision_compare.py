#!/usr/bin/env python3
"""Score the PROPOSED resolved-act classifier against the same corpus as the live gate.

Two numbers decide whether this is an improvement, and one of them is the controls. A change
that retires every false positive and also lets one control through has made the gate worse;
in a run without controls that outcome is indistinguishable from success.
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "plugins", "_shared"))

from gate_precision_corpus import CASES, FORBIDDEN   # noqa: E402
from gate_resolved_act import forbidden_reach         # noqa: E402


def proposed(case):
    hit = forbidden_reach(case.paths, case.repos, case.command, FORBIDDEN, case.cwd)
    return ("deny", hit) if hit else ("allow", None)


def live(case):
    import hestia_gate_core as core
    ev = core.NormalizedEvent(tool=case.tool, paths=list(case.paths),
                              repos=list(case.repos), command=case.command, cwd=case.cwd)
    prof = core.HarnessProfile(member_id="corpus-probe",
                               identity_path=os.path.join(HERE, "probe-identity.json"))
    v = core.evaluate(ev, prof, workspace=os.path.expanduser("~/ai-workspace"))
    dec = getattr(v, "decision", None) or ("deny" if getattr(v, "blocks", False) else "allow")
    return dec


def main() -> int:
    scored = [c for c in CASES if c.reaches == "gate1a"]
    print(f"{len(scored)} scorable cases (the rest are annotated unreachable in the corpus)")
    print()
    print(f"{'case':44} {'want':6} {'live':6} {'proposed'}")
    print("-" * 76)

    fp_live = fp_new = 0
    fp_total = ctrl_total = ctrl_leak_live = ctrl_leak_new = 0
    regressions = []

    for c in scored:
        want = c.expect
        got_live = live(c)
        got_new, hit = proposed(c)
        flag = " " if got_new == want else "X"
        print(f"{flag}{c.name:43} {want:6} {got_live:6} {got_new}"
              + (f"   <- {hit[0]} in {hit[1]}" if hit and want == 'allow' else ""))
        if want == "allow":
            fp_total += 1
            fp_live += got_live != want
            fp_new += got_new != want
            if got_new != want:
                regressions.append(c.name)
        else:
            ctrl_total += 1
            ctrl_leak_live += got_live != want
            ctrl_leak_new += got_new != want
            if got_new != want:
                regressions.append("CONTROL LEAKED: " + c.name)

    print()
    print(f"false positives   live {fp_live}/{fp_total}   proposed {fp_new}/{fp_total}")
    print(f"controls leaked   live {ctrl_leak_live}/{ctrl_total}   proposed {ctrl_leak_new}/{ctrl_total}")
    print()
    if ctrl_leak_new:
        print("REJECT: the proposal lets a real act through. Precision bought that way is not")
        print("precision, and this is the only line in the output that can say so.")
        return 2
    if fp_new < fp_live:
        print(f"IMPROVEMENT: {fp_live - fp_new} false positive(s) retired, every control still denies.")
        return 0
    print("NO IMPROVEMENT.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
