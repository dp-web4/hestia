#!/usr/bin/env python3
"""git-manager reconciliation — report, and optionally reap, stale worktrees and branches.

The functions the fleet's voted-down git-manager ROLE would have owned, packaged as a TOOL so any
member (or a cron) can run them WITHOUT a dedicated custodian — respecting that vote while still
getting the work done. Report-only by default; nothing is removed without `--prune-worktrees`.

Solves the sprawl measured 2026-08-13 (hestia #387 frame): 31 worktrees, feature branches ~35
commits behind main, and the shared deploy tree drifting onto a feature branch (which stranded a
deploy — the gates run from that tree).

CHECKS
  1. DEPLOY-TREE INVARIANT — the main working tree must stay on `main`; it is what the gates run
     from, so drifting it onto a feature branch runs stale gate code and strands deploys. Reported,
     not auto-fixed: switching a SHARED tree's branch is fleet-affecting, so the fix command is
     printed for an operator to run deliberately.
  2. WORKTREE REAP — a worktree is REAPABLE when it is clean AND (its branch is merged to main OR
     its HEAD is on a remote). A dirty or unpushed-and-unmerged worktree is KEPT, always: reaping it
     would destroy the only copy of uncommitted/unpushed work. The main/deploy tree is never reaped.
  3. BRANCH STALENESS — each remote feature branch's behind/ahead vs main; flagged TRANSPLANT when
     far behind (a rebase would conflict; a clean-transplant of the delta is the move).

SAFETY: `--prune-worktrees` removes only worktrees classified REAPABLE, and re-verifies clean
immediately before each removal. It never touches the main/deploy tree. Read-only otherwise.
"""
import argparse
import os
import subprocess
import sys


def git(*args, cwd=None, timeout=25):
    # Per-call timeout: a `git status` on a /mnt/c drvfs worktree can hang for seconds under load,
    # and a hung maintenance run is useless. A timed-out call returns rc=124; callers treat that
    # conservatively (unknown -> KEEP), never as a reason to reap.
    try:
        r = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), r.returncode
    except subprocess.TimeoutExpired:
        return "", 124


def main_ref():
    _, rc = git("rev-parse", "--verify", "-q", "origin/main")
    return "origin/main" if rc == 0 else "main"


def worktrees():
    out, _ = git("worktree", "list", "--porcelain")
    wts, cur = [], {}
    for line in out.splitlines():
        if not line.strip():
            if cur:
                wts.append(cur)
                cur = {}
            continue
        if line.startswith("worktree "):
            cur = {"path": line[len("worktree "):]}
        elif line.startswith("HEAD "):
            cur["head"] = line[len("HEAD "):]
        elif line.startswith("branch "):
            cur["branch"] = line[len("branch "):].replace("refs/heads/", "")
        elif line == "detached":
            cur["detached"] = True
        elif line == "bare":
            cur["bare"] = True
    if cur:
        wts.append(cur)
    return wts


def is_dirty(path):
    out, rc = git("status", "--porcelain", cwd=path)
    return rc != 0 or bool(out.strip())


def merged_to(head, target):
    _, rc = git("merge-base", "--is-ancestor", head, target)
    return rc == 0


def on_remote(head):
    out, _ = git("branch", "-r", "--contains", head)
    return bool(out.strip())


def classify(wt, target, main_path):
    path = wt["path"]
    if wt.get("bare"):
        return "KEEP", "bare repo"
    if os.path.realpath(path) == os.path.realpath(main_path):
        return "KEEP", "the main/deploy tree"
    if not os.path.isdir(path):
        return "PRUNE-GONE", "directory missing"
    head = wt.get("head", "")
    # Cheap object-DB checks FIRST (merge-base / branch --contains); the working-tree `git status`
    # (the slow /mnt/c call) runs ONLY for a merged/pushed candidate, to confirm clean before
    # declaring it reapable. An unpushed+unmerged worktree is KEPT without a status call.
    merged = bool(head) and merged_to(head, target)
    pushed = bool(head) and (merged or on_remote(head))
    if not (merged or pushed):
        return "KEEP", "unpushed + unmerged work"
    if is_dirty(path):
        return "KEEP", "uncommitted changes"
    return "REAPABLE", ("branch merged to main" if merged else "HEAD pushed to a remote (clean)")


