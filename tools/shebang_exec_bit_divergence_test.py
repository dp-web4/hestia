#!/usr/bin/env python3
"""The exec-bit gauge must read the surface that ships, not only the one it writes.

`shebang_exec_bit_test.py` used to read the git INDEX alone, with a comment
asserting "the index is what a clone gets". That is false. A clone -- and a CI
runner -- gets HEAD's tree. The two disagree in a state this fleet produces
routinely:

    git update-index --chmod=+x tools/probe.py   # index: 100755
    git commit tools/probe.py -m ...             # re-reads the WORKING TREE,
                                                 # where core.filemode=false
                                                 # means the bit cannot exist
    -> commit lands 100644, the +x stays staged in the index

An index-only gauge PASSES on that state while the pushed commit is wrong, so
the failure surfaces two minutes into CI -- whose index IS the commit -- long
after the author has moved on. Measured on hestia 68e50e1 -> 070c5a8, and again
on 2026-08-08 when PRs #283, #289 and #290 went red on three different members'
files in one night.

This test fires all four arms against the real gauge. The HEAD arm is the one
that was blind; ARM 1 is the regression that matters. Arms 0 and 3 are the
negative controls -- a gauge that simply failed everything would pass ARM 1 and
ARM 2 while being useless, so both directions are asserted.

Run:  ./tools/shebang_exec_bit_divergence_test.py
"""

import subprocess
import sys
import tempfile
from pathlib import Path

GAUGE = Path(__file__).resolve().parent / "shebang_exec_bit_test.py"

SHEBANG = "#!/usr/bin/env python3\nprint(1)\n"


def git(repo, *args, check=True):
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=check
    )


def new_repo(tmp):
    """A repo that reproduces the fleet's filesystem: core.filemode=false, so a
    plain `chmod +x` is discarded and only `update-index` can record a mode."""
    repo = Path(tmp)
    git(repo, "init", "-q", ".")
    git(repo, "config", "core.filemode", "false")
    git(repo, "config", "user.email", "test@example.invalid")
    git(repo, "config", "user.name", "exec bit test")
    git(repo, "config", "commit.gpgsign", "false")
    (repo / "tools").mkdir()
    (repo / "tools" / "probe.py").write_text(SHEBANG)
    git(repo, "add", "tools/probe.py")
    git(repo, "update-index", "--chmod=+x", "tools/probe.py")
    return repo


def modes(repo, path):
    idx = git(repo, "ls-files", "-s", path).stdout.split()
    head = git(repo, "ls-tree", "HEAD", "--", path, check=False).stdout.split()
    return (idx[0] if idx else None), (head[0] if head else None)


def run_gauge(repo):
    out = subprocess.run(
        [sys.executable, str(GAUGE)], cwd=repo, capture_output=True, text=True
    )
    return out.returncode, out.stdout + out.stderr


def check(name, got_rc, want_rc, state, detail, out):
    ok = got_rc == want_rc
    print(f"{'PASS' if ok else 'FAIL'}  {name}")
    print(f"        state: {state}")
    print(f"        want rc={want_rc}  got rc={got_rc}  ({detail})")
    if not ok:
        print("        --- gauge output ---")
        for line in out.strip().splitlines():
            print(f"        {line}")
    return ok


def main():
    results = []

    # ARM 3 first: an unborn HEAD must not be read as a failure. Absence of a
    # commit is absence of evidence for the HEAD arm, not evidence against.
    with tempfile.TemporaryDirectory() as tmp:
        repo = new_repo(tmp)
        rc, out = run_gauge(repo)
        results.append(check(
            "ARM 3 unborn HEAD -> index-only, PASS",
            rc, 0, "index=100755 HEAD=(none)",
            "no commit yet; the HEAD arm has nothing to disagree with", out,
        ))

    with tempfile.TemporaryDirectory() as tmp:
        repo = new_repo(tmp)
        git(repo, "commit", "-qm", "base")

        # ARM 0 -- negative control. Both surfaces correct.
        state = "index=%s HEAD=%s" % modes(repo, "tools/probe.py")
        rc, out = run_gauge(repo)
        results.append(check(
            "ARM 0 index=755 HEAD=755 -> PASS",
            rc, 0, state, "negative control: a gauge that fails here is useless", out,
        ))

        # ARM 1 -- THE REGRESSION. Mode repaired in the index, reverted in the
        # commit. This is precisely what `git commit <paths>` leaves behind, and
        # precisely what the index-only gauge could not see.
        git(repo, "update-index", "--chmod=-x", "tools/probe.py")
        git(repo, "commit", "-q", "-m", "drop the bit in the commit")
        git(repo, "update-index", "--chmod=+x", "tools/probe.py")
        state = "index=%s HEAD=%s" % modes(repo, "tools/probe.py")
        rc, out = run_gauge(repo)
        ok = check(
            "ARM 1 index=755 HEAD=644 -> FAIL  (the blind spot)",
            rc, 1, state, "staged but never committed; CI checks out HEAD", out,
        )
        # The diagnosis must name HEAD, not send the author back to a chmod that
        # is already done -- a correct verdict with the wrong remedy still loops.
        if ok and "HEAD" not in out:
            print("        FAIL  verdict is right but the remedy never names HEAD")
            ok = False
        results.append(ok)

        # ARM 2 -- never repaired on either surface.
        git(repo, "update-index", "--chmod=-x", "tools/probe.py")
        state = "index=%s HEAD=%s" % modes(repo, "tools/probe.py")
        rc, out = run_gauge(repo)
        results.append(check(
            "ARM 2 index=644 HEAD=644 -> FAIL",
            rc, 1, state, "the original defect; must still be caught", out,
        ))

    print()
    if all(results):
        print(f"GREEN  {len(results)}/{len(results)} arms")
        return 0
    print(f"RED    {sum(results)}/{len(results)} arms")
    return 1


if __name__ == "__main__":
    sys.exit(main())
