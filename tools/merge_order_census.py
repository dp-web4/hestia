#!/usr/bin/env python3
"""Which of the open PRs can actually land, and in what order.

GitHub's `mergeable` answers ONE question: does this branch conflict with the
base as it stands right now?  It is a PAIRWISE predicate.  A merge queue asks a
different question -- can these N branches land one after another? -- and the
pairwise answer does not imply the sequential one.  Two siblings can each be
MERGEABLE against main and still be mutually exclusive: whichever lands first
makes the other CONFLICTING, and nothing in the per-PR view says so beforehand.

Measured on hestia 2026-09-03 over claude-code's 64 open PRs (see
`findings/wake-9908-merge-order-is-not-a-per-pr-property-2026-09-03.md`):

  * 59/64 land clean in ascending-number order; 58/64 in fewest-files order.
    Chronological authorship order is the better one and no per-PR field says so.
  * Two collision classes, both invisible to `mergeable`, which calls all of
    them MERGEABLE:
      - ORDER-SENSITIVE: {634, 859}.  634-then-859 lands; 859-then-634 does not.
        A correct order exists; the wrong one manufactures an avoidable conflict.
      - MUTUALLY EXCLUSIVE: {802, 816, 819}.  Every ordering blocks.  These are
        not a stack, they are three competing designs of one function, and no
        merge order rescues them -- they need one authored supersession.

The distinction is the point: the first class is a scheduling problem, the
second is an authoring problem, and the queue view renders them identically.

  python3 tools/merge_order_census.py --author @me
  python3 tools/merge_order_census.py --author @me --order files --json

Creates and removes its own scratch worktrees; mutates nothing else, never pushes.
Exit 0 always: this is a census, not a gate.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tempfile


def run(cmd, cwd=None, check=False):
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and p.returncode != 0:
        raise SystemExit(f"{' '.join(cmd)}: {p.stderr.strip()}")
    return p


def replay(repo, base, refs):
    """Land `refs` (a list of (key, ref)) onto `base`, in the order given.

    Returns (landed, blocked).  Each blocked entry records whether the branch
    conflicts with the BASE itself -- it is simply stale, and GitHub already
    says so -- or only with a SIBLING that landed earlier in this sequence,
    which is the case no per-PR view can express.
    """
    wt = tempfile.mkdtemp(prefix="merge-order-")
    run(["git", "worktree", "add", "--detach", wt, base], cwd=repo, check=True)
    try:
        landed, blocked = [], []
        for key, ref in refs:
            m = run(["git", "merge", "--no-ff", "-q", "-m", f"m{key}", ref], cwd=wt)
            if m.returncode == 0:
                landed.append(key)
                continue
            run(["git", "merge", "--abort"], cwd=wt)
            files = sorted({ln.split(" in ", 1)[1].strip()
                            for ln in (m.stdout + m.stderr).splitlines()
                            if ln.startswith("CONFLICT") and " in " in ln})
            # Against the base, or only against a sibling?  Merge it onto a
            # pristine base to find out; that is exactly what `mergeable` knows.
            probe = tempfile.mkdtemp(prefix="merge-probe-")
            run(["git", "worktree", "add", "--detach", probe, base], cwd=repo)
            solo = run(["git", "merge", "--no-ff", "-q", "-m", "probe", ref], cwd=probe)
            run(["git", "merge", "--abort"], cwd=probe)
            run(["git", "worktree", "remove", "--force", probe], cwd=repo)
            blocked.append({"key": key,
                            "against": "base" if solo.returncode != 0 else "sibling",
                            "files": files})
    finally:
        run(["git", "worktree", "remove", "--force", wt], cwd=repo)
    return landed, blocked


def open_prs(repo_dir, author, limit):
    p = run(["gh", "pr", "list", "--author", author, "--state", "open",
             "--limit", str(limit), "--json",
             "number,headRefName,title,files,mergeable"], cwd=repo_dir, check=True)
    return json.loads(p.stdout)


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", default=".", help="a checkout of the repo (not modified)")
    ap.add_argument("--author", default="@me")
    ap.add_argument("--base", default="origin/main")
    ap.add_argument("--limit", type=int, default=200)
    ap.add_argument("--order", default="number", choices=("number", "files"),
                    help="the landing order to test")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    prs = open_prs(args.repo, args.author, args.limit)
    if args.order == "number":
        prs.sort(key=lambda p: p["number"])
    else:
        prs.sort(key=lambda p: (len(p["files"]), p["number"]))

    landed, blocked_raw = replay(args.repo, args.base,
                                 [(p["number"], f"origin/{p['headRefName']}") for p in prs])
    by_num = {p["number"]: p for p in prs}
    blocked = [{"number": b["key"], "against": b["against"], "files": b["files"],
                "github_mergeable": by_num[b["key"]].get("mergeable"),
                "title": by_num[b["key"]]["title"][:70]} for b in blocked_raw]

    # The finding this tool exists for: pairwise-clean, sequentially dead.
    hidden = [b for b in blocked
              if b["against"] == "sibling" and b["github_mergeable"] == "MERGEABLE"]

    out = {"order": args.order, "total": len(prs), "landed": landed,
           "blocked": blocked, "hidden_sibling_collisions": [b["number"] for b in hidden]}
    if args.json:
        print(json.dumps(out, indent=2))
        return 0

    print(f"{len(landed)}/{len(prs)} land clean in {args.order} order")
    print("landable order:", " ".join(str(n) for n in landed))
    print()
    for b in blocked:
        tag = "stale vs base" if b["against"] == "base" else "KILLED BY A SIBLING"
        gh = b["github_mergeable"] or "?"
        print(f"  #{b['number']:>5} {tag:<20} gh={gh:<12} {b['title']}")
        for f in b["files"]:
            print(f"          {f}")
    if hidden:
        print()
        print("HIDDEN: GitHub calls these MERGEABLE; they cannot land after their own"
              " siblings:", " ".join(f"#{b['number']}" for b in hidden))
    return 0


if __name__ == "__main__":
    sys.exit(main())
