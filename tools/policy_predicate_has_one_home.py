#!/usr/bin/env python3
"""A policy predicate must have ONE implementation. This pins the one that went wrong.

WHY THIS EXISTS
---------------
`bar_met`'s `SovereignPlusPeer` arm required a peer factor until `9d3936d` (2026-08-06)
made the peer conjunct evidence rather than a gate. Two other places had written the old
rule down in their own words:

  - `handler.rs`, `esc.bar == Bar::SovereignPlusPeer` gating an invitation — found and
    corrected 2026-08-16, ten days later, and the correction survives only as a comment.
  - `dashboard.rs`, `f.channel == Channel::PeerMember` deciding whether to tell the
    operator "YOUR APPROVAL ALONE WILL NOT PERMIT THIS" — found 2026-08-31, TWENTY-FIVE
    days later, having asserted the opposite of the code it described the whole time.

Both were restatements: an `==` against a policy enum, outside the module that owns the
predicate, answering a question the predicate already answers. The remedy landed with the
second one is `Escalation::bar_met_over` — one evaluator, with `bar_met()` and
`operator_alone_suffices()` as two questions asked of it. This guard keeps a third
restatement from being written.

WHAT IT CHECKS, AND WHAT IT CANNOT
----------------------------------
Checks: no equality comparison against `Bar::*` or `Channel::*` outside
`core/src/server/gate_escalation.rs`. Construction (`Channel::OperatorSession` passed to
`decide`) is untouched — building a value is not deciding with one.

Cannot check: a restatement written as a `match`, a `matches!`, or in English prose. The
`match (esc.bar, ...)` in `handler.rs` that explains INVITATION is legitimate and stays.
So this is a floor on one syntactic form, not a proof that the rule has one home. It is
pinned anyway because it is the exact form that produced both known instances, it costs
one grep, and its allowlist is EMPTY -- a guard with no exceptions is one nobody has to
maintain a story about.
"""
import re, subprocess, sys, pathlib

OWNER = "core/src/server/gate_escalation.rs"
ROOT = pathlib.Path(__file__).resolve().parent.parent
# `x == Bar::Y`, `Bar::Y == x`, with or without a path qualifier, on either side.
PAT = re.compile(r"(==|!=)\s*(?:[\w:]*::)?(Bar|Channel)::\w+"
                 r"|(?:[\w:]*::)?(Bar|Channel)::\w+\s*(==|!=)")

def main():
    files = subprocess.run(["git", "-C", str(ROOT), "ls-files", "core/src/**/*.rs"],
                           capture_output=True, text=True, check=True).stdout.split()
    hits = []
    for f in files:
        if f == OWNER:
            continue
        for i, line in enumerate(( ROOT / f).read_text(errors="replace").splitlines(), 1):
            code = line.split("//", 1)[0]          # a comment quoting the old rule is a RECORD
            if PAT.search(code):
                hits.append(f"{f}:{i}: {line.strip()}")
    if hits:
        print(f"POLICY PREDICATE RESTATED OUTSIDE {OWNER} -- {len(hits)} site(s):")
        for h in hits:
            print("  " + h)
        print("\nAsk the predicate instead of re-deriving it. `Escalation::bar_met_over` is\n"
              "the evaluator; `bar_met()` and `operator_alone_suffices()` are questions put\n"
              "to it. If you need a THIRD question, add a third method there.")
        return 1
    print(f"policy predicates have one home: 0 restatements across {len(files)} rust files")
    return 0

if __name__ == "__main__":
    sys.exit(main())
