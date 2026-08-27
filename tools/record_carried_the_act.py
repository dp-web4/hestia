#!/usr/bin/env python3
"""Did the RECORD carry the act? Measured, not hand-labelled.

`tools/peer_dissent_ground_census.py` decides `record_recovered` vs `none` by
reading what the PEER said it did. That is a rater judgment, and PR #671's
second-seat audit plus `tools/label_instrument_check.py` both show the errors
run one direction: every disagreement is a `none` that might be a recovery, and
the opposite set is empty.

The judgment is avoidable. Whether a peer COULD have reviewed the act from the
escalation record is a property OF THE RECORD, readable off the chain:

    gate_escalation_opened.stated_reason

carries the act (or does not). Classify that field instead of the peer's prose:

  FULL       the reason carries a complete-looking act
  TRUNCATED  the reason is cut mid-act -- the hook truncates `stated_reason`,
             so the tail is unreviewable by anyone (codex's standing dissent on
             4c534379b7db7768: "visible prefix read-only but tail unreviewable")
  MARKER     no act at all -- a destination path and a rule name, the write-class
             shape from #616
  ABSENT     no stated_reason on the opened row

A peer that filed a CONTENT judgment on a TRUNCATED, MARKER or ABSENT record
necessarily obtained the act somewhere else, whether or not it said so. That is
`record_recovered` by the census file's own definition, established without
asking the rater anything.

Usage: python3 tools/record_carried_the_act.py [--max HOPS]
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter

sys.path.insert(0, __file__.rsplit("/", 1)[0])
from chain_walk import ChainWalker, payload  # noqa: E402
from peer_dissent_ground_census import CONCUR_LABELS, LABELS  # noqa: E402

# The hook cuts `stated_reason` at `pre_tool_use.py:2057`:
#     return f"{tool_name}: {s[:220]}" + (" …" if len(s) > 220 else "")
# "Bash: " (6) + 220 + " …" (2) = 228, which is exactly the observed length of
# every truncated record in the window, with zero variance.
#
# BUT THAT IS NOT THE ONLY PRODUCER. 38 of the 87 peer-reviewed escalations in
# the window carry a `stated_reason` with NO `tool_name:` prefix -- the bare
# command (`sleep …`, `cd …`, `for …`) up to 412 chars, or a bare destination
# PATH and nothing else. That second producer does not truncate, and the bare
# path carries no act at all (#616's write-class shape). A classifier that only
# looks for the ellipsis scores both of those as FULL and undercounts.
ELLIPSIS = "…"


def classify(reason: str | None) -> tuple[str, int]:
    """What the record carries. Not what the peer said it did."""
    if not reason:
        return "ABSENT", 0
    r = reason.strip()
    n = len(r)
    if "[REDACTED" in r:
        # `_credential_shaped` withheld the act rather than copy it into the
        # chain. Deliberate, and it leaves the peer nothing to review.
        return "REDACTED", n
    if r.endswith(ELLIPSIS) or r.endswith("..."):
        return "TRUNCATED", n
    # A bare destination path and nothing else: no verb, no arguments, no
    # command. The write-class record shape (#616).
    body = r.split(": ", 1)[1] if re.match(r"^[A-Z][A-Za-z]*: ", r) else r
    if " " not in body.strip() and body.strip().startswith("/"):
        return "MARKER", n
    return "FULL", n


def collect(max_entries: int):
    walker = ChainWalker()
    factors, reasons, hops = {}, {}, 0
    first = last = None
    for entry in walker.walk(max_entries=max_entries):
        hops += 1
        ts = entry.get("timestamp")
        if first is None:
            first = ts
        last = ts
        data = payload(entry) or {}
        if not isinstance(data, dict):
            continue
        eid = data.get("escalation_id")
        if entry.get("eventType") == "gate_escalation_opened":
            # keep the FIRST-seen (walk runs tip->old, so the last write wins
            # the oldest; either is the same row for a given id)
            reasons[eid] = data.get("stated_reason")
        fs = data.get("factors_present")
        if not isinstance(fs, list):
            continue
        for f in fs:
            if f.get("channel") == "peer_member":
                factors[(eid, f.get("by"), f.get("at"))] = f
    return factors, reasons, hops, first, last


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=25000)
    args = ap.parse_args()
    factors, reasons, hops, first, last = collect(args.max)
    print(f"walked {hops} hops, {last} -> {first}")

    esc = {k[0] for k in factors}
    have = [e for e in esc if e in reasons]
    print(f"escalations drawing a peer factor: {len(esc)}"
          f"   with an `opened` row in window: {len(have)}")
    if len(have) < len(esc):
        print(f"  {len(esc) - len(have)} opened BEFORE the window -- excluded,"
              " not folded in as ABSENT")

    kinds = {e: classify(reasons[e]) for e in have}
    print()
    print("WHAT THE RECORD CARRIES (escalations that drew peer review):")
    c = Counter(k for k, _ in kinds.values())
    for kind, n in c.most_common():
        print(f"  {kind:<10} {n:>3}   {100.0*n/len(have):.0f}%")
    unreviewable = sum(n for k, n in c.items() if k != "FULL")
    print(f"  -> {unreviewable} of {len(have)}"
          f" ({100.0*unreviewable/len(have):.0f}%) cannot be reviewed"
          " from the record alone.")

    lens = sorted(n for k, n in kinds.values() if k == "TRUNCATED")
    if lens:
        print(f"  TRUNCATED lengths: min={lens[0]} max={lens[-1]}"
              f" distinct={len(set(lens))}  {sorted(set(lens))[:12]}")

    # ---- cross-tab: the hand label against the record's own shape --------
    print()
    print("HAND LABEL vs WHAT THE RECORD CARRIED (concurrences only):")
    rows = Counter()
    misses = []
    for k, f in factors.items():
        if f.get("dissent") or k[0] not in kinds:
            continue
        lab = CONCUR_LABELS.get(k)
        if lab is None:
            continue
        kind = kinds[k[0]][0]
        rows[(lab, kind)] += 1
        if lab == "none" and kind != "FULL":
            misses.append((k, kind, f))
    labs = ["none", "record_qualified", "record_recovered"]
    kindnames = ["FULL", "TRUNCATED", "MARKER", "ABSENT"]
    print(f"  {'':<18}" + "".join(f"{x:>10}" for x in kindnames))
    for lab in labs:
        print(f"  {lab:<18}" + "".join(f"{rows[(lab,x)]:>10}" for x in kindnames))

    print()
    print(f"STRUCTURAL MISSES -- labelled `none`, record could NOT carry the act"
          f" ({len(misses)}):")
    for k, kind, f in sorted(misses, key=lambda t: t[0][2]):
        arg = (f.get("argument") or "").replace("\n", " ")
        print(f"  {k[0][:8]} {k[1]:<12} {k[2]}  record={kind}")
        print(f"    reason: {(reasons[k[0]] or '')[:150]!r}")
        print(f"    factor: {arg[:150]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
