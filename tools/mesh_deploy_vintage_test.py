#!/usr/bin/env python3
"""Fixture arms for the half of `mesh_deploy_vintage.py` that had none.

WHY THIS FILE EXISTS. The tool shipped with no test at all, and its two halves
answered the same question two different ways. The seat loop asks the byte
question -- "do the bytes this watcher will exec on its next fire differ from the
merged bytes" -- and says so in a comment. The stranded list asked the COMMIT
question, `git log HEAD..origin/main -- plugins/member-mesh`, and called the
answer "not in the executing tree".

Those diverge on exactly one state, and it is the state a seat reaches by doing
the right thing. `git checkout origin/main -- plugins/member-mesh` on a shared
tree parked on someone else's feature branch deploys the fix without moving
anyone's HEAD. Measured on CBP 2026-09-20, the tool then printed "IN FORCE,
drift=none" for all three seats and "merged and NOT executing: 1" four lines
later, about the same commit (40903d6, #1081) -- and it is the second line that
`--primer-banner` pastes into every wake prompt, for every seat, every fire.

A banner that cries stranded at a deployed mesh is not a cosmetic defect. This
tool's own rule is that "a banner on the healthy path is noise, and noise is what
gets filtered out right before the one time it mattered"; a permanent false alarm
is how that filtering gets learned. The failure direction that matters is the
other one, so every arm below also pins that a witness which FAILS over-reports.

The arms are real git repositories rather than mocks, because the defect lived in
what `git log` means, and a mock of `git log` would have encoded the same
misunderstanding that produced the bug.
"""
import os
import subprocess
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from mesh_deploy_vintage import (  # noqa: E402
    MESH_DIR, classify_stranded, primer_banner, undeployed_files,
)

FIRE = os.path.join(MESH_DIR, "fire-x.sh")


def _git(repo, *args):
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    r = subprocess.run(["git", "-C", repo] + list(args),
                       capture_output=True, text=True, env=env)
    if r.returncode != 0:
        raise AssertionError(f"git {args} failed in {repo}: {r.stderr}")
    return r.stdout.strip()


def _write(repo, rel, text):
    path = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)


