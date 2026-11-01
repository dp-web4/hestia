#!/usr/bin/env python3
"""member_branch_hygiene: the destructive half must fail closed on drift.

nova's P1 on #1358: --apply executed `git worktree remove --force` /
`git branch -D` from the audit's STALE snapshot, so a commit pushed (or a
worktree dirtied, or a PR opened) between audit and delete was destroyed
unseen. The fix is per-target revalidation immediately before each delete;
these tests pin it:

  1. happy path — a fully-pushed branch on a clean worktree IS dropped
     (the tool must still do its job);
  2. race — an unpushed commit landing between audit and apply saves BOTH
     the worktree and the branch, and the run exits nonzero;
  3. race — dirt landing between audit and apply saves the worktree, and
     the surviving worktree keeps its branch;
  4. --json --apply is refused (it used to silently suppress the cleanup);
  5. audit alone deletes nothing.

gh is stubbed in-process (facts are the decision input; the stub states them).
Run:  ./tools/member_branch_hygiene_test.py
"""
from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
_spec = importlib.util.spec_from_file_location("mbh", HERE / "member_branch_hygiene.py")
mbh = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mbh)

FAILURES = []


def check(name, cond, detail=""):
    if cond:
        print(f"  ok   {name}")
    else:
        print(f"  FAIL {name}  {detail}")
        FAILURES.append(name)


def sh(cwd, *args):
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError(f"{' '.join(args)}: {r.stderr.strip()}")
    return r


def make_repo(root):
    """A clone with a main commit, a fully-pushed kimi/* branch, and a clean
    worktree sitting on a second fully-pushed kimi/* branch."""
    root.mkdir(parents=True)
    origin = root / "origin.git"
    sh(root, "git", "init", "--bare", str(origin))
    repo = root / "repo"
    sh(root, "git", "clone", str(origin), str(repo))
    sh(repo, "git", "config", "user.email", "t@t")
    sh(repo, "git", "config", "user.name", "t")
    (repo / "f").write_text("0")
    sh(repo, "git", "add", "f")
    sh(repo, "git", "commit", "-qm", "init")
    sh(repo, "git", "push", "-q", "origin", "HEAD:main")
    sh(repo, "git", "checkout", "-qb", "main")
    for b in ("kimi/merged", "kimi/wt"):
        sh(repo, "git", "branch", b)
        sh(repo, "git", "push", "-q", "origin", b)
    wt = root / "wt"
    sh(repo, "git", "worktree", "add", str(wt), "kimi/wt")
    return repo, wt


def stub_prs(state):
    mbh.gh_prs = lambda repo, branch: list(state)


def main():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)

        repo, wt = make_repo(root / "one")
        stub_prs([("1", "MERGED")])
        rows, wt_rows = mbh.audit(str(repo), "kimi")
        check("happy path: merged branch is droppable",
              any(r["branch"] == "kimi/merged" and r["verdict"].startswith("drop") for r in rows),
              str(rows))
        check("happy path: clean worktree on a droppable branch is droppable",
              any(w["path"] == str(wt) and w["verdict"] == "drop" for w in wt_rows),
              str(wt_rows))
        rc = mbh.apply_drops(str(repo), "kimi/", rows, wt_rows, False)
        check("happy path: apply returns 0", rc == 0)
        check("happy path: worktree removed", not wt.exists())
        check("happy path: branch deleted",
              "kimi/merged" not in sh(repo, "git", "branch", "--format", "%(refname:short)").stdout)

        repo, wt = make_repo(root / "two")
        stub_prs([("2", "MERGED")])
        rows, wt_rows = mbh.audit(str(repo), "kimi")
        # RACE: after the audit, unpushed work lands on the worktree's branch.
        (wt / "new").write_text("race")
        sh(wt, "git", "add", "new")
        sh(wt, "git", "commit", "-qm", "unpushed work racing the cleanup")
        rc = mbh.apply_drops(str(repo), "kimi/", rows, wt_rows, False)
        check("race: unpushed commit between audit and apply exits nonzero", rc == 1)
        check("race: worktree survives", wt.is_dir())
        check("race: the racing branch survives",
              "kimi/wt" in sh(repo, "git", "branch", "--format", "%(refname:short)").stdout)

        repo, wt = make_repo(root / "three")
        stub_prs([("3", "MERGED")])
        rows, wt_rows = mbh.audit(str(repo), "kimi")
        # RACE: after the audit, the worktree gets dirty.
        (wt / "scratch.txt").write_text("not whitelisted")
        rc = mbh.apply_drops(str(repo), "kimi/", rows, wt_rows, False)
        check("race: dirt between audit and apply exits nonzero", rc == 1)
        check("race: dirty worktree survives", wt.is_dir())
        check("race: a surviving worktree keeps its branch",
              "kimi/wt" in sh(repo, "git", "branch", "--format", "%(refname:short)").stdout)
        check("race: the untouched droppable branch is still dropped",
              "kimi/merged" not in sh(repo, "git", "branch", "--format", "%(refname:short)").stdout)

        repo, _ = make_repo(root / "four")
        stub_prs([("4", "MERGED")])
        rows, wt_rows = mbh.audit(str(repo), "kimi")
        check("audit alone deletes nothing",
              "kimi/merged" in sh(repo, "git", "branch", "--format", "%(refname:short)").stdout)

        r = subprocess.run(
            [sys.executable, str(HERE / "member_branch_hygiene.py"),
             "--member", "kimi", "--repo", str(repo), "--json", "--apply"],
            capture_output=True, text=True)
        check("--json --apply is refused (rc=2)", r.returncode == 2, r.stderr[:200])
        check("--json --apply refusal names the conflict",
              "mutually exclusive" in r.stderr, r.stderr[:200])

    if FAILURES:
        print(f"FAILED {len(FAILURES)}: {FAILURES}")
        sys.exit(1)
    print("ALL CHECKS PASSED")


if __name__ == "__main__":
    main()
