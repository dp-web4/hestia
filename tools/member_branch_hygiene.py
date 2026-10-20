#!/usr/bin/env python3
"""Audit (and, with --apply, clean) ONE member's local branches and worktrees.

Squash-merge breaks the predicate everyone reaches for first: after a PR is
squashed, the branch tip is never an ancestor of main again, so
`git branch --merged` reports unmerged forever and the local refs pile up
(measured: 43 fully-pushed local kimi/* branches and 13 stale worktrees on one
host, 2026-10-20). The test that still means anything is the PR's STATE, via
`gh pr list --head <branch>`.

The safety rule is mechanical and checked per branch, never from a list:

  KEEP   the branch the current checkout sits on, and every worktree's branch
  KEEP   no remote twin (the local ref is the only copy)
  KEEP   unpushed commits (origin/<branch> does not contain the local tip)
  KEEP   OPEN PR
  drop   local branch only when: remote twin exists AND unpushed==0 AND the
         PR (if any) is MERGED or there is no PR at all (findings journals live
         on origin; the local ref is a cache)
  drop   a worktree only when: it is not the main checkout, its branch is
         droppable by the rule above (or it is detached), and it is clean
         (untracked files are listed, and --apply refuses unless they are
         whitelisted build scratch: .cargo/, target/)

Nothing here ever deletes a remote branch. The remote is the fleet's record;
this tool only reclaims local refs and directories. Deleting a local branch
loses nothing the remote holds; removing a clean worktree loses nothing the
branch holds. The two KEEP-on-sight classes (no twin, unpushed) are the only
places a local deletion could actually lose work, and they are guarded twice:
reported in the audit and refused in --apply.

Usage:
  member_branch_hygiene.py --member kimi [--repo PATH]            # audit only
  member_branch_hygiene.py --member kimi --apply                  # clean what the rule allows
  member_branch_hygiene.py --member kimi --json

--member is required and must match the branch prefix (`kimi/*`). It refuses
to audit another member's prefix without --i-am-allowed-to-audit-others, which
exists for the operator, not for convenience.
"""
import argparse
import json
import os
import subprocess
import sys

WHITELIST_DIRT = (".cargo/", "target/")


def git(repo, *args, check=True):
    r = subprocess.run(["git", "-C", repo, *args],
                       capture_output=True, text=True)
    if check and r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r


def gh_prs(repo, branch):
    """PRs whose head is this branch: [(number, state)]. Needs gh auth."""
    r = subprocess.run(
        ["gh", "pr", "list", "--head", branch, "--state", "all",
         "--json", "number,state", "--limit", "5"],
        capture_output=True, text=True, cwd=repo)
    if r.returncode != 0:
        return None  # gh unavailable: PR state unknown, treat as no evidence
    try:
        return [(p["number"], p["state"]) for p in json.loads(r.stdout)]
    except (ValueError, KeyError):
        return None


