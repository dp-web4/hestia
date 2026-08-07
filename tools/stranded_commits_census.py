#!/usr/bin/env python3
"""Which commits were pushed to a branch AFTER that branch's pull request merged?

WHY THIS EXISTS
---------------
A pull request merges the commit its head pointed at, and then stops caring. Push another
commit to the same branch afterwards and it is stranded: no pull request references it, none
ever will, and every question a member naturally asks answers YES.

    gh pr view <n> --json state          ->  MERGED
    git log <branch>                     ->  the commit is right there, at the tip
    git push                             ->  succeeded, everything up-to-date

The predicate that would catch it is a different one, and nobody runs it by habit:

    git merge-base --is-ancestor <commit> origin/main

This was found (2026-08-06) because two separate fixes on this repository were in exactly
that state at the same time, eight and twenty-five minutes past their merges, and BOTH were
subsequently cited in the forum and on the mesh as landed -- once by the seat that wrote the
fix and then again, second-hand, by a peer quoting it back. A branch whose PR is MERGED is a
WORSE signal than one whose PR is open, because "open" is visibly pending and "merged" reads
as done for the whole branch rather than for one commit.

THE CLASSES, AND WHY THEY ARE NOT THE SAME BUG
----------------------------------------------
  stranded-after-merge   the branch's newest PR is MERGED and the commit was authored AFTER
                         that merge. The dangerous one: it reads as landed from every angle.
  closed-unmerged        a PR existed and was closed without merging. A decision was taken.
                         Not silent -- somebody said no.
  never-proposed         commits ahead of main, no PR ever opened. Also unrouted, but the
                         member knows: there is no merge to mistake for one.
  open                   a PR is pending. Routed; waiting is the expected state.

Only the first class is a false LANDED signal. The others are unrouted-and-visibly-so, and
lumping them together is what makes the census unreadable -- the repo has many of the third
kind and they are mostly abandoned scratch, which would bury the finding.

TWO FILTERS THAT THE FIRST DRAFT OF THIS TOOL DID NOT HAVE, AND ITS ANSWER WAS 71
---------------------------------------------------------------------------------
"Not an ancestor of main" is NOT the same question as "did not land", and the first run of
this census reported 71 stranded commits by assuming it was. Both corrections lower it:

1. `git cherry` (patch-id equivalence). A squash- or rebase-merged PR lands its CONTENT on
   main under a NEW sha, so the original commit is never an ancestor and looks stranded
   forever. This repository has used both merge styles over its life, so the ancestor test
   alone reports every squash-merged PR as a loss. The tell in the first run was that the
   stranded sha was frequently the PR's OWN merged head -- a commit cannot be pushed after
   the merge of itself.

2. The SIGN of (commit authored) - (PR merged). This is the whole mechanism: a commit
   stranded by the defect is authored AFTER the merge it is mistaken for. One authored
   BEFORE is a different story (squash residue, a dropped commit, a rebase), and calling it
   the same thing buries the real finding in noise.

Commits ahead of main that fail neither test are reported under `unrouted-before-merge` --
named for what was measured (not an ancestor, no equivalent patch upstream, predates the
merge) rather than for a cause this tool cannot see.

USAGE
    python3 tools/stranded_commits_census.py                 # summary + the stranded set
    python3 tools/stranded_commits_census.py --all           # every class, full detail
    python3 tools/stranded_commits_census.py --json          # machine-readable

Exit status is 1 when the stranded-after-merge set is non-empty, so this can be a red trigger
in CI: it is green while nothing is stranded and goes red the moment something is, which is
the direction a guard has to fail in to be worth having.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from collections import defaultdict

BASE = "origin/main"


def git(*args: str) -> str:
    return subprocess.run(
        ("git",) + args, capture_output=True, text=True, check=True
    ).stdout.strip()


def gh_prs() -> list[dict]:
    """Every PR in the repo, one call. Per-branch calls would be 84 round trips."""
    out = subprocess.run(
        [
            "gh", "pr", "list", "--state", "all", "--limit", "1000",
            "--json", "number,state,headRefName,headRefOid,mergedAt,title",
        ],
        capture_output=True, text=True,
    )
    if out.returncode != 0:
        sys.stderr.write("gh pr list failed:\n" + out.stderr + "\n")
        sys.exit(2)
    return json.loads(out.stdout)


def is_ancestor(commit: str, of: str) -> bool:
    return subprocess.run(
        ["git", "merge-base", "--is-ancestor", commit, of],
        capture_output=True,
    ).returncode == 0


def upstream_equivalents(ref: str) -> set[str]:
    """Shas on `ref` whose PATCH already exists on BASE, per git's patch-id.

    This is what separates "squash-merged, content landed under a new sha" from "lost".
    `git cherry` prints `- <sha>` for a commit with an equivalent upstream and `+ <sha>`
    for one without.
    """
    out = subprocess.run(
        ["git", "cherry", BASE, ref], capture_output=True, text=True
    )
    if out.returncode != 0:
        return set()
    return {
        line.split()[1] for line in out.stdout.splitlines()
        if line.startswith("- ")
    }


def parse_iso(s: str) -> str:
    """Normalise both git's `--date=iso` and gh's Z-suffixed ISO to a comparable key."""
    from datetime import datetime, timezone
    s = s.strip()
    if not s:
        return ""
    try:
        if s.endswith("Z"):
            dt = datetime.fromisoformat(s[:-1]).replace(tzinfo=timezone.utc)
        else:
            dt = datetime.fromisoformat(s)
        return dt.astimezone(timezone.utc).isoformat()
    except ValueError:
        return ""


def classify() -> dict:
    branches = [
        b for b in git(
            "for-each-ref", "--format=%(refname:short)", "refs/remotes/origin"
        ).splitlines()
        # origin/HEAD is a symbolic alias for the default branch, not a branch. Counting it
        # is the same defect this repo's ref census carried (fixed 989e660) -- an alias
        # rendered as a member of the population.
        if b not in ("origin/HEAD", BASE) and not b.endswith("/HEAD")
    ]

    by_branch: dict[str, list[dict]] = defaultdict(list)
    for pr in gh_prs():
        by_branch[pr["headRefName"]].append(pr)

    result: dict[str, list] = {
        "stranded-after-merge": [], "unrouted-before-merge": [],
        "closed-unmerged": [], "never-proposed": [], "open": [],
    }
    landed_equivalent = 0

    for ref in branches:
        short = ref[len("origin/"):]
        ahead = [
            line.split(" ", 1)
            for line in git(
                "log", "--format=%H %ad|%s", "--date=iso", f"{BASE}..{ref}"
            ).splitlines()
        ]
        if not ahead:
            continue  # fully merged or behind; nothing to strand

        equivalents = upstream_equivalents(ref)
        commits = []
        for sha, rest in ahead:
            when, _, subject = rest.partition("|")
            if is_ancestor(sha, BASE):
                continue
            if sha in equivalents:
                landed_equivalent += 1  # squash/rebase: content is upstream under a new sha
                continue
            commits.append({"sha": sha[:7], "date": when,
                            "at": parse_iso(when), "subject": subject})
        if not commits:
            continue

        prs = sorted(by_branch.get(short, []), key=lambda p: p["number"])
        entry = {"branch": short, "commits": commits,
                 "prs": [{"number": p["number"], "state": p["state"],
                          "head": p["headRefOid"][:7], "mergedAt": p["mergedAt"]}
                         for p in prs]}

        if any(p["state"] == "OPEN" for p in prs):
            result["open"].append(entry)
        elif any(p["state"] == "MERGED" for p in prs):
            merged = [p for p in prs if p["state"] == "MERGED"]
            entry["merged_at"] = merged[-1]["mergedAt"]
            entry["merged_head"] = merged[-1]["headRefOid"][:7]
            cut = parse_iso(merged[-1]["mergedAt"] or "")
            # THE SIGN IS THE FINDING. After the merge -> stranded by this defect.
            # Before it -> something else, and this tool does not know what.
            after = [c for c in entry["commits"] if cut and c["at"] and c["at"] > cut]
            before = [c for c in entry["commits"] if c not in after]
            if after:
                result["stranded-after-merge"].append({**entry, "commits": after})
            if before:
                result["unrouted-before-merge"].append({**entry, "commits": before})
        elif prs:
            result["closed-unmerged"].append(entry)
        else:
            result["never-proposed"].append(entry)

    result["_landed_equivalent"] = landed_equivalent
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="print every class, not just stranded")
    ap.add_argument("--json", action="store_true", dest="as_json")
    args = ap.parse_args()

    res = classify()
    if args.as_json:
        print(json.dumps(res, indent=2))
        return 1 if res["stranded-after-merge"] else 0

    print(f"base: {BASE} @ {git('rev-parse', '--short', BASE)}")
    for cls in ("stranded-after-merge", "unrouted-before-merge",
                "closed-unmerged", "never-proposed", "open"):
        print(f"  {cls:24s} {len(res[cls]):3d} branches, "
              f"{sum(len(e['commits']) for e in res[cls]):3d} unrouted commits")
    print(f"  {'(landed via squash/rebase)':24s}      "
          f"{res['_landed_equivalent']:3d} commits excluded by patch-id")

    show = ("stranded-after-merge",) if not args.all else (
        "stranded-after-merge", "unrouted-before-merge",
        "closed-unmerged", "never-proposed", "open")
    for cls in show:
        if not res[cls]:
            continue
        print(f"\n=== {cls} ===")
        for e in res[cls]:
            prs = ", ".join(f"#{p['number']} {p['state']} head={p['head']}"
                            for p in e["prs"]) or "(no PR)"
            print(f"\n  {e['branch']}\n    {prs}")
            if cls == "stranded-after-merge":
                print(f"    merged at {e['merged_at']} with head {e['merged_head']}")
            for c in e["commits"]:
                print(f"    {c['sha']}  {c['date']}  {c['subject'][:76]}")

    n = sum(len(e["commits"]) for e in res["stranded-after-merge"])
    if n:
        print(f"\nRED: {n} commit(s) pushed to a branch after its PR merged. "
              f"They read as landed and are not on {BASE}.")
    else:
        print(f"\ngreen: nothing stranded after a merge.")
    return 1 if n else 0


if __name__ == "__main__":
    raise SystemExit(main())
