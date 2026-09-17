#!/usr/bin/env python3
"""Run the two cheap landing guards against YOUR staged snapshot, before the commit.

`tools/shebang_exec_bit_test.py` is the breaker in **5 of the 12 red spells** on
`main` in the 2026-07-28..09-17 window, and an added cause in two more
(`tools/ci_red_spell_census.py census`). Its own docstring already named the
reason: "A guard that is correct but too slow to run before a push is a guard
that reports mistakes instead of preventing them." It was then made fast (one
`git cat-file --batch`). What never arrived is the thing that RUNS it before the
mistake lands. CONTRIBUTING.md documents the same intent for the boundary
scanner -- "hook-manager agnostic so it can be composed into an existing
pre-commit chain" -- and `f9f31da` tripped that scanner on `main` anyway.

So this is only the composition, plus one design decision that is the whole
point:

    IT JUDGES ONLY THE PATHS YOU STAGED.

The repo-wide guard cannot be a pre-commit hook. If `main` is already red, a
repo-wide hook blocks every unrelated commit by every seat for somebody else's
violation -- and a guard that blocks correct work gets `--no-verify` bolted onto
the muscle memory, permanently, which costs more than the red it prevented. The
staged-path scoping is what makes the honest path also the cheap one.

Exit codes: 0 clean, 1 a staged path violates, 2 misuse (not a repo, etc).

    tools/staged_guards.py            # check the staged snapshot
    tools/staged_guards.py --install  # symlink as the repo's pre-commit hook
"""
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
# Reuse, never re-derive: the shebang predicate (absolute-interpreter match against
# the INDEX blob) and the index mode reader both live in the guard that CI runs. A
# second copy here would be a second answer to "is this a script", and the two would
# drift in exactly the direction that makes the hook advisory.
from shebang_exec_bit_test import _shebang_paths, tracked_modes


def repo_root():
    out = subprocess.run(["git", "rev-parse", "--show-toplevel"],
                         capture_output=True, text=True)
    if out.returncode != 0:
        return None
    return out.stdout.strip()


def staged_paths(repo):
    """Paths added/copied/modified in the index. Deletions and renames-away cannot
    carry a mode violation into a commit, so they are not asked about."""
    out = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=ACM", "-z"],
        cwd=repo, capture_output=True, check=True).stdout
    return [p.decode() for p in out.split(b"\0") if p]


def exec_bit_offenders(staged, shebang_paths, index_modes):
    """Staged script files whose INDEX mode is 100644.

    Pure so the arms can drive it. `index_modes` is {path: mode} and
    `shebang_paths` the set of paths whose index blob opens with an absolute
    interpreter -- both read from git by the caller.
    """
    return [p for p in sorted(staged)
            if p in shebang_paths and index_modes.get(p) == "100644"]


def repair_line(offenders):
    """The repair, in the one spelling that works under core.filemode=false.

    A plain `chmod +x` is silently dropped there (the fleet's NTFS worktrees), so
    printing that would be a repair instruction that does nothing -- the failure
    mode the CI guard's own comment warns about.
    """
    return "git update-index --chmod=+x " + " ".join(offenders)


def boundary_findings(text):
    """Parse `tools/public_boundary.py`'s findings into (path, message).

    Its verdict is repo-wide even under `--cached`: it reads the whole INDEX, plus a
    manifest of binary assets. Measured in a scratch clone -- a `FAIL` there named 60+
    paths, none of them staged. Treating that rc as "your commit is bad" is the
    repo-wide-hook failure this tool exists to avoid, committed by the tool itself.
    """
    out = []
    for line in text.splitlines():
        if not line.startswith("  ") or ":" not in line:
            continue
        path, _, msg = line.strip().partition(":")
        out.append((path.strip(), msg.strip()))
    return out


def findings_on(findings, staged):
    """Only the findings naming a path in your staged set.

    A finding against the asset MANIFEST (`tools/public_binary_assets.sha256:
    untracked or missing asset <other path>`) names the manifest, not the asset --
    so it blocks only the seat that actually staged the manifest, which is correct.
    """
    s = set(staged)
    return [(p, m) for p, m in findings if p in s]


def check(repo):
    staged = staged_paths(repo)
    if not staged:
        print("staged-guards: nothing staged")
        return 0
    index_modes = {p: m for m, p in tracked_modes(repo)}
    offenders = exec_bit_offenders(staged, _shebang_paths(repo), index_modes)
    rc = 0
    if offenders:
        rc = 1
        print("staged-guards FAIL: %d staged script(s) are 100644 in the index; the "
              "shebang is a lie on any filesystem that enforces it" % len(offenders))
        for p in offenders:
            print("    100644  %s" % p)
        print("\nRepair, then re-commit:\n\n    %s\n" % repair_line(offenders))
    boundary = os.path.join(HERE, "public_boundary.py")
    if os.path.exists(boundary):
        out = subprocess.run([sys.executable, boundary, "--cached"], cwd=repo,
                             capture_output=True, text=True)
        if out.returncode != 0:
            print(out.stdout.rstrip() or out.stderr.rstrip())
            mine = findings_on(boundary_findings(out.stdout), staged)
            if mine:
                rc = 1
                print("\nstaged-guards FAIL: the boundary scanner refused %d path(s) "
                      "YOU staged:" % len(mine))
                for path, msg in mine:
                    print("    %s: %s" % (path, msg))
            else:
                print("\nstaged-guards: the boundary scanner is red, but on no path you "
                      "staged -- NOT blocking this commit. That red belongs to main "
                      "(see tools/ci_red_spell_census.py baseline).")
    if rc == 0:
        print("staged-guards: %d staged path(s) clean" % len(staged))
    return rc


HOOK = """#!/usr/bin/env sh
# Installed by tools/staged_guards.py --install. Judges only the paths you staged.
# Bypass for a genuine emergency: git commit --no-verify
exec python3 "$(git rev-parse --show-toplevel)/tools/staged_guards.py"
"""


def install(repo):
    """Write the hook into the COMMON git dir, so every worktree of this clone is
    covered by one install.

    Refuses to clobber an existing hook: the machine on this fleet already runs a
    global `core.hooksPath` dispatcher that delegates to the repo's hook of the
    same name, and silently replacing that delegate is how installing a guard
    becomes an unwitnessed change to somebody else's publication behaviour.
    """
    common = subprocess.run(["git", "rev-parse", "--git-common-dir"], cwd=repo,
                            capture_output=True, text=True, check=True).stdout.strip()
    if not os.path.isabs(common):
        common = os.path.join(repo, common)
    hooks = os.path.join(common, "hooks")
    os.makedirs(hooks, exist_ok=True)
    path = os.path.join(hooks, "pre-commit")
    if os.path.exists(path):
        cur = open(path).read()
        if "staged_guards.py" not in cur:
            print("REFUSING: %s already exists and is not ours. Compose it by hand:\n"
                  "    python3 tools/staged_guards.py || exit 1" % path)
            return 2
    with open(path, "w") as fh:
        fh.write(HOOK)
    os.chmod(path, 0o755)
    print("installed %s (covers every worktree of this clone)" % path)
    return 0


def main(argv):
    repo = repo_root()
    if not repo:
        print("staged-guards: not a git repository")
        return 2
    if "--install" in argv:
        return install(repo)
    return check(repo)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
