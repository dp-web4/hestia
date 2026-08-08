#!/usr/bin/env python3
"""A file that declares how to run itself must be allowed to run.

Every tracked file whose first two bytes are `#!` is asserting "exec me
directly". Git records that intent in the tree mode, and only there. If the mode
is 100644, the shebang is a lie on every filesystem that enforces it.

Why this went unseen for so long: the fleet's working tree lives on
/mnt/c (NTFS via WSL DrvFs), which reports EVERY file as -rwxrwxrwx regardless
of what git stored. The exec bit is unobservable there. The same checkout on
ext4 -- a real clone, a CI runner, a Linux box, a /tmp worktree -- yields
-rw-rw-r-- and the bare-path invocation dies with rc=126.

That is the same defect shape as the undelivered-report port (PR #71): a
capability that appears to work because of an accident of the environment
rather than because the artifact carries it. There, the carrier was a
long-running process. Here, it is a filesystem that cannot say no.

The bite is not hypothetical. plugins/codex/hooks/hooks.json invokes
observe.sh and hydrate.sh by bare path:

    "command": ".../hestia/plugins/codex/hooks/observe.sh"

Both were 100644. On ext4 that is Permission denied, and a governance hook that
cannot execute is a governance hook that does not witness.

Run:  ./tools/shebang_exec_bit_test.py
"""

import re
import subprocess
import sys

# Mode is read from git, never from the filesystem. On the NTFS working tree the
# filesystem's answer is a fiction, and `core.filemode=false` means git will not
# even record a plain `chmod +x` there. Use `git update-index --chmod=+x <path>`
# to repair.
#
# TWO surfaces, because they can disagree and only one of them ships. The index
# is what `update-index --chmod=+x` writes; HEAD's tree is what a clone and a CI
# runner check out. `git commit <paths>` re-reads those paths from the WORKING
# TREE -- where, under core.filemode=false, the bit cannot exist -- so it lands
# 100644 in the commit and leaves the +x sitting in the index. Checking only the
# index passes on exactly that state (measured: hestia 68e50e1 -> 070c5a8), and
# the failure then surfaces in CI, whose index IS the commit. Checking only HEAD
# would miss a repair that is staged but not yet committed. So: check both.
LS_FILES = ["git", "ls-files", "-s", "-z"]
LS_TREE_HEAD = ["git", "ls-tree", "-r", "-z", "HEAD"]


def tracked_modes(repo):
    out = subprocess.run(LS_FILES, cwd=repo, capture_output=True, check=True).stdout
    for entry in out.split(b"\0"):
        if not entry:
            continue
        meta, _, path = entry.partition(b"\t")
        mode, _, _ = meta.partition(b" ")
        yield mode.decode(), path.decode()


def head_modes(repo):
    """Modes in HEAD's tree -- what a clone and a CI runner actually get.

    Returns {} when HEAD does not resolve (an empty repo, or a checkout sitting
    on an unborn branch). That is an absence of evidence, not a pass: the index
    arm still runs, and there is no commit yet for this arm to disagree with.
    """
    out = subprocess.run(LS_TREE_HEAD, cwd=repo, capture_output=True)
    if out.returncode != 0:
        return {}
    modes = {}
    for entry in out.stdout.split(b"\0"):
        if not entry:
            continue
        meta, _, path = entry.partition(b"\t")
        mode, _, _ = meta.partition(b" ")
        modes[path.decode()] = mode.decode()
    return modes


def has_shebang(repo, path):
    """Read the blob from the index, not the worktree -- the worktree may be a
    dirty or partially-checked-out state.

    `#!` alone is not enough. Rust inner attributes open with `#![cfg_attr(..)]`
    and would be swept up (app/src-tauri/src/main.rs was, on the first run of
    this test). The kernel's actual requirement is an ABSOLUTE interpreter path
    right after the bang, so that is what we match -- a structural rule rather
    than a file-extension denylist that would rot as languages are added.
    """
    blob = subprocess.run(
        ["git", "show", f":{path}"], cwd=repo, capture_output=True
    )
    if blob.returncode != 0:
        return False
    first = blob.stdout.split(b"\n", 1)[0]
    return re.match(rb"#!\s*/", first) is not None


def main():
    repo = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()

    in_head = head_modes(repo)

    offenders = []          # (path, where) -- where in {"index+HEAD", "index", "HEAD"}
    checked = 0
    for mode, path in tracked_modes(repo):
        # 120000 is a symlink, 160000 a submodule -- neither carries an exec bit.
        if mode not in ("100644", "100755"):
            continue
        if not has_shebang(repo, path):
            continue
        checked += 1
        head_mode = in_head.get(path)
        bad_index = mode == "100644"
        # A path absent from HEAD is newly added and has no HEAD arm to fail.
        bad_head = head_mode == "100644"
        if bad_index and bad_head:
            offenders.append((path, "index+HEAD"))
        elif bad_index:
            offenders.append((path, "index"))
        elif bad_head:
            offenders.append((path, "HEAD"))

    if offenders:
        print(f"FAIL  {len(offenders)}/{checked} shebang files are not executable:\n")
        width = max(len(w) for _, w in offenders)
        for path, where in offenders:
            print(f"    100644 in {where:<{width}}  {path}")

        staged_only = [p for p, w in offenders if w == "HEAD"]
        needs_chmod = [p for p, w in offenders if w != "HEAD"]

        if needs_chmod:
            print("\nRepair (a plain `chmod +x` is silently dropped when "
                  "core.filemode=false):\n")
            print("    git update-index --chmod=+x \\\n        "
                  + " \\\n        ".join(needs_chmod))
        if staged_only:
            print("\nThese are already 100755 in the index and 100644 in the commit --"
                  "\nthe mode fix is staged but was never committed, which is what"
                  "\n`git commit <paths>` does to it. Commit the index with NO"
                  "\npathspec (check `git status --short` is only yours first):\n")
            print("    git commit        # no pathspec")
            print("\n    " + "\n    ".join(staged_only))
        return 1

    scope = "index and HEAD" if in_head else "index (no HEAD to check)"
    print(f"PASS  all {checked} tracked shebang files are 100755 in the {scope}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
