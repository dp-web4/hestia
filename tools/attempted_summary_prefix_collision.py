#!/usr/bin/env python3
"""Does the 220-char operator view name ONE act, or a class of them?

The companion census (`attempted_summary_branch_census.py`) measures how often the act is
truncated or erased before the operator ever sees it. This one asks the next question, and
it is the one that keeps the first from being overstated: when an operator approves what
they see, how many DIFFERENT commands would have rendered identically?

The honest answer, on this host, is "usually one." That bounds the claim. A head-anchored
220-char prefix is usually act-IDENTIFYING; it is never act-BINDING, because nothing carries
the rendering into the claim -- which is hestia#318, and is a separate defect from this one.

Reported because a finding that only ever comes out damning is not being measured.

Usage:  python3 tools/attempted_summary_prefix_collision.py [transcript-root]
Prints no full command text: only rendering prefixes, which are by construction what the
operator surface already shows, and only for the non-erased arm.
"""
from __future__ import annotations

import collections
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from attempted_summary_branch_census import (  # noqa: E402
    MARKER_SHAPES,
    collect_commands,
    load_enforcing_hook,
)


def report(label: str, pop: list[str], summ) -> None:
    uniq = sorted(set(pop))
    groups: dict[str, set[str]] = collections.defaultdict(set)
    for c in uniq:
        groups[summ("Bash", {"command": c})].add(c)
    colliding = {k: v for k, v in groups.items() if len(v) > 1}
    shared = sum(len(v) for v in colliding.values())
    print(f"--- {label}")
    print(f"  distinct commands             : {len(uniq)}")
    print(f"  distinct operator renderings  : {len(groups)}")
    print(f"  renderings covering >1 act    : {len(colliding)}")
    print(f"  acts sharing a rendering      : {shared} "
          f"({100 * shared / max(len(uniq), 1):.1f}%)")
    if colliding:
        k, v = max(colliding.items(), key=lambda kv: len(kv[1]))
        print(f"  worst class: {len(v)} distinct commands render as:")
        print(f"    {k[:200]}")
    print()


def main() -> int:
    root = sys.argv[1] if len(sys.argv) > 1 else os.path.expanduser("~/.claude/projects")
    mod, path = load_enforcing_hook()
    summ = mod._attempted_summary
    print(f"enforcing gate hook (per install ledger): {path}")
    print()
    cmds, nfiles = collect_commands(root)
    if not cmds:
        raise SystemExit(f"no Bash commands found under {root}; nothing to measure")
    print(f"population: {len(cmds)} Bash commands from {nfiles} transcripts")
    print()
    report("all Bash commands", cmds, summ)
    report("escalation-eligible (governance-marker-SHAPED text; proxy, not the gate's list)",
           [c for c in cmds if any(m in c for m in MARKER_SHAPES)], summ)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
