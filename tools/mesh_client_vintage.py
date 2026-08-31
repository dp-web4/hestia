#!/usr/bin/env python3
"""Date every seat's INSTALLED member-mesh client against git history, and grade it
against `origin/main` — not against whatever this checkout happens to have.

Why this exists, and why it is not `install.sh --check`:

`install.sh --check` compares each seat's installed file to `$SRC` (the directory the
script itself lives in, i.e. the WORKING TREE) at line 141: `cmp -s "$SRC/$f" "$hooks/$f"`.
Its header advertises a different question — "is the code I am running the code that was
MERGED?" — and those two questions only give the same answer while the checkout happens
to equal main for that file. Measured 2026-08-31 on CBP: the checkout was on branch
`claude/review-7451`, 48 behind / 43 ahead of `origin/main`, and `--check` still graded
three seats as authoritative. It got the right answer by accident: neither synced file
had diverged between the branch and main. On a branch that touches either file, `current`
would certify bytes that were never merged, and `DRIFT` would fire against them.

So this tool anchors on `origin/main` explicitly, and adds the thing a boolean cannot
carry: the installed bytes are usually an exact historical revision, so we can name the
commit they came from and list what has landed since. "DRIFT" tells you a seat is behind;
this tells you *by how much, and what it is missing*.

Read-only. Exit 1 if any present seat is behind `origin/main`.
"""

import subprocess
import sys
import os
import hashlib

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRACKED = "plugins/member-mesh/hestia-mesh.py"

# seat -> installed path. The layout differs per engine because each picked its own,
# which is exactly why a fleet-wide answer needs a table and not a glob.
SEATS = {
    "claude-code": "~/.claude/hooks/member-mesh/hestia-mesh.py",
    "kimi-code": "~/.kimi-code/hooks/hestia-mesh.py",
    "codex": "~/.codex/hooks/hestia-mesh.py",
}


def git(*args):
    return subprocess.run(("git", "-C", REPO) + args, capture_output=True, text=True)


def sha_bytes(b):
    return hashlib.sha256(b).hexdigest()


def main():
    ref = sys.argv[1] if len(sys.argv) > 1 else "origin/main"

    head = git("cat-file", "-p", f"{ref}:{TRACKED}")
    if head.returncode != 0:
        print(f"cannot read {ref}:{TRACKED} — fetch first?", file=sys.stderr)
        return 2
    want = sha_bytes(head.stdout.encode())

    # Every revision of the file, newest first, so an installed copy can be dated by
    # exact match. A copy that matches nothing has been hand-edited and is reported so.
    revs = git("log", "--format=%H", "--", TRACKED).stdout.split()
    by_sha = {}
    for c in revs:
        blob = git("cat-file", "-p", f"{c}:{TRACKED}")
        if blob.returncode == 0:
            by_sha.setdefault(sha_bytes(blob.stdout.encode()), c)

    print(f"anchor {ref} = {want[:12]}  ({TRACKED})")
    behind = False
    for seat, p in SEATS.items():
        path = os.path.expanduser(p)
        if not os.path.exists(path):
            print(f"  {seat:<12} absent            {p}")
            continue
        got = sha_bytes(open(path, "rb").read())
        if got == want:
            print(f"  {seat:<12} CURRENT  {got[:12]}")
            continue
        behind = True
        origin = by_sha.get(got)
        if not origin:
            print(f"  {seat:<12} DIVERGENT {got[:12]}  matches no committed revision "
                  f"— hand-edited, not merely stale")
            continue
        when = git("log", "-1", "--format=%ad", "--date=short", origin).stdout.strip()
        missing = git("log", "--format=%h %ad  %s", "--date=short",
                      f"{origin}..{ref}", "--", TRACKED).stdout.strip()
        n = len([x for x in missing.splitlines() if x])
        print(f"  {seat:<12} STALE    {got[:12]}  = {origin[:12]} ({when}), "
              f"missing {n} commit(s):")
        for line in missing.splitlines():
            print(f"      {line}")
    return 1 if behind else 0


if __name__ == "__main__":
    sys.exit(main())
