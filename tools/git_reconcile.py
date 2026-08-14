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
import json
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
    #
    # THE POPULATION IS THE REMOTE, NOT YOUR VIEW OF IT (#442). This section used to
    # enumerate `for-each-ref refs/remotes/origin`, which is the LOCAL view — and a local
    # view leaks in BOTH directions: it misses branches never fetched, and it retains refs
    # the remote no longer has. Measured 2026-08-14: 245 refs under `refs/remotes/pr/*`
    # (the `fetch origin refs/pull/N/head:refs/remotes/pr/N` review idiom) made this tool
    # report 390 remote branches where the remote had 86, and 219 "deletable" where 12 were.
    # Those refs sit under refs/remotes/ with NO remote name, so `git remote prune` cannot
    # ever collect them. Authority is now `ls-remote`; the local view is reported separately
    # as its own finding, because phantom refs are real cleanup — just not branch staleness.
    print("[3] BRANCH STALENESS (remote feature branches with un-merged commits)")
    ls, rc_ls = git("ls-remote", "--heads", "origin")
    remote_heads = set()
    for line in ls.splitlines():
        parts = line.split("\t")
        if len(parts) == 2 and parts[1].startswith("refs/heads/"):
            remote_heads.add(parts[1][len("refs/heads/"):])
    if rc_ls != 0 or not remote_heads:
        # Never silently fall back to the local view — that is the defect. Say so instead.
        print("    ls-remote failed or returned nothing; branch staleness NOT measured "
              "(refusing to substitute the local ref view, which is what #442 corrected).")
        remote_heads = None
    # A branch's PR STATE is what makes "transplant" actionable or wrong: a branch whose PR
    # was closed unmerged is retired-by-decision, not stranded work, and telling an operator
    # to transplant it is advice to undo a disposition. Optional: git-only clones just lose
    # the annotation (never the report).
    pr_state = {}
    try:
        import subprocess as _sp
        _r = _sp.run(["gh", "pr", "list", "--state", "all", "--limit", "400",
                      "--json", "headRefName,state,number"],
                     capture_output=True, text=True, timeout=45)
        if _r.returncode == 0:
            for pr in json.loads(_r.stdout or "[]"):
                # newest PR per branch wins (a branch can be reused)
                prev = pr_state.get(pr["headRefName"])
                if prev is None or pr["number"] > prev[0]:
                    pr_state[pr["headRefName"]] = (pr["number"], pr["state"])
    except Exception:
        pr_state = {}

    rows = []
    for b in ([f"origin/{h}" for h in sorted(remote_heads)] if remote_heads else []):
        if b == "origin/main" or b.endswith("/HEAD"):
            continue
        # A head on the remote that this clone has never fetched cannot be measured here;
        # count it rather than skipping it silently.
        _, rc_have = git("rev-parse", "--verify", "-q", b)
        if rc_have != 0:
            rows.append((-1, -1, b, "UNFETCHED"))
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
        pr = pr_state.get(b[len("origin/"):])
        if pr and pr[1] == "CLOSED":
            flag = f"RETIRED(#{pr[0]})"      # disposition already made — do not transplant
        elif pr and pr[1] == "MERGED":
            flag = f"merged(#{pr[0]})"       # branch outlived its merge; deletable
        elif pr and pr[1] == "OPEN":
            flag = f"{flag} PR#{pr[0]}"
        rows.append((behind, ahead, b, flag))
    for behind, ahead, b, flag in sorted(rows, reverse=True):
        if flag == "UNFETCHED":
            print(f"    {b:52.52} {'(on the remote, never fetched here)':>28}  -> {flag}")
            continue
        print(f"    {b:52.52} behind {behind:3} ahead {ahead:3}  -> {flag}")
    print(f"    {sum(1 for r in rows if r[3] == 'TRANSPLANT')} need clean-transplant "
          f"(too far behind to rebase); population = {len(remote_heads or [])} remote heads\n")

    # 4. phantom local refs — the finding that corrected this tool (#442)
    print("[4] PHANTOM LOCAL REFS (under refs/remotes/ but owned by no configured remote)")
    remotes, _ = git("remote")
    owned = tuple(f"refs/remotes/{r}/" for r in remotes.split() if r)
    allrefs, _ = git("for-each-ref", "--format=%(refname)", "refs/remotes/")
    phantom = [r for r in allrefs.splitlines()
               if r.startswith("refs/remotes/") and not r.startswith(owned)]
    if phantom:
        from collections import Counter
        by_ns = Counter(r.split("/")[2] for r in phantom if len(r.split("/")) > 2)
        print(f"    {len(phantom)} phantom ref(s); `git remote prune` can NEVER collect these")
        for ns, n in by_ns.most_common(6):
            print(f"      refs/remotes/{ns}/*  x{n}")
        print("    They inflate every local branch count (git branch -r globs all of "
              "refs/remotes/). Typical source: `fetch origin refs/pull/N/head:refs/remotes/pr/N`.")
        print("    Remove:  git for-each-ref --format='delete %(refname)' 'refs/remotes/<ns>/*'"
              " | git update-ref --stdin")
    else:
        print("    none — every ref under refs/remotes/ belongs to a configured remote")
    print()

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
