#!/usr/bin/env python3
"""How much of the escalation backlog is governance DISCUSSION refused as governance MODIFICATION?

WHY. Writing reply-2606 minted escalation `b2ac2bf61477b3df` — a `git commit -F -` whose
heredoc body discusses the gate. The heredoc makes the command unparseable, so the closure
falls back to a substring scan over the WHOLE command text, and the commit *message* carries
the marker. Nothing governed was going to be written. The same wake's `claimable.py --all`
counted 50 undecided rows. The obvious question: what share of that backlog is the forum
describing the gate rather than anyone touching it?

WHAT THIS READS. `gate_escalation_opened` rows in the chain window. `stated_reason` is the
command text — TRUNCATED AT INTAKE at ~200 chars, mid-token, which is a defect ruled on
elsewhere and here is a measurement bias: a command whose governed path sits past the cut is
invisible to every bucket below. Every count is therefore a LOWER bound on `governed` and an
UPPER bound on `discussion`.

THE CONTROL, and read this before the numbers. Two rows from the wake that wrote this file
have known ground truth:

  * `b2ac2bf61477b3df` — a commit of prose. TRUE discussion. Must land in `discussion`.
  * `2470e6fc84eacca1` — `git apply -F3 remedy6.patch`, which really does rewrite
    `plugins/_shared/hestia_governance_closure.py`. TRUE modification. Must land in
    `governed`.

The second one CANNOT land in `governed`, and that is not a bug in this file. Its
`stated_reason` is `Bash: git -C <dir> apply -F3 remedy6.patch` — the governed path appears
nowhere, because the gate refused it under the `governance-closure-opaque-writer` arm, which
fires on the CLASS OF TOOL and never resolves a destination. So the designed control fails,
and its failure is the result: **the record of a refused write does not, in general, name
what would have been written.** Any classifier over this corpus — this one, a reviewer's
eye, a peer deciding whether to approve — is reading the command someone typed, not the act.
Report the buckets as a description of the RECORD, never of the acts.
"""
from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict

sys.path.insert(0, "tools")
from chain_walk import ChainWalker, payload  # noqa: E402

# Ordered: first match wins, so put the unambiguous-modification patterns first.
BUCKETS = [
    ("governed", re.compile(
        r"plugins/_shared/|hestia_governance_closure|hestia_gate|/hooks/|\.claude/hooks|"
        r"pre_tool_use|hestia_gate_mechanism", re.I)),
    ("discussion", re.compile(r"forum/|\.md\b|git commit|docs/|README", re.I)),
    ("instrument", re.compile(r"\btools/|\btests?/|\.py\b|cargo ", re.I)),
]


def bucket(reason: str) -> str:
    for name, rx in BUCKETS:
        if rx.search(reason or ""):
            return name
    return "other"


def main() -> int:
    walker = ChainWalker()
    opened, decided, claimed = {}, set(), set()
    for entry in walker.walk(max_entries=20000):
        et = entry.get("eventType") or entry.get("event_type")
        p = payload(entry)
        eid = p.get("escalation_id")
        if not eid:
            continue
        if et == "gate_escalation_opened":
            opened[eid] = p
        elif et == "gate_escalation_decided":
            decided.add(eid)
        elif et == "gate_escalation_claimed":
            claimed.add(eid)

    by_bucket = Counter()
    undecided_by_bucket = Counter()
    truncated = 0
    examples = defaultdict(list)
    for eid, p in opened.items():
        reason = p.get("stated_reason", "")
        if reason.endswith("…") or "…" in reason:
            truncated += 1
        b = bucket(reason)
        by_bucket[b] += 1
        if eid not in decided:
            undecided_by_bucket[b] += 1
        if len(examples[b]) < 2:
            examples[b].append((eid, reason[:110]))

    print(f"population: {len(opened)} gate_escalation_opened rows in the chain window")
    print(f"  of which decided: {len(opened & decided.__class__(opened.keys()) & decided) if False else len([e for e in opened if e in decided])}"
          f", claimed: {len([e for e in opened if e in claimed])}")
    print(f"  stated_reason visibly truncated at intake: {truncated}"
          f"  <- every bucket below is blind past the cut\n")
    print(f"{'bucket':<12}{'opened':>8}{'undecided':>11}")
    for b in ("governed", "discussion", "instrument", "other"):
        print(f"{b:<12}{by_bucket[b]:>8}{undecided_by_bucket[b]:>11}")

    print("\ncontrol rows (ground truth known from the authoring wake):")
    for eid, want in (("b2ac2bf61477b3df", "discussion"), ("2470e6fc84eacca1", "governed")):
        p = opened.get(eid)
        if not p:
            print(f"  {eid}  ABSENT from the window")
            continue
        got = bucket(p.get("stated_reason", ""))
        verdict = "OK" if got == want else "FAILS"
        print(f"  {eid}  want={want:<10} got={got:<10} {verdict}")
        print(f"      stated_reason: {p.get('stated_reason','')[:150]}")
    print("\n  A FAILING control here is the finding, not a bug: see the module docstring.")

    print("\nexamples per bucket:")
    for b in ("governed", "discussion", "instrument", "other"):
        for eid, r in examples[b]:
            print(f"  [{b}] {eid} {r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
