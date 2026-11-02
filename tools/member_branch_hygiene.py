#!/usr/bin/env python3
"""Audit (and, with --apply, clean) ONE member's local branches and worktrees.

Squash-merge breaks the predicate everyone reaches for first: after a PR is
squashed, the branch tip is never an ancestor of main again, so
`git branch --merged` reports unmerged forever and the local refs pile up
(measured: 43 fully-pushed local kimi/* branches and 13 stale worktrees on one
host, 2026-10-20). The test that still means anything is the PR's STATE, via
`gh pr list --head <branch>`.

The safety rule is mechanical and derived from fresh evidence per branch,
never from a list:

  KEEP   the branch the main checkout sits on
  KEEP   a branch a KEPT worktree sits on (you cannot delete it anyway)
  KEEP   no remote twin (the local ref is the only copy)
  KEEP   unpushed commits (origin/<branch> does not contain the local tip)
  KEEP   OPEN PR, and KEEP when gh cannot say (unknown fails closed)
  KEEP   a worktree that is dirty (untracked/modified files beyond whitelisted
         build scratch: .cargo/, target/), detached (operator's call), or on
         another member's branch
  drop   local branch only when: remote twin exists AND unpushed==0 AND the
         PR (if any) is MERGED/CLOSED or there is no PR at all (findings
         journals live on origin; the local ref is a cache)
  drop   a worktree only when: it is not the main checkout, it is clean, and
         its branch is droppable ON THE FACTS above — a worktree's own checkout
         does not keep its branch, or no branch-attached worktree could ever
         be dropped, and that is exactly the forcing case this tool exists for

--apply REVALIDATES EVERY TARGET IMMEDIATELY BEFORE DELETING IT (nova's P1 on
#1358). The audit is a snapshot; between it and the delete a co-seat can push
the branch, dirty the worktree, or open a PR. Each deletion first re-derives
the target's verdict from fresh git/gh evidence and SKIPS on any drift — fail
closed — and any skip exits nonzero. Worktrees are revalidated and removed
before branches: removing a worktree changes its branch's in-use set, which
the branch's own revalidation then sees.

Nothing here ever deletes a remote branch. The remote is the fleet's record;
this tool only reclaims local refs and directories. Deleting a local branch
loses nothing the remote holds; removing a clean worktree loses nothing the
branch holds. The two KEEP-on-sight classes (no twin, unpushed) are the only
places a local deletion could actually lose work, and they are guarded three
times: reported in the audit, re-derived in --apply, and enforced by git
itself (branch -D still refuses a checked-out branch).

Usage:
  member_branch_hygiene.py --member kimi [--repo PATH]            # audit only
  member_branch_hygiene.py --member kimi --apply                  # clean what the rule allows
  member_branch_hygiene.py --member kimi --json

--json renders the audit and returns; combining it with --apply is an error
(it used to silently suppress the requested cleanup — the audit returned
before the apply ran). --member is required and must match the branch prefix
(`kimi/*`). It refuses to audit another member's prefix without
--i-am-allowed-to-audit-others, which exists for the operator, not for
convenience.
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


def worktrees(repo):
    """path -> branch (None when detached). First entry is the main checkout."""
    wt = git(repo, "worktree", "list", "--porcelain").stdout
    out, path = {}, None
    for line in wt.splitlines():
        if line.startswith("worktree "):
            path = line.split(" ", 1)[1]
            out[path] = None
        elif line.startswith("branch ") and path:
            out[path] = line.split("refs/heads/", 1)[-1]
    return out


def branch_facts(repo, branch):
    """The evidence a drop decision is made from: (remote_twin, unpushed, prs).
    prs is None when gh cannot answer; unknown fails closed downstream."""
    twin = git(repo, "rev-parse", "--verify", "-q", f"origin/{branch}",
               check=False).returncode == 0
    unpushed = None
    if twin:
        unpushed = int(git(repo, "rev-list", "--count",
                           f"origin/{branch}..{branch}").stdout.strip())
    return twin, unpushed, gh_prs(repo, branch)


def facts_say_droppable(facts):
    """The drop rule over raw facts, shared by the audit and by --apply's
    per-target revalidation so the two can never drift apart in logic."""
    twin, unpushed, prs = facts
    if not twin or unpushed is None or unpushed > 0 or prs is None:
        return False
    return not any(s == "OPEN" for _, s in prs)


def facts_verdict(facts):
    twin, unpushed, prs = facts
    if not twin:
        return "keep (NO REMOTE TWIN — local ref is the only copy)"
    if unpushed:
        return f"keep (unpushed={unpushed})"
    if prs is None:
        return "keep (PR state unknown — gh unavailable)"
    if any(s == "OPEN" for _, s in prs):
        return "keep (PR open: " + ",".join(f"#{n}" for n, s in prs if s == "OPEN") + ")"
    if any(s == "MERGED" for _, s in prs):
        return "drop (PR merged: " + ",".join(f"#{n}" for n, s in prs if s == "MERGED") + ")"
    return "drop (fully pushed; no PR — findings journal lives on origin)"


def worktree_dirt(repo, path):
    dirty = [l for l in git(repo, "-C", path, "status", "--porcelain").stdout.splitlines()]
    bad = [l for l in dirty if not any(l[3:].startswith(w) for w in WHITELIST_DIRT)]
    return dirty, bad


def audit(repo, member, args_operator=False):
    prefix = f"{member}/"
    wts = worktrees(repo)
    main_checkout = next(iter(wts)) if wts else None
    main_branch = wts.get(main_checkout)

    branches = [l.strip() for l in
                git(repo, "branch", "--list", f"{prefix}*",
                    "--format", "%(refname:short)").stdout.splitlines() if l.strip()]
    facts = {b: branch_facts(repo, b) for b in branches}

    # Worktrees first: a worktree's droppability is derived from its branch's
    # FACTS, never from the branch's audit verdict — the worktree's own
    # checkout would otherwise keep its own branch, and no branch-attached
    # worktree could ever be dropped.
    wt_rows = []
    for path, branch in wts.items():
        if path == main_checkout:
            continue
        dirty, bad = worktree_dirt(repo, path)
        if branch is None:
            # A detached checkout names no owner. A member never drops one; the
            # operator may, when it is clean.
            verdict = ("drop" if not bad and args_operator else
                       f"keep (detached — owner unprovable; operator's call"
                       f"{', dirty: ' + str(bad[:3]) if bad else ''})")
        elif not branch.startswith(prefix):
            verdict = "keep (another member's branch)"
        elif not facts_say_droppable(facts.get(branch, branch_facts(repo, branch))):
            verdict = "keep (branch kept)"
        elif bad:
            verdict = f"keep (untracked/modified files: {bad[:3]})"
        else:
            verdict = "drop"
        wt_rows.append({"path": path, "branch": branch, "detached": branch is None,
                        "dirty": dirty, "verdict": verdict})

    kept_wt_branches = {w["branch"] for w in wt_rows
                        if w["branch"] and not w["verdict"].startswith("drop")}
    rows = []
    for b in branches:
        if b == main_branch:
            verdict = "keep (checked out in the main tree)"
        elif b in kept_wt_branches:
            verdict = "keep (checked out in a kept worktree)"
        else:
            verdict = facts_verdict(facts[b])
        rows.append({"branch": b, "remote_twin": facts[b][0], "unpushed": facts[b][1],
                     "prs": facts[b][2],
                     "checked_out": b == main_branch or b in kept_wt_branches,
                     "verdict": verdict})
    return rows, wt_rows


def revalidate_worktree(repo, prefix, path, args_operator):
    """Re-derive ONE worktree's verdict from fresh evidence, immediately before
    its deletion. (ok, why-not) — any drift fails closed."""
    wts = worktrees(repo)
    if path not in wts:
        return False, "worktree vanished since audit"
    if path == next(iter(wts)):
        return False, "it is the main checkout"
    branch = wts[path]
    _, bad = worktree_dirt(repo, path)
    if branch is None:
        if args_operator and not bad:
            return True, ""
        return False, f"detached, and dirty: {bad[:3]}" if bad else "detached"
    if not branch.startswith(prefix):
        return False, f"branch {branch} is another member's"
    if not facts_say_droppable(branch_facts(repo, branch)):
        return False, f"branch {branch} no longer droppable on fresh evidence"
    if bad:
        return False, f"dirty since audit: {bad[:3]}"
    return True, ""


def revalidate_branch(repo, branch):
    """Re-derive ONE branch's verdict from fresh evidence, immediately before
    its deletion — after worktree removals, so the in-use set is current."""
    wts = worktrees(repo)
    if branch == wts.get(next(iter(wts))):
        return False, "checked out in the main tree"
    if branch in {b for b in wts.values() if b}:
        return False, "checked out in a surviving worktree"
    if not facts_say_droppable(branch_facts(repo, branch)):
        return False, "no longer droppable on fresh evidence"
    return True, ""


def apply_drops(repo, prefix, rows, wt_rows, args_operator):
    drift = []
    for w in wt_rows:
        if w["verdict"] != "drop":
            continue
        ok, why = revalidate_worktree(repo, prefix, w["path"], args_operator)
        if not ok:
            drift.append(f"SKIP worktree {w['path']}: {why}")
            continue
        git(repo, "worktree", "remove", "--force", w["path"])
        print(f"removed worktree {w['path']}")
    for r in rows:
        if not r["verdict"].startswith("drop"):
            continue
        ok, why = revalidate_branch(repo, r["branch"])
        if not ok:
            drift.append(f"SKIP branch {r['branch']}: {why}")
            continue
        git(repo, "branch", "-D", r["branch"])
        print(f"deleted local branch {r['branch']} (record on origin)")
    for d in drift:
        print(d)
    if drift:
        print(f"\n{len(drift)} target(s) drifted since audit and were SKIPPED "
              f"(fail closed) — re-run the audit for a current view.")
        return 1
    return 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--member", required=True)
    ap.add_argument("--repo", default=os.getcwd())
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--i-am-allowed-to-audit-others", action="store_true")
    args = ap.parse_args()

    if args.json and args.apply:
        ap.error("--json and --apply are mutually exclusive: --json renders the "
                 "audit and returns, so the combination silently suppressed the "
                 "requested cleanup")

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

    sys.exit(apply_drops(args.repo, f"{args.member}/", rows, wt_rows,
                         args.i_am_allowed_to_audit_others))


if __name__ == "__main__":
    main()