def audit(repo, member, args_operator=False):
    prefix = f"{member}/"
    wt = git(repo, "worktree", "list", "--porcelain").stdout
    # worktree path -> branch ref (or None for detached)
    worktrees = {}
    path = None
    for line in wt.splitlines():
        if line.startswith("worktree "):
            path = line.split(" ", 1)[1]
            worktrees[path] = None
        elif line.startswith("branch ") and path:
            worktrees[path] = line.split("refs/heads/", 1)[-1]
    main_checkout = worktrees and next(iter(worktrees))  # first entry is the main tree
    branch_in_use = {b for b in worktrees.values() if b}

    branches = [l.strip() for l in
                git(repo, "branch", "--list", f"{prefix}*",
                    "--format", "%(refname:short)").stdout.splitlines() if l.strip()]
    rows = []
    for b in branches:
        twin = git(repo, "rev-parse", "--verify", "-q", f"origin/{b}",
                   check=False).returncode == 0
        unpushed = None
        if twin:
            unpushed = int(git(repo, "rev-list", "--count",
                               f"origin/{b}..{b}").stdout.strip())
        prs = gh_prs(repo, b)
        row = {"branch": b, "remote_twin": twin, "unpushed": unpushed,
               "prs": prs, "checked_out": b in branch_in_use}
        # verdict
        if row["checked_out"]:
            verdict = "keep (checked out)"
        elif not twin:
            verdict = "keep (NO REMOTE TWIN — local ref is the only copy)"
        elif unpushed:
            verdict = f"keep (unpushed={unpushed})"
        elif prs and any(s == "OPEN" for _, s in prs):
            verdict = "keep (PR open: " + ",".join(f"#{n}" for n, s in prs if s == "OPEN") + ")"
        elif prs and any(s == "MERGED" for _, s in prs):
            verdict = "drop (PR merged: " + ",".join(f"#{n}" for n, s in prs if s == "MERGED") + ")"
        elif prs is None:
            verdict = "keep (PR state unknown — gh unavailable)"
        else:
            verdict = "drop (fully pushed; no PR — findings journal lives on origin)"
        row["verdict"] = verdict
        rows.append(row)

    wt_rows = []
    for path, branch in worktrees.items():
        if path == main_checkout:
            continue
        dirty = [l for l in git(repo, "-C", path, "status", "--porcelain").stdout.splitlines()]
        bad_dirt = [l for l in dirty
                    if not any(l[3:].startswith(w) for w in WHITELIST_DIRT)]
        if branch is None:
            # A detached checkout names no owner. A member never drops one; the
            # operator may, when it is clean.
            verdict = ("drop" if not bad_dirt and args_operator else
                       f"keep (detached — owner unprovable; operator's call"
                       f"{', dirty: ' + str(bad_dirt[:3]) if bad_dirt else ''})")
        elif not branch.startswith(prefix):
            verdict = "keep (another member's branch)"
        elif not any(r["branch"] == branch and r["verdict"].startswith("drop") for r in rows):
            verdict = "keep (branch kept)"
        elif bad_dirt:
            verdict = f"keep (untracked/modified files: {bad_dirt[:3]})"
        else:
            verdict = "drop"
        wt_rows.append({"path": path, "branch": branch, "detached": branch is None,
                        "dirty": dirty, "verdict": verdict})
    return rows, wt_rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--member", required=True)
    ap.add_argument("--repo", default=os.getcwd())
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--i-am-allowed-to-audit-others", action="store_true")
    args = ap.parse_args()

    if args.member in ("claude", "claude-code", "codex", "cbp", "cbp-being", "gemini") \
            and not args.i_am_allowed_to_audit_others:
        sys.exit("refusing: --member names someone else. Audit your own prefix; "
                 "the operator passes --i-am-allowed-to-audit-others.")

    rows, wt_rows = audit(args.repo, args.member,
                          args_operator=args.i_am_allowed_to_audit_others)
    if args.json:
        print(json.dumps({"branches": rows, "worktrees": wt_rows}, indent=1))
        return

    for r in rows:
        print(f"{r['verdict']:<52} {r['branch']}")
    for w in wt_rows:
        print(f"{w['verdict']:<52} {w['path']}  [{w['branch'] or 'detached'}]")

    drops = [r for r in rows if r["verdict"].startswith("drop")]
    wt_drops = [w for w in wt_rows if w["verdict"] == "drop"]
    print(f"\n{len(rows)} branches ({len(drops)} droppable), "
          f"{len(wt_rows)} worktrees ({len(wt_drops)} droppable). Remote is never touched.")
    if not args.apply:
        if drops or wt_drops:
            print("audit only — rerun with --apply to perform the drops above.")
        return

    for w in wt_drops:
        git(args.repo, "worktree", "remove", "--force", w["path"])
        print(f"removed worktree {w['path']}")
    for r in drops:
        git(args.repo, "branch", "-D", r["branch"])
        print(f"deleted local branch {r['branch']} (record on origin)")


if __name__ == "__main__":
    main()
