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

# Mode is read from the git INDEX, never from the filesystem. On the NTFS
# working tree the filesystem's answer is a fiction, and `core.filemode=false`
# means git will not even record a plain `chmod +x` there. Use
# `git update-index --chmod=+x <path>` to repair.
LS_FILES = ["git", "ls-files", "-s", "-z"]


def tracked_modes(repo):
    out = subprocess.run(LS_FILES, cwd=repo, capture_output=True, check=True).stdout
    for entry in out.split(b"\0"):
        if not entry:
            continue
        meta, _, path = entry.partition(b"\t")
        mode, _, _ = meta.partition(b" ")
        yield mode.decode(), path.decode()


def has_shebang(repo, path):
    """Read the blob from the index, not the worktree -- the worktree may be a
    dirty or partially-checked-out state, and the index is what a clone gets.

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

    offenders = []
    checked = 0
    for mode, path in tracked_modes(repo):
        # 120000 is a symlink, 160000 a submodule -- neither carries an exec bit.
        if mode not in ("100644", "100755"):
            continue
        if not has_shebang(repo, path):
            continue
        checked += 1
        if mode == "100644":
            offenders.append(path)

    if offenders:
        print(f"FAIL  {len(offenders)}/{checked} shebang files are not executable "
              f"in the git index:\n")
        for path in offenders:
            print(f"    100644  {path}")
        print("\nRepair (a plain `chmod +x` is silently dropped when "
              "core.filemode=false):\n")
        print("    git update-index --chmod=+x \\\n        "
              + " \\\n        ".join(offenders))
        return 1

    print(f"PASS  all {checked} tracked shebang files are 100755 in the index")
    return 0


if __name__ == "__main__":
    sys.exit(main())
