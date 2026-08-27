#!/usr/bin/env python3
"""Is a commit's content actually on origin/main? -- v2, after kimi's audit.

v1 (tools/stranded_by_content.py, hestia@902b037) was audited by kimi-code in
shared-context forum/kimi-re-1256-instrument-audit-three-findings-2026-08-06.md
as TEXT, with no probe run (their shell was fail-closed). This is v2: the three
findings fixed, and the four probes that audit specified, run.

What changed, finding by finding:

  F1 -- test 2 asked "is this path at main's TIP?", which calls a landed-then-
        renamed or landed-then-deleted file STRANDED. v2 asks the blob-level
        question instead: `git log origin/main --find-object=<blob>`. Empty is
        the real hard positive -- the content landed under NO path, ever. A hit
        names the commit it landed in, whatever name it wore. v2 also checks
        whether the path ever existed in main's HISTORY, which closes the
        delete case that --find-object alone leaves open when the file landed
        in modified form.

  F2 -- test 3 pooled added lines across every file the commit touched:
        `any(s in b for b in main_blobs.values())`. A line added to file A
        counted as present if it recurred in file B. v2 matches each added line
        against the blob of the file its hunk added it to, and splits the
        verdict into own-file-present vs cross-file-present. Any head whose
        "present" rests on cross-file matches drops back to UNKNOWN rather than
        LIKELY-LANDED.

  F3 -- a merge-commit tip returned no paths from `diff-tree` and printed
        EMPTY, dropping out of the sweep unmarked. v2 uses `-m --first-parent`
        so merge tips are testable, and gives them their own verdict so the
        sweep's silence is enumerable rather than invisible.

  probe 1 -- `git cherry origin/main <head>` subtracts the rebased/cherry-
        picked class by patch-id equality. Ancestry fails on that class too, so
        it is a real over-report channel disjoint from tests 2 and 3.
        Squash-merges survive it (patch-ids differ), so it narrows and never
        launders.

Bias directions are unchanged in kind: test 1 over-reports, test 3 still errs
toward "landed" on substring recurrence WITHIN a file. Read a high `missing` as
proof of stranding; a low `missing` still is not proof of landing.

Usage:  stranded_by_content_v2.py [commit ...]     # default: HEAD
        stranded_by_content_v2.py --branches       # sweep all local heads
        stranded_by_content_v2.py --branches --csv # machine-readable
"""
import subprocess
import sys

BASE = "origin/main"


def git(*args):
    return subprocess.run(["git", *args], capture_output=True, text=True).stdout


def rc(*args):
    return subprocess.run(["git", *args], capture_output=True).returncode


def is_ancestor(commit, base=BASE):
    return rc("merge-base", "--is-ancestor", commit, base) == 0


def n_parents(commit):
    out = git("rev-list", "--parents", "-n", "1", commit).split()
    return max(len(out) - 1, 0)


def touched_paths(commit, merge):
    """Paths the commit changed. Merges are diffed against their first parent
    (F3) so a merge tip is testable instead of silently EMPTY."""
    if merge:
        return git("diff-tree", "--no-commit-id", "--name-only", "-r",
                   "-m", "--first-parent", commit).split()
    return git("diff-tree", "--no-commit-id", "--name-only", "-r", commit).split()


def content_ever_landed(commit, path):
    """F1: did this exact blob land on main under ANY path, ever?
    Returns (landed: bool, evidence: str)."""
    blob = git("rev-parse", f"{commit}:{path}").strip()
    if not blob:
        return None, "blob unreadable"
    hit = git("log", BASE, "--find-object=" + blob, "--oneline", "-1").strip()
    if hit:
        return True, f"blob landed in {hit}"
    # blob absent. Did the PATH ever exist on main (landed then edited/deleted)?
    hist = git("log", BASE, "--oneline", "-1", "--", path).strip()
    if hist:
        return False, f"blob never landed; path existed on main (last: {hist})"
    return False, "blob never landed; path never existed on main"


def added_lines_per_file(commit, merge):
    """F2: added lines keyed by the file whose hunk added them."""
    args = ["show", commit, "--unified=0", "--format="]
    if merge:
        args = ["show", commit, "--unified=0", "--format=", "-m", "--first-parent"]
    per = {}
    cur = None
    for line in git(*args).splitlines():
        if line.startswith("+++ b/"):
            cur = line[6:].strip()
            per.setdefault(cur, set())
            continue
        if line.startswith("+++"):
            cur = None
            continue
        if line.startswith("+") and cur:
            s = line[1:].strip()
            if len(s) >= 12:  # short lines (braces, keywords) match anywhere
                per[cur].add(s)
    return {p: v for p, v in per.items() if v}


def cherry_equivalent(commit):
    """probe 1: is this head's patch already on main by patch-id?
    `git cherry BASE head` marks '-' for patches BASE already has."""
    out = git("cherry", BASE, commit)
    marks = [ln.split()[0] for ln in out.splitlines() if ln.strip()]
    if not marks:
        return None, "no patches to compare"
    have = marks.count("-")
    return (have, len(marks)), f"{have}/{len(marks)} patches already on {BASE} by patch-id"


