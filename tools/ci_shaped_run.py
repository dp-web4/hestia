#!/usr/bin/env python3
"""Run the CI sweep in a checkout shaped like CI's, from a developer machine.

WHY THIS EXISTS -- three consecutive fixes, each green where written and red
where it ran:

  9b927fe   the census resolved `origin/main`. `actions/checkout` creates no
            `refs/remotes/origin/*`, so it exited 128 and took the instrument
            down; the instrument then blamed the DOCUMENT.
  4be4110   the pin fixture resolved `HEAD~1`. `actions/checkout` fetches
            depth 1, so there is no `HEAD~1`; 128 again, one layer down.
  ff18fe4   the replacement minted a commit with `commit-tree`. Minting needs
            an AUTHOR, and `actions/checkout` writes no `user.name`; 128
            again, one layer further down.

`ci.yml` has carried a note about this class since 2026-07-28 -- its first
firing caught its own author verifying on a machine that had a sibling
checkout CI lacked. Three fixes fell into it anyway. Prose did not stop it,
because the only environment that lacked those things was reachable ONLY BY
PUSHING: every dev host answers "is it green?" with its own history, its own
refs, and its own `~/.gitconfig` mixed in.

This makes that environment reachable locally. It is a pre-push check, not a
CI job -- CI already IS this environment, which is precisely why CI cannot be
the thing that warns you first.

WHAT IS STRIPPED, and which layer each one would have caught:

  1. history beyond depth 1         -> the `HEAD~1` 128            (4be4110)
  2. `refs/remotes/origin/*`        -> the `origin/main` 128       (9b927fe)
  3. global + system git config     -> the `commit-tree` ident 128 (ff18fe4)
  4. `$HOME` (an empty directory)   -> anything reading ~/.hestia, ~/.claude,
                                       ~/.gitconfig, ~/.cache
  5. untracked files                -> a test that only passes because a
                                       scratch tool is sitting in your tree

WHAT IS NOT STRIPPED, stated so a green is not over-read: the OS, the python
version, installed packages, network reachability, and anything the runner
image provides that this machine also provides. A green here is evidence about
the checkout, not about the machine.

Usage:
    python3 tools/ci_shaped_run.py              # whole `bare` sweep, shaped
    python3 tools/ci_shaped_run.py --only tools/citation_number_claim_test.py
    python3 tools/ci_shaped_run.py --probe /path/to/scratch_test.py
    python3 tools/ci_shaped_run.py --describe   # print the env delta, run nothing

`--probe` copies a file that is NOT in the repo into the shaped checkout and
runs only it. That is how `ci_shaped_run_test.py` proves this harness can fail:
a control that has never gone red is a claim, not a control.
"""

import argparse
import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

REPO = pathlib.Path(
    subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
)

#: Handed to every command inside the shaped checkout. `/dev/null` is git's
#: documented spelling for "this config file is empty" -- unsetting the vars
#: would let git fall back to `$HOME/.gitconfig` and `/etc/gitconfig`, which is
#: the opposite of the intent.
SHAPED_GIT_CONFIG = {
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_CONFIG_SYSTEM": "/dev/null",
}

#: Ambient identity travels in the environment as well as in config, and a
#: developer shell may carry it either way.
DROPPED_VARS = (
    "GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_AUTHOR_DATE",
    "GIT_COMMITTER_NAME", "GIT_COMMITTER_EMAIL", "GIT_COMMITTER_DATE",
    "GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE", "GIT_CONFIG",
)


def shaped_env(home: pathlib.Path) -> dict:
    env = dict(os.environ)
    for var in DROPPED_VARS:
        env.pop(var, None)
    env.update(SHAPED_GIT_CONFIG)
    env["HOME"] = str(home)
    return env


def dirty_paths() -> list[tuple[str, str]]:
    """Files this run will NOT cover, because the clone takes HEAD as committed.

    Named rather than silently dropped: a green over a checkout that omits the
    edit you are about to push is the same shape of lie this tool exists to
    refuse.

    UNTRACKED IS INCLUDED, and the first draft of this function excluded it --
    which would have hidden a brand-new test file entirely, reporting a clean
    "all N passed" for a sweep that never saw the thing being added. Uncommitted
    edits at least appear in the modified list; a new file appears nowhere.
    """
    out = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=all"],
        capture_output=True, text=True, check=True, cwd=REPO,
    ).stdout
    rows = []
    for line in out.splitlines():
        if not line.strip():
            continue
        kind = "untracked" if line.startswith("??") else "modified"
        rows.append((kind, line[3:]))
    return rows


