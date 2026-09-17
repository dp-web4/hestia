#!/usr/bin/env python3
"""Pins what tools/staged_guards.py judges, and -- load-bearing -- what it does NOT.

The interesting arms are the negative ones. A pre-commit guard that fails on a
violation somebody else already landed blocks correct work, and the next thing
that happens is `--no-verify` in the muscle memory of every seat. So: an
offender that is tracked but NOT staged must pass, and that is pinned twice --
once on the predicate, once end-to-end in a real temporary repository.
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from staged_guards import check, exec_bit_offenders, repair_line, staged_paths


def test_a_staged_script_at_100644_is_an_offender():
    off = exec_bit_offenders(["tools/x.py"], {"tools/x.py"}, {"tools/x.py": "100644"})
    assert off == ["tools/x.py"], off


def test_a_staged_script_already_100755_is_clean():
    assert exec_bit_offenders(["tools/x.py"], {"tools/x.py"},
                              {"tools/x.py": "100755"}) == []


def test_a_staged_non_script_is_not_asked_about():
    """No shebang, no claim to be executable. `README.md` at 100644 is correct."""
    assert exec_bit_offenders(["README.md"], set(), {"README.md": "100644"}) == []


def test_somebody_elses_unstaged_offender_does_not_block_your_commit():
    """THE arm. The repo-wide guard fails here; this one must not -- otherwise a red
    main blocks every seat's unrelated commit and the hook gets bypassed for good."""
    assert exec_bit_offenders(["docs/a.md"], {"tools/theirs.py"},
                              {"tools/theirs.py": "100644",
                               "docs/a.md": "100644"}) == []


def test_offenders_are_sorted_so_the_repair_line_is_stable():
    off = exec_bit_offenders(["b.py", "a.py"], {"a.py", "b.py"},
                             {"a.py": "100644", "b.py": "100644"})
    assert off == ["a.py", "b.py"], off


def test_the_repair_is_update_index_not_chmod():
    """Under core.filemode=false (the fleet's NTFS worktrees) a plain chmod +x is
    silently dropped, so printing it would be an instruction that does nothing."""
    line = repair_line(["tools/a.py", "tools/b.py"])
    assert line == "git update-index --chmod=+x tools/a.py tools/b.py", line
    assert "chmod +x" not in line


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=repo, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _repo(td):
    _git(td, "init", "-q")
    _git(td, "config", "user.email", "t@example.invalid")
    _git(td, "config", "user.name", "t")
    _git(td, "config", "commit.gpgsign", "false")
    return td


def test_end_to_end_a_staged_script_fails_and_the_repair_clears_it():
    with tempfile.TemporaryDirectory() as td:
        repo = _repo(td)
        path = os.path.join(repo, "run.sh")
        with open(path, "w") as fh:
            fh.write("#!/usr/bin/env bash\necho hi\n")
        os.chmod(path, 0o644)
        _git(repo, "add", "run.sh")
        _git(repo, "update-index", "--chmod=-x", "run.sh")
        assert staged_paths(repo) == ["run.sh"], staged_paths(repo)
        assert check(repo) == 1
        _git(repo, "update-index", "--chmod=+x", "run.sh")
        assert check(repo) == 0


def test_end_to_end_an_already_committed_offender_does_not_fail_a_later_commit():
    """A violation that is already in HEAD is CI's problem, not this commit's."""
    with tempfile.TemporaryDirectory() as td:
        repo = _repo(td)
        with open(os.path.join(repo, "bad.sh"), "w") as fh:
            fh.write("#!/bin/sh\ntrue\n")
        _git(repo, "add", "bad.sh")
        _git(repo, "update-index", "--chmod=-x", "bad.sh")
        _git(repo, "commit", "-q", "-m", "land the offender")
        with open(os.path.join(repo, "notes.md"), "w") as fh:
            fh.write("unrelated\n")
        _git(repo, "add", "notes.md")
        assert check(repo) == 0


def test_end_to_end_nothing_staged_is_not_a_failure():
    with tempfile.TemporaryDirectory() as td:
        assert check(_repo(td)) == 0


TESTS = [
    test_a_staged_script_at_100644_is_an_offender,
    test_a_staged_script_already_100755_is_clean,
    test_a_staged_non_script_is_not_asked_about,
    test_somebody_elses_unstaged_offender_does_not_block_your_commit,
    test_offenders_are_sorted_so_the_repair_line_is_stable,
    test_the_repair_is_update_index_not_chmod,
    test_end_to_end_a_staged_script_fails_and_the_repair_clears_it,
    test_end_to_end_an_already_committed_offender_does_not_fail_a_later_commit,
    test_end_to_end_nothing_staged_is_not_a_failure,
]


if __name__ == "__main__":
    defined = {k for k in globals() if k.startswith("test_")}
    listed = {t.__name__ for t in TESTS}
    if defined != listed:
        # An explicit list can go stale. Make that RED, not a silently smaller run.
        print("FAIL TESTS is stale: defined-not-listed=%s listed-not-defined=%s"
              % (sorted(defined - listed), sorted(listed - defined)))
        raise SystemExit(1)
    for f in TESTS:
        f()
        print("ok", f.__name__)
    print("%d passed" % len(TESTS))
