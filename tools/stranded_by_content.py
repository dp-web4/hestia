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


_BASE_BLOBS = None


def base_blobs():
    """Every object ever reachable from BASE, as a set of sha1s.

    The obvious spelling of "did this blob ever land" is
    `git log BASE --find-object=<blob>`, one full history walk PER BLOB. On hestia that
    made a --branches sweep take minutes and get killed; an instrument nobody will wait
    for is a claim, not a tool. One `rev-list --objects` walk (3.8s, 5492 objects here)
    answers the same question for every blob at once.
    """
    global _BASE_BLOBS
    if _BASE_BLOBS is None:
        _BASE_BLOBS = {
            ln.split(None, 1)[0]
            for ln in git("rev-list", "--objects", BASE).splitlines() if ln.strip()
        }
    return _BASE_BLOBS


def cherry_landed(commit):
    """kimi's probe 1: is every patch on this head ALREADY on BASE by patch-id?

    `git cherry BASE head` marks each commit '-' when BASE already contains an
    equivalent patch and '+' when it does not. Patch-id ignores the commit hash,
    so it sees straight through the rebase/cherry-pick class -- exactly the class
    ancestry gets wrong for the same reason it gets squash-merges wrong. It does
    NOT launder squash-merges: squashing N commits into one changes the patch, so
    the parts still read '+'.

    Returns (all_landed, detail) or (None, reason) when there is nothing to compare.
    """
    out = git("cherry", BASE, commit)
    marks = [ln.split()[0] for ln in out.splitlines() if ln.strip()]
    if not marks:
        return None, "no patches to compare"
    have = marks.count("-")
    return have == len(marks), f"{have}/{len(marks)} patches already on {BASE} by patch-id"


def classify(commit):
    """Return (verdict, detail) for one commit against origin/main."""
    if is_ancestor(commit):
        return "ON-MAIN", "reachable from " + BASE

    # probe 1 (kimi, notice 1259) -- run BEFORE the path/line tests. Those tests ask
    # "is this content on main"; patch-id equality answers it outright and with less
    # inference, so letting them run first would only invite them to disagree with a
    # stronger instrument. This is the single largest correction to the sweep: it is
    # the rebase/cherry-pick class, which nothing else here could see.
    landed, cdetail = cherry_landed(commit)
    if landed:
        return "CHERRY-LANDED", cdetail

    # A merge commit has no single diff. Without -m, diff-tree prints nothing and the
    # commit would fall through to "EMPTY" -- silently untested and invisible in a sweep
    # (kimi F3, 2026-08-06). Diff against the first parent and SAY that is what happened.
    parents = git("rev-list", "--parents", "-n1", commit).split()[1:]
    nparents = len(parents)
    if nparents > 1:
        paths = git("diff-tree", "--no-commit-id", "--name-only", "-r",
                    "-m", "--first-parent", commit).split()
        merge_note = f" [merge tip, {nparents} parents, diffed vs first parent]"
    else:
        paths = git("diff-tree", "--no-commit-id", "--name-only", "-r", commit).split()
        merge_note = ""
    paths = sorted(set(paths))
    if not paths:
        return "EMPTY", "commit touches no paths" + merge_note

    # test 2 -- a path that exists on no main commit.
    # Path-absence at main's TIP is not content-absence: main may have RENAMED or DELETED
    # a file whose content did land (kimi F1). So for each absent path, ask the
    # path-independent question -- did this exact blob ever appear in main's history?
    absent = []
    relocated = []  # blob landed on BASE, just not at this path
    for p in paths:
        if subprocess.run(["git", "cat-file", "-e", f"{BASE}:{p}"],
                          capture_output=True).returncode == 0:
            continue
        blob = git("rev-parse", f"{commit}:{p}").strip()
        if blob and blob in base_blobs():
            relocated.append(p)  # content landed under some other path -- not stranded
            continue
        absent.append(p)
    if absent:
        return "STRANDED", (f"{len(absent)} added path(s) whose content is on no {BASE} "
                            f"commit (blob-level): {absent[0]}" + merge_note)

    # A relocated path must be WITHDRAWN from the line test below, not merely spared the
    # hard-positive verdict. Test 3 reads `BASE:<path>`, which is empty for a path main
    # does not carry -- so every added line would read missing and the commit would come
    # back STRANDED anyway, with a different reason and the same wrong answer. That is
    # kimi's F1 one layer down, and it is invisible on this repo because the class is
    # empty here; caseA in tools/stranded_controls.sh is the instance that shows it.
    if relocated:
        paths = [p for p in paths if p not in relocated]
        merge_note = (f" [{len(relocated)} path(s) landed under another name on {BASE}, "
                      f"withdrawn from the line test: {relocated[0]}]" + merge_note)
        if not paths:
            return "CONTENT-LANDED", (f"all {len(relocated)} path(s) landed on {BASE} under "
                                      f"another name (blob-level){merge_note}")

    # test 3 -- modify-only: are the added lines in main's version OF THE FILE THEY WERE
    # ADDED TO? Matching against the union of all touched blobs (the original) counts a
    # line added to file A as present when it merely recurs in file B -- an inflation
    # toward "landed" that is exactly backwards for a stranding test (kimi F2).
    main_blobs = {p: git("show", f"{BASE}:{p}") for p in paths}
    added = {}  # path -> set of added lines
    cur = None
    # `git show` on a merge prints a COMBINED diff (or nothing), so the +lines never
    # parse -- fixing diff-tree alone left merge tips testable for paths and silently
    # untestable for content. Diff against the first parent explicitly.
    diff_cmd = (["diff", "--unified=0", parents[0], commit] if nparents > 1
                else ["show", commit, "--unified=0", "--format="])
    for line in git(*diff_cmd).splitlines():
        if line.startswith("+++ b/"):
            cur = line[6:].strip()
            continue
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+") and cur is not None:
            s = line[1:].strip()
            if len(s) >= 12:  # short lines (braces, keywords) match anywhere
                added.setdefault(cur, set()).add(s)
    total = sum(len(v) for v in added.values())
    if not total:
        return "UNKNOWN", "no substantive added lines to test" + merge_note

    missing = 0
    cross_only = 0  # present SOMEWHERE, absent from its own file: what the pooled test hid
    for p, lines in added.items():
        own = main_blobs.get(p, "")
        for s in lines:
            if s in own:
                continue
            if any(s in b for b in main_blobs.values()):
                cross_only += 1
            missing += 1
    if missing:
        note = f" ({cross_only} of them present only in a SIBLING file)" if cross_only else ""
        return "STRANDED", f"{missing}/{total} added lines absent from their own file on {BASE}{note}{merge_note}"
    return "LIKELY-LANDED", f"all {total} added lines present in their own file on {BASE} (substring test){merge_note}"


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

    tally = {}
    for c in targets:
        verdict, detail = classify(c)
        tally[verdict] = tally.get(verdict, 0) + 1
        if verdict == "ON-MAIN":
            continue
        subject = git("log", "-1", "--format=%h %ad %s", "--date=short", c).strip()
        print(f"{verdict:14} {subject}")
        print(f"{'':14} {detail}")

    # Print the base the run was pinned to alongside the counts: the bound decays as
    # main advances, so a tally without its base is not a reproducible number.
    base_sha = git("rev-parse", "--short", BASE).strip()
    print(f"\n-- tally ({len(targets)} refs, BASE={BASE}@{base_sha}) --")
    for k in sorted(tally):
        print(f"{tally[k]:4}  {k}")


if __name__ == "__main__":
    main()