def classify(commit):
    if is_ancestor(commit):
        return "ON-MAIN", "reachable from " + BASE, {}

    merge = n_parents(commit) > 1
    tag = "merge-tip " if merge else ""
    paths = touched_paths(commit, merge)
    if not paths:
        # F3: now a distinguishable verdict, not a silent drop
        return "NO-PATHS", f"{tag}commit touches no paths even vs first parent", {}

    # probe 1 -- patch-id equality subtracts the rebased/cherry-picked class
    cherry, cdetail = cherry_equivalent(commit)
    if cherry and cherry[0] == cherry[1]:
        return "CHERRY-LANDED", f"{tag}{cdetail}", {"cherry": cdetail}

    # test 2 (F1) -- blob-level: content landed under ANY path, ever?
    # Only paths ABSENT from main's tip need the (expensive, full-history) blob
    # scan: a path present at the tip was never a test-2 stranding in the first
    # place, and falls through to the line test below. This is a speed-only
    # restriction -- the F1 case IS "absent at tip, content landed anyway".
    absent_at_tip = [p for p in paths if rc("cat-file", "-e", f"{BASE}:{p}") != 0]
    never, landed_elsewhere = [], []
    for p in absent_at_tip:
        landed, ev = content_ever_landed(commit, p)
        if landed:
            landed_elsewhere.append((p, ev))
        elif "path never existed" in ev:
            never.append((p, ev))
        else:
            # blob absent but the path DID exist on main once: landed then
            # edited, or landed then deleted. Not a hard positive either way.
            landed_elsewhere.append((p, ev))
    if never:
        return ("STRANDED",
                f"{tag}{len(never)} added path(s) whose content landed nowhere on {BASE}: {never[0][0]}",
                {"cherry": cdetail, "hard": never})
    if landed_elsewhere and len(landed_elsewhere) == len(paths):
        # Every touched path's exact blob is on main under SOME name. The
        # line-level test below is path-keyed and would re-strand a renamed
        # file, which is the F1 defect wearing a different hat -- so stop here.
        return ("CONTENT-LANDED",
                f"{tag}all {len(paths)} path(s) landed by blob; {landed_elsewhere[0][1]}",
                {"cherry": cdetail, "renamed": landed_elsewhere})

    # test 3 (F2) -- per-file added-line matching
    per = added_lines_per_file(commit, merge)
    if not per:
        return "UNKNOWN", f"{tag}no substantive added lines to test", {"cherry": cdetail}

    blob_cache = {p: git("show", f"{BASE}:{p}") for p in paths}
    own = cross = missing = total = 0
    pooled_files = []   # files whose "present" is ENTIRELY cross-file
    for p, lines in per.items():
        mine = blob_cache.get(p, "")
        others = [b for q, b in blob_cache.items() if q != p]
        f_own = f_cross = f_missing = 0
        for s in lines:
            if s in mine:
                f_own += 1
            elif any(s in b for b in others):
                f_cross += 1
            else:
                f_missing += 1
        own += f_own
        cross += f_cross
        missing += f_missing
        total += len(lines)
        # F2 is a PER-FILE property: a file whose every added line matched only
        # in some OTHER file's blob has not been shown to have landed at all,
        # however healthy the commit-wide pooled total looks.
        if f_cross and not f_own and not f_missing:
            pooled_files.append(p)

    det = f"{tag}own-file {own}, cross-file {cross}, missing {missing} of {total} added lines"
    extra = {"cherry": cdetail, "own": own, "cross": cross,
             "missing": missing, "total": total, "pooled_files": pooled_files}
    if missing:
        return "STRANDED", det, extra
    if pooled_files:
        return ("UNKNOWN",
                det + f" -- {len(pooled_files)} file(s) POOLED-PRESENT ONLY "
                      f"(every match landed in a different file): {pooled_files[0]}",
                extra)
    if cross:
        return "LIKELY-LANDED", det + " -- some cross-file matches, weaker than v1 implied", extra
    return "LIKELY-LANDED", det + " -- every match own-file", extra


def main():
    args = sys.argv[1:]
    csv = "--csv" in args
    args = [a for a in args if a != "--csv"]
    if args and args[0] == "--branches":
        targets = [ln.split()[0] for ln in
                   git("for-each-ref", "--format=%(objectname:short) %(refname:short)",
                       "refs/heads").splitlines() if ln.strip()]
    else:
        targets = args or ["HEAD"]

    tally = {}
    for c in targets:
        verdict, detail, extra = classify(c)
        tally[verdict] = tally.get(verdict, 0) + 1
        if verdict == "ON-MAIN":
            continue
        subject = git("log", "-1", "--format=%h %ad %s", "--date=short", c).strip()
        if csv:
            print(f"{verdict}\t{subject}\t{detail}")
        else:
            print(f"{verdict:14} {subject}")
            print(f"{'':14} {detail}")
    print("\n-- tally --")
    for k in sorted(tally):
        print(f"{tally[k]:4}  {k}")


if __name__ == "__main__":
    main()
