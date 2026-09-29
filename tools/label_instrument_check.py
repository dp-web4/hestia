#!/usr/bin/env python3
"""Is the hand label an INSTRUMENT or an opinion? Two independent checks.

`tools/peer_dissent_ground_census.py` publishes "50% of peer factors are review
of a record that did not carry the act" from a hand label. kimi-code audited all
60 concur labels from a second seat (PR #671) and disagreed on 2, both in the
same direction. That audit is an inter-rater reliability measurement and nobody
scored it as one. 56/60 = 93% raw agreement -- but 35 of 60 labels are `none`,
so two raters who both guessed the majority class would score ~58% by luck
alone. Raw agreement is the wrong statistic. Cohen's kappa is the right one.

CHECK 1 (inter-rater): kappa between my labels and kimi's, computed from the
audit's own disagreement list -- both full label vectors are recoverable because
kimi reports its labels as deltas from mine.

CHECK 2 (intra-rater): a keyword auto-labeller run over the same 60 arguments,
printing ONLY the two disagreement sets. The point is not that the regex is
right -- it is not, and it undercounts in the opposite direction from a hand
read. The point is that a hand label and a mechanical label disagreeing on a row
flags that row for re-reading, and the flagged set is small enough to read.
kimi found one intra-rater inconsistency by eye (18e0e6ba `record_qualified` vs
9f4a6d4b `none`, same reasoning verbatim). This asks how many more there are.

Usage: python3 tools/label_instrument_check.py [--max HOPS]
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from chain_walk import ChainWalker, payload  # noqa: E402
from peer_dissent_ground_census import CONCUR_LABELS, LABELS, collect  # noqa: E402

# kimi-code's second-seat audit, PR #671 comment 5438782937. Reported as deltas
# from my table: 56 of 60 agree, 2 FIRM disagreements, 2 borderline it filed but
# declined to count. Both firm relabels are `none` -> `record_recovered`.
KIMI_FIRM = {
    ("a0dc8225", "kimi-code"): "record_recovered",
    ("c44125d8", "codex"): "record_recovered",
}
KIMI_BORDERLINE = {
    ("042c34a4", "codex"): "record_recovered",
    ("e5bc6795", "claude-code"): "record_qualified",
}

# Recovery language: the peer says it OBTAINED the act from somewhere the
# escalation record is not. Qualification language: the peer says it could NOT.
RECOVER_RX = re.compile(
    r"recover|from the artifact|asker transcript|from the transcript|"
    r"byte-compare|byte compare|verified against the payload|on disk|"
    r"in the worktree|committed \w+ in|git (?:show|log|history)|"
    r"reconstruct|sibling `?outcome|different chain surface|mtime",
    re.I,
)
QUALIFY_RX = re.compile(
    r"truncat|withheld|LIMITS?:|limit(?:s)? (?:of the evidence |)stated|"
    r"cannot (?:see|review|read)|not carried|does not carry|visible (?:portion|prefix)|"
    r"unreviewable|prefix (?:only|is)|400-char|220|not content-verified|"
    r"NOT content|caveat|unseen",
    re.I,
)


def auto_label(arg: str) -> str:
    """Mechanical stand-in for the hand read. Deliberately crude."""
    if RECOVER_RX.search(arg):
        return "record_recovered"
    if QUALIFY_RX.search(arg):
        return "record_qualified"
    return "none"


def kappa(a: list[str], b: list[str]) -> tuple[float, float, float]:
    """Cohen's kappa, plus the observed and chance agreement it is built from."""
    n = len(a)
    po = sum(1 for x, y in zip(a, b) if x == y) / n
    ca, cb = Counter(a), Counter(b)
    pe = sum(ca[k] * cb[k] for k in set(ca) | set(cb)) / (n * n)
    return (po - pe) / (1 - pe) if pe < 1 else 1.0, po, pe


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=25000)
    args = ap.parse_args()

    seen, opened, hops, first, last = collect(args.max)
    print(f"walked {hops} hops, {last} -> {first}")
    concurs = {k: v for k, v in seen.items() if not v.get("dissent")}
    lab = {k: CONCUR_LABELS[k] for k in concurs if k in CONCUR_LABELS}
    print(f"concurrences: {len(concurs)}   labelled: {len(lab)}")
    if len(lab) != len(concurs):
        print(f"  WARNING {len(concurs) - len(lab)} unlabelled -- excluded")

    keys = sorted(lab)
    mine = [lab[k] for k in keys]

    # ---- CHECK 1: inter-rater kappa vs kimi-code -------------------------
    def kimi_vector(include_borderline: bool) -> list[str]:
        out = []
        for k in keys:
            short = (k[0][:8], k[1])
            v = lab[k]
            if short in KIMI_FIRM:
                v = KIMI_FIRM[short]
            elif include_borderline and short in KIMI_BORDERLINE:
                v = KIMI_BORDERLINE[short]
            out.append(v)
        return out

    print()
    print("CHECK 1 -- INTER-RATER (claude-code hand label vs kimi-code audit)")
    matched = sum(1 for k in keys if (k[0][:8], k[1]) in KIMI_FIRM)
    print(f"  firm relabels matched to live keys: {matched} of {len(KIMI_FIRM)}")
    if matched != len(KIMI_FIRM):
        print("  !! a relabel did not match a live factor -- kappa below is WRONG")
    for name, incl in (("firm only", False), ("firm+borderline", True)):
        kv = kimi_vector(incl)
        kp, po, pe = kappa(mine, kv)
        print(f"  {name:<16} agree {int(po*len(keys))}/{len(keys)}"
              f"  po={po:.3f}  pe(chance)={pe:.3f}  kappa={kp:.3f}")
    print("  Landis-Koch: >0.80 almost perfect, 0.61-0.80 substantial.")

    # ---- CHECK 2: intra-rater, hand vs mechanical ------------------------
    print()
    print("CHECK 2 -- HAND vs MECHANICAL (only the disagreements are printed)")
    auto = {k: auto_label(concurs[k].get("argument") or "") for k in keys}
    hand_record = {k for k in keys if lab[k] != "none"}
    auto_record = {k for k in keys if auto[k] != "none"}
    print(f"  hand says record-limited: {len(hand_record)} of {len(keys)}")
    print(f"  auto says record-limited: {len(auto_record)} of {len(keys)}")
    print(f"  both agree on the BOOL:   {len(hand_record & auto_record) + len(set(keys) - hand_record - auto_record)}")

    only_auto = sorted(auto_record - hand_record)
    only_hand = sorted(hand_record - auto_record)
    print()
    print(f"  SET A -- auto flags, hand said `none` ({len(only_auto)}):"
          " candidate MISSES, read these")
    for k in only_auto:
        arg = (concurs[k].get("argument") or "").replace("\n", " ")
        print(f"    {k[0][:8]} {k[1]:<12} {k[2]}  auto={auto[k]}")
        print(f"      {arg[:240]}")
    print()
    print(f"  SET B -- hand flags, auto said `none` ({len(only_hand)}):"
          " the regex's own blind spots")
    for k in only_hand:
        arg = (concurs[k].get("argument") or "").replace("\n", " ")
        print(f"    {k[0][:8]} {k[1]:<12} {k[2]}  hand={lab[k]}")
        print(f"      {arg[:160]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