def fixture(tmp):
    """A shared tree on an unmerged feature branch, with one mesh fix on main.

    Returns the repo path. State on return is the REAL one from 2026-09-20: the
    tree sits on `feature`, and main carries a mesh commit `feature` does not.
    The worktree still holds the OLD bytes, so the fix is genuinely un-deployed.
    """
    repo = os.path.join(tmp, "repo")
    os.makedirs(repo)
    _git(repo, "init", "-q", "-b", "main")
    _write(repo, FIRE, "v1\n")
    _write(repo, "README.md", "r\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "base")
    _git(repo, "branch", "feature")
    # The merged mesh fix, on main only.
    _write(repo, FIRE, "v2\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "mesh: the fix that must reach the seats")
    _git(repo, "update-ref", "refs/remotes/origin/main", _git(repo, "rev-parse", "main"))
    # ...and a commit main has that does NOT touch the mesh, so the arms below
    # also pin that the classifier is scoped to MESH_DIR rather than to "main is
    # ahead" -- the tree being behind is not by itself a mesh deployment fact.
    _write(repo, "README.md", "r2\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "docs: unrelated")
    _git(repo, "update-ref", "refs/remotes/origin/main", _git(repo, "rev-parse", "main"))
    _git(repo, "checkout", "-q", "feature")
    # A commit of its OWN, so `feature` is genuinely unmerged rather than merely
    # behind. This is not cosmetic: primer_banner() has two loud arms, and a
    # branch that is an ancestor of main takes the "ALREADY MERGED" one. The tree
    # on CBP was mid-review with commits of its own, so the arm these fixtures
    # must exercise is the quiet "someone may be mid-feature" one.
    _write(repo, "README.md", "feature work\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "wip: someone is mid-feature")
    return repo


def _deploy_by_file(repo):
    """The targeted deploy: main's bytes, nobody's HEAD moved."""
    _git(repo, "checkout", "origin/main", "--", MESH_DIR)


def _absent(repo):
    return [
        dict(zip(("sha", "subject"), ln.split(" ", 1)))
        for ln in _git(repo, "log", "HEAD..origin/main", "--format=%h %s",
                       "--", MESH_DIR).splitlines() if " " in ln
    ]


def test_stale_tree_is_stranded():
    """The arm that always worked. Bytes differ -> loud, and it must stay loud."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = fixture(tmp)
        stranded, off = classify_stranded(repo, _absent(repo))
        assert len(stranded) == 1, stranded
        assert off == [], off
        b = primer_banner(repo)
        assert "NOT in force here" in b, b
        assert "merged and NOT executing" in b, b


def test_file_deployed_fix_is_not_stranded():
    """The load-bearing one: the state the old code got backwards.

    Same HEAD, same `git log HEAD..origin/main` -- only the bytes changed. The
    commit-derived answer cannot tell these two arms apart; that is the bug.
    """
    with tempfile.TemporaryDirectory() as tmp:
        repo = fixture(tmp)
        before = _absent(repo)
        _deploy_by_file(repo)
        assert _absent(repo) == before, "the commit graph must be UNCHANGED by a deploy"
        stranded, off = classify_stranded(repo, _absent(repo))
        assert stranded == [], f"deployed bytes reported as stranded: {stranded}"
        assert len(off) == 1, off


def test_file_deployed_fix_still_warns_that_it_is_unheld():
    """Not stranded is not healthy. Silence here would be the opposite error:
    the next checkout of this shared tree reverts the deploy and no commit
    records that it ever happened."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = fixture(tmp)
        _deploy_by_file(repo)
        b = primer_banner(repo)
        assert b, "a by-file deploy must not render an empty banner"
        assert "by FILE, not by branch" in b, b
        assert "Nothing is un-deployed right now" in b, b
        # It must NOT claim the fix is not executing -- that was the false alarm.
        assert "NOT executing" not in b, b


def test_unstaged_deploy_is_still_deployed():
    """The one the first fix got wrong, one layer down.

    `git checkout origin/main -- <MESH_DIR>` STAGES what it restores, and leaving
    it staged in a shared tree is how a co-seat's unrelated `git commit` sweeps it
    up. So the right follow-up is `git restore --staged` -- which turns a newly
    deployed file that main tracks and this branch does not into an UNTRACKED one.
    Its bytes are still main's and still the bytes that exec; only git's index has
    an opinion. An index-mediated comparison (`git diff --name-only origin/main`)
    calls that path deleted and re-strands the commit, which is the original false
    alarm restored by its own repair (CBP, 2026-09-20).
    """
    with tempfile.TemporaryDirectory() as tmp:
        repo = fixture(tmp)
        roster = os.path.join(MESH_DIR, "MEMBERS")
        _git(repo, "checkout", "-q", "main")
        _write(repo, roster, "cbp-being\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "mesh: a roster this branch has never tracked")
        _git(repo, "update-ref", "refs/remotes/origin/main", _git(repo, "rev-parse", "main"))
        _git(repo, "checkout", "-q", "feature")
        _deploy_by_file(repo)
        _git(repo, "restore", "--staged", MESH_DIR)
        assert "??" in _git(repo, "status", "-s", "--", roster), "fixture: not untracked"
        assert undeployed_files(repo) == set(), undeployed_files(repo)
        stranded, off = classify_stranded(repo, _absent(repo))
        assert stranded == [], f"unstaged-but-deployed bytes reported stranded: {stranded}"
        assert len(off) == 2, off


def test_absent_file_is_undeployed():
    """The safe direction of the same question: a file main has that is NOT on
    disk is undeployed, and the commit carrying it stays loud. Deleting is not
    deploying, and main's `fire-*.sh` abort the fire when MEMBERS is missing."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = fixture(tmp)
        _deploy_by_file(repo)
        os.remove(os.path.join(repo, FIRE))
        assert undeployed_files(repo) == {FIRE}, undeployed_files(repo)
        stranded, _ = classify_stranded(repo, _absent(repo))
        assert len(stranded) == 1, stranded


def test_partial_deploy_is_still_stranded():
    """One file of a multi-file commit restored is NOT a deploy. The classifier
    asks whether ANY touched file still differs, so a half-finished checkout
    keeps the commit loud rather than crediting it to the survivor."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = fixture(tmp)
        second = os.path.join(MESH_DIR, "MEMBERS")
        _git(repo, "checkout", "-q", "main")
        _write(repo, second, "cbp-being\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "-qm", "mesh: roster + template, together")
        _write(repo, FIRE, "v3\n")
        _git(repo, "add", "-A")
        _git(repo, "commit", "--amend", "-qm", "mesh: roster + template, together")
        _git(repo, "update-ref", "refs/remotes/origin/main", _git(repo, "rev-parse", "main"))
        _git(repo, "checkout", "-q", "feature")
        _git(repo, "checkout", "origin/main", "--", second)   # only half of it
        stranded, off = classify_stranded(repo, _absent(repo))
        subjects = [c["subject"] for c in stranded]
        assert "mesh: roster + template, together" in subjects, (stranded, off)


def test_tree_on_main_says_nothing():
    """The silent arm. Nothing merged is absent -> no banner at all."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = fixture(tmp)
        _git(repo, "checkout", "-q", "main")
        assert _absent(repo) == []
        assert primer_banner(repo) == "", primer_banner(repo)


def test_unrelated_commits_do_not_strand_the_mesh():
    """Main being ahead is not a mesh deployment fact. The `docs:` commit in the
    fixture must never appear in either list."""
    with tempfile.TemporaryDirectory() as tmp:
        repo = fixture(tmp)
        _deploy_by_file(repo)
        stranded, off = classify_stranded(repo, _absent(repo))
        for c in stranded + off:
            assert not c["subject"].startswith("docs:"), c


def test_a_failed_witness_over_reports():
    """The direction that must never invert. If the deployment diff cannot be
    taken, every absent commit stays stranded -- `git()` returning '' on failure
    would otherwise read as 'no file differs', i.e. as a fully deployed mesh, and
    would silence the banner on the exact tree it exists to warn about."""
    missing = "/nonexistent-repo-for-mesh-deploy-vintage-test"
    assert undeployed_files(missing) is None
    absent = [{"sha": "deadbee", "subject": "mesh: a fix nobody can measure"}]
    stranded, off = classify_stranded(missing, absent)
    assert stranded == absent, stranded
    assert off == [], off


TESTS = [
    test_stale_tree_is_stranded,
    test_file_deployed_fix_is_not_stranded,
    test_file_deployed_fix_still_warns_that_it_is_unheld,
    test_unstaged_deploy_is_still_deployed,
    test_absent_file_is_undeployed,
    test_partial_deploy_is_still_stranded,
    test_tree_on_main_says_nothing,
    test_unrelated_commits_do_not_strand_the_mesh,
    test_a_failed_witness_over_reports,
]


if __name__ == "__main__":
    defined = {k for k in globals() if k.startswith("test_")}
    listed = {t.__name__ for t in TESTS}
    if defined != listed:
        # An explicit list can go stale. Make that RED, not a silently smaller run.
        print(f"FAIL TESTS is stale: defined-not-listed={sorted(defined - listed)} "
              f"listed-not-defined={sorted(listed - defined)}")
        raise SystemExit(1)
    for f in TESTS:
        f()
        print("ok", f.__name__)
    print(f"{len(TESTS)} passed")
