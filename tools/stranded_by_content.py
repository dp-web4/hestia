#!/usr/bin/env python3
"""Is a commit's content actually on origin/main?

Three tests, in increasing order of what they can prove:

  1. ancestry   `git merge-base --is-ancestor C origin/main`
                OVER-REPORTS. A squash-merged branch is not an ancestor of
                main even though every line of it landed. Measured here on
                hestia: 75 heads fail this test; most are squash-merges or
                stale June snapshots that main has since moved past.

  2. added-file A file ADDED by the branch that exists on NO main commit is
                decisive: a new path cannot be "superseded". Hard positive.
                BLIND to modify-only commits -- 44/75 = 59% of hestia's
                stranded heads add no files at all, including d035300 and
                8419240, the two commits notice 1252 was about.

  3. added-line For a modify-only commit, ask whether its added lines appear
                in main's version of the files it touched. This is the test
                that settles the modify-only case.

Test 3 is a substring check, not a diff: it can be fooled by a line that
recurs elsewhere in the file (inflating "present", i.e. erring toward
"landed"). It is therefore a LOWER bound on what is missing. Read a high
`missing` as proof of stranding; do not read a low `missing` as proof of
landing.

MAGNITUDE IS THE DISCRIMINATOR, and test 3 cannot tell "my line never
landed" from "my line landed and was later edited". Both print as missing.
Measured: d035300 (today) reports 214/216 -- stranded. 012efff (a week old,
PR merged) reports 1/62, and that one line is a test call whose signature
main has since changed: the branch is BEHIND main, not ahead of it. So a
near-total miss on a recent commit is stranding; a handful of missing lines
on an older branch is drift. Between those, this tool does not decide --
check whether the branch's merge-base is recent before believing it.

Usage:  stranded_by_content.py [commit ...]        # default: HEAD
        stranded_by_content.py --branches          # sweep all local heads
"""
import subprocess
import sys

BASE = "origin/main"


def git(*args):
    return subprocess.run(
        ["git", *args], capture_output=True, text=True
    ).stdout


def is_ancestor(commit, base=BASE):
    return subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, base],
        capture_output=True,
    ).returncode == 0


def classify(commit):
    """Return (verdict, detail) for one commit against origin/main."""
    if is_ancestor(commit):
        return "ON-MAIN", "reachable from " + BASE

    paths = git("diff-tree", "--no-commit-id", "--name-only", "-r", commit).split()
    if not paths:
        return "EMPTY", "commit touches no paths"

    # test 2 -- a path that exists on no main commit
    absent = [
        p for p in paths
        if subprocess.run(
            ["git", "cat-file", "-e", f"{BASE}:{p}"], capture_output=True
        ).returncode != 0
    ]
    if absent:
        return "STRANDED", f"{len(absent)} added path(s) absent from {BASE}: {absent[0]}"

    # test 3 -- modify-only: are the added lines in main's version?
    main_blobs = {p: git("show", f"{BASE}:{p}") for p in paths}
    added = set()
    for line in git("show", commit, "--unified=0", "--format=").splitlines():
        if line.startswith("+") and not line.startswith("+++"):
            s = line[1:].strip()
            if len(s) >= 12:  # short lines (braces, keywords) match anywhere
                added.add(s)
    if not added:
        return "UNKNOWN", "no substantive added lines to test"

    missing = sum(1 for s in added if not any(s in b for b in main_blobs.values()))
    if missing:
        return "STRANDED", f"{missing}/{len(added)} added lines absent from {BASE}"
    return "LIKELY-LANDED", f"all {len(added)} added lines present in {BASE} (substring test)"


def main():
    args = sys.argv[1:]
    if args and args[0] == "--branches":
        heads = [
            ln.split()[0]
            for ln in git("for-each-ref", "--format=%(objectname:short) %(refname:short)",
                          "refs/heads").splitlines() if ln.strip()
        ]
        targets = heads
    else:
        targets = args or ["HEAD"]

    for c in targets:
        verdict, detail = classify(c)
        if verdict == "ON-MAIN":
            continue
        subject = git("log", "-1", "--format=%h %ad %s", "--date=short", c).strip()
        print(f"{verdict:14} {subject}")
        print(f"{'':14} {detail}")


if __name__ == "__main__":
    main()