def main():
    ap = argparse.ArgumentParser(description="git-manager reconciliation (report-only by default)")
    ap.add_argument("--prune-worktrees", action="store_true",
                    help="remove REAPABLE worktrees (re-verified clean+safe first)")
    args = ap.parse_args()

    target = main_ref()
    wts = worktrees()
    # The deploy tree is the PRIMARY worktree — the first entry in `git worktree list
    # --porcelain`, a position git guarantees. Identifying it by "whichever worktree
    # holds branch main" (the old form) MISSES the exact failure this check exists to
    # catch: a deploy tree drifted onto a feature branch no longer holds main, so the
    # old lookup silently re-pointed the invariant at some other worktree (GPT, #394).
    main_path = wts[0]["path"] if wts else git("rev-parse", "--show-toplevel")[0]

    print(f"git-manager reconciliation — target {target}\n")

    # 1. deploy-tree invariant
    main_branch, _ = git("rev-parse", "--abbrev-ref", "HEAD", cwd=main_path)
    ok = main_branch == "main"
    print(f"[1] DEPLOY-TREE INVARIANT: {main_path}")
    print(f"    on '{main_branch}' — {'OK' if ok else 'DRIFTED — the gates run stale code'}")
    if not ok:
        print(f"    fix (operator): git -C {main_path} checkout main && "
              f"git -C {main_path} merge --ff-only {target}")
    print()

    # 2. worktree reap
    print(f"[2] WORKTREES: {len(wts)} total")
    reapable, counts = [], {}
    for wt in wts:
        cls, why = classify(wt, target, main_path)
        counts[cls] = counts.get(cls, 0) + 1
        tag = wt.get("branch") or ("(detached)" if wt.get("detached") else "?")
        if cls in ("REAPABLE", "PRUNE-GONE"):
            reapable.append((wt, cls))
        print(f"    {cls:11} {tag:46.46} {why}")
    print(f"    -> {counts};  {len(reapable)} reapable\n")

    # 3. branch staleness
    print("[3] BRANCH STALENESS (remote feature branches with un-merged commits)")
    out, _ = git("for-each-ref", "--format=%(refname:short)", "refs/remotes/origin")
    rows = []
    for b in out.splitlines():
        if b == "origin/main" or b.endswith("/HEAD"):
            continue
        behind_s, _ = git("rev-list", "--count", f"{b}..{target}")
        ahead_s, _ = git("rev-list", "--count", f"{target}..{b}")
        try:
            behind, ahead = int(behind_s or 0), int(ahead_s or 0)
        except ValueError:
            continue
        if ahead == 0:
            continue
        flag = "TRANSPLANT" if behind > 20 else ("rebase" if behind else "mergeable")
        rows.append((behind, ahead, b, flag))
    for behind, ahead, b, flag in sorted(rows, reverse=True):
        print(f"    {b:52.52} behind {behind:3} ahead {ahead:3}  -> {flag}")
    print(f"    {sum(1 for r in rows if r[3] == 'TRANSPLANT')} need clean-transplant "
          f"(too far behind to rebase)\n")

    # prune action (opt-in)
    if args.prune_worktrees:
        print("PRUNING reapable worktrees (re-verifying clean first)...")
        git("worktree", "prune")
        for wt, cls in reapable:
            if cls == "PRUNE-GONE":
                continue
            path = wt["path"]
            # Re-verify the FULL reapable predicate immediately before the forced
            # removal — not just cleanliness. Between the report pass and this point
            # a branch may have gained unpushed commits (classify would then say KEEP);
            # rechecking only `is_dirty` would still remove it (GPT, #394).
            cls2, why2 = classify(wt, target, main_path)
            if cls2 != "REAPABLE":
                print(f"    SKIP {path} — no longer reapable ({cls2}: {why2})")
                continue
            _, rc = git("worktree", "remove", "--force", path)
            print(f"    {'removed' if rc == 0 else 'FAILED'}: {path}")
    else:
        print("(report only — pass --prune-worktrees to remove the REAPABLE ones)")


if __name__ == "__main__":
    sys.exit(main())
