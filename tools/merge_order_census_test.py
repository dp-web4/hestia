#!/usr/bin/env python3
"""Pins the one claim `merge_order_census.replay` exists to make.

The claim: PAIRWISE-clean does not imply SEQUENTIALLY landable, and the census
can tell the two blocking reasons apart.  Both arms are built here from scratch
in a throwaway repo, so the test needs no network, no `gh`, and no hestia state.

Arm A (sibling collision) is the load-bearing one: two branches that BOTH merge
cleanly onto main on their own, where landing either one blocks the other.  If
`replay` ever reported that as `against: base`, or silently landed both, the
tool's headline would be false and this arm goes red.

Arm B (stale vs base) is the control: a branch that conflicts with main itself.
GitHub already reports this case, so it is NOT the finding -- it is here to prove
the classifier discriminates rather than labelling every failure "sibling".

Arm C is the negative control: three branches touching disjoint files all land,
so a green in A/B is not just "replay blocks everything".
"""
from __future__ import annotations

import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from merge_order_census import replay  # noqa: E402


def git(repo, *args):
    p = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    if p.returncode != 0:
        raise SystemExit(f"git {' '.join(args)} failed in {repo}: {p.stderr}")
    return p.stdout


def write(repo, name, text):
    with open(os.path.join(repo, name), "w") as fh:
        fh.write(text)


def build_repo():
    repo = tempfile.mkdtemp(prefix="moc-test-")
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "test")
    write(repo, "guard.txt", "line1\nSHARED\nline3\n")
    write(repo, "other.txt", "a\n")
    write(repo, "third.txt", "a\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", "base")

    # Two rewrites of the SAME line: each is clean against main, together they are not.
    for branch, text in (("sib-a", "line1\nA-DESIGN\nline3\n"),
                         ("sib-b", "line1\nB-DESIGN\nline3\n")):
        git(repo, "checkout", "-q", "-b", branch, "main")
        write(repo, "guard.txt", text)
        git(repo, "commit", "-qam", branch)

    # A branch that conflicts with main itself: main moves under it.
    git(repo, "checkout", "-q", "-b", "stale", "main")
    write(repo, "other.txt", "stale-edit\n")
    git(repo, "commit", "-qam", "stale")
    git(repo, "checkout", "-q", "main")
    write(repo, "other.txt", "main-moved\n")
    git(repo, "commit", "-qam", "main moves")

    # Disjoint branch: nothing else touches third.txt.
    git(repo, "checkout", "-q", "-b", "disjoint", "main")
    write(repo, "third.txt", "disjoint\n")
    git(repo, "commit", "-qam", "disjoint")
    git(repo, "checkout", "-q", "main")
    return repo


def main():
    repo = build_repo()
    failures = []

    # Precondition for arm A: each sibling really is pairwise-clean against main.
    for b in ("sib-a", "sib-b"):
        landed, blocked = replay(repo, "main", [(b, b)])
        if landed != [b] or blocked:
            failures.append(f"precondition: {b} is not pairwise-clean against main")

    # Arm A -- the finding.
    landed, blocked = replay(repo, "main", [("a", "sib-a"), ("b", "sib-b")])
    if landed != ["a"]:
        failures.append(f"arm A: expected only 'a' to land, got {landed}")
    if [x["key"] for x in blocked] != ["b"]:
        failures.append(f"arm A: expected 'b' blocked, got {blocked}")
    elif blocked[0]["against"] != "sibling":
        failures.append(f"arm A: 'b' must be blocked by a SIBLING, got {blocked[0]['against']}")
    elif blocked[0]["files"] != ["guard.txt"]:
        failures.append(f"arm A: wrong conflict files {blocked[0]['files']}")

    # Arm A, reversed: the exclusion is a property of the SET, not of the order.
    landed, blocked = replay(repo, "main", [("b", "sib-b"), ("a", "sib-a")])
    if landed != ["b"] or [x["key"] for x in blocked] != ["a"]:
        failures.append(f"arm A reversed: expected b lands / a blocked, got {landed} {blocked}")

    # Arm B -- the control the classifier must NOT call a sibling collision.
    landed, blocked = replay(repo, "main", [("s", "stale")])
    if landed or [x["key"] for x in blocked] != ["s"]:
        failures.append(f"arm B: expected 'stale' blocked alone, got {landed} {blocked}")
    elif blocked[0]["against"] != "base":
        failures.append(f"arm B: must be blocked by the BASE, got {blocked[0]['against']}")

    # Arm C -- negative control: replay does not block what does not collide.
    landed, blocked = replay(repo, "main", [("a", "sib-a"), ("d", "disjoint")])
    if landed != ["a", "d"] or blocked:
        failures.append(f"arm C: disjoint branches must both land, got {landed} {blocked}")

    if failures:
        for f in failures:
            print("FAIL:", f)
        return 1
    print("ALL CHECKS PASSED (arms: sibling collision, reversed, stale-vs-base, disjoint)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