def build_shaped_checkout(dest: pathlib.Path, home: pathlib.Path) -> str:
    """A depth-1, no-remote-refs, no-ambient-config checkout of HEAD.

    `git clone --depth` is silently ignored for a local PATH -- git says so and
    hands you the full history, which would make this tool green on exactly the
    defect it is here to catch. Fetching from a `file://` URL is the spelling
    that honours the depth, and fetching `HEAD` rather than a branch name works
    from a detached worktree, which is how most of this repo's branches are
    checked out.
    """
    env = shaped_env(home)
    dest.mkdir(parents=True, exist_ok=True)
    run = lambda *a: subprocess.run(
        ["git", *a], cwd=dest, env=env, capture_output=True, text=True, check=True)
    run("init", "-q", "-b", "main", ".")
    run("fetch", "-q", "--depth=1", f"file://{REPO}", "HEAD")
    run("checkout", "-q", "--detach", "FETCH_HEAD")
    # `actions/checkout` leaves an `origin` REMOTE but no remote-tracking refs.
    # Adding the URL without fetching reproduces that asymmetry, which is the
    # one that made `origin/main` a 128 rather than a clean "no such remote".
    origin = subprocess.run(
        ["git", "remote", "get-url", "origin"],
        cwd=REPO, capture_output=True, text=True,
    ).stdout.strip()
    if origin:
        run("remote", "add", "origin", origin)
    depth = run("rev-list", "--count", "HEAD").stdout.strip()
    head = run("rev-parse", "HEAD").stdout.strip()
    if depth != "1":
        raise RuntimeError(
            f"the shaped checkout has {depth} commits, not 1 -- the depth was not "
            "honoured, so this run would be blind to the shallow-clone class")
    return head


def discover(dest: pathlib.Path, home: pathlib.Path) -> list[str]:
    """Discovery runs INSIDE the shaped checkout, deliberately.

    `tools/ci_discovery.py` reads `git ls-files`, so asking the dev tree would
    answer for a population the shaped run does not have.
    """
    out = subprocess.run(
        [sys.executable, "tools/ci_discovery.py", "bare"],
        cwd=dest, env=shaped_env(home), capture_output=True, text=True, check=True,
    ).stdout
    return [line.strip() for line in out.splitlines() if line.strip()]


def run_sweep(tests: list[str], dest: pathlib.Path, home: pathlib.Path,
              verbose: bool) -> list[str]:
    """Run all, then report -- the same choice `ci.yml` makes, for its reason.

    Stopping on the first red hides every red after it and reports "1 failure"
    regardless of the truth, which costs one push per layer.
    """
    env = shaped_env(home)
    failed = []
    for rel in tests:
        proc = subprocess.run(
            [sys.executable, rel], cwd=dest, env=env,
            capture_output=True, text=True,
        )
        mark = "ok  " if proc.returncode == 0 else "FAIL"
        print(f"  {mark} {rel}")
        if proc.returncode != 0:
            failed.append(rel)
            tail = (proc.stdout + proc.stderr).strip().splitlines()
            for line in tail[-12:]:
                print(f"       | {line}")
        elif verbose:
            for line in proc.stdout.strip().splitlines()[-4:]:
                print(f"       | {line}")
    return failed


def describe() -> None:
    print("shaped checkout: depth-1 fetch of HEAD over file://, no refs/remotes/origin/*,")
    print("                 origin remote URL present but never fetched, tracked files only")
    print("environment:")
    for k, v in sorted(SHAPED_GIT_CONFIG.items()):
        print(f"  {k}={v}")
    print("  HOME=<fresh empty directory>")
    print(f"  unset: {', '.join(DROPPED_VARS)}")
    print("NOT shaped: OS, python version, installed packages, network.")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--only", action="append", default=[],
                    help="repo-relative test path; repeatable")
    ap.add_argument("--probe", action="append", default=[],
                    help="path to a file OUTSIDE the repo; copied in and run alone")
    ap.add_argument("--describe", action="store_true", help="print the env delta and exit")
    ap.add_argument("--verbose", action="store_true")
    ap.add_argument("--keep", action="store_true",
                    help="leave the shaped checkout on disk and print its path")
    args = ap.parse_args()

    if args.describe:
        describe()
        return 0

    root = pathlib.Path(tempfile.mkdtemp(prefix="ci-shaped-"))
    dest, home = root / "checkout", root / "home"
    home.mkdir()
    try:
        head = build_shaped_checkout(dest, home)
        print(f"shaped checkout at {head[:8]} (depth 1, no origin refs, empty HOME)")

        dirty = dirty_paths()
        if dirty:
            print(f"NOT COVERED -- {len(dirty)} file(s) absent from the shaped checkout:")
            for kind, p in dirty:
                print(f"  {'+' if kind == 'untracked' else '~'} {p}  ({kind})")
            print("  commit them first, or read this green as being about HEAD only.")

        if args.probe:
            tests = []
            for src in args.probe:
                name = f"tools/_probe_{pathlib.Path(src).name}"
                shutil.copy(pathlib.Path(src), dest / name)
                (dest / name).chmod(0o755)
                tests.append(name)
        elif args.only:
            tests = list(args.only)
        else:
            tests = discover(dest, home)
            print(f"discovered {len(tests)} test file(s) in the shaped checkout")

        if not tests:
            print("no tests selected -- refusing to report green on an empty sweep")
            return 1

        failed = run_sweep(tests, dest, home, args.verbose)
        if failed:
            print(f"FAILED {len(failed)} of {len(tests)}: {' '.join(failed)}")
            print(f"shaped checkout kept at {dest}")
            args.keep = True
            return 1
        print(f"all {len(tests)} passed in the shaped checkout")
        return 0
    finally:
        if args.keep:
            print(f"kept: {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
