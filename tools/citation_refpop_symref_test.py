#!/usr/bin/env python3
"""`refpop` told two identical clones they were measuring different things.

THE INSTANCE. `ref_population_pin` exists so a second reader can tell "I disagree with
your number" from "I am not measuring the same population". It digests
`for-each-ref refs/remotes/origin`. That pattern also matches
`refs/remotes/origin/HEAD` -- a SYMBOLIC ref, an alias for the default branch rather
than a member of the population, which `%(refname:short)` renders as the bare `origin`.

A clone that carries one therefore reports N+1 refs, one extra hit on every anchor the
default branch satisfies, and a DIFFERENT digest -- with no commit anywhere. Whether a
clone carries it is not a property of its content: `git clone` creates it, and the
fleet's shared checkouts do not have one.

So the pin fired on a pair of clones holding byte-identical refs and told the reader
reproduction was not expected. That is worse than the bare count it replaced. A count
that is merely wrong gets checked; disagreement wearing a proof gets believed. This was
measured across seats before it was fixed: kimi's fresh-clone row (82 refs, 28/82 and
49/82) is this artifact, and collapses onto the shared-clone row (81, 27/81, 48/81)
once symbolic refs are dropped.

WHAT THIS FILE ASSERTS.

  A  two clones of one remote, differing ONLY by `refs/remotes/origin/HEAD`, agree in
     both N and refpop
  B  ... and the same pair DISAGREES under the unfiltered predicate, so A is
     attributable to the filter and not to the fixture being trivially identical
  C  the filter is INERT where no symbolic ref exists -- N and refpop are unchanged,
     so old figures taken on symref-free clones remain comparable

B is the load-bearing one. Without it this file would still pass if `ref_population_pin`
were replaced by `return (0, "")`.

NOT ASSERTED, and deliberately: that refpop is now reproducible. It is not. A ref that
MOVES is reconstructible from its reflog; a ref that arrives or is pruned takes its
reflog with it and is not reconstructible by anyone. The pin detects drift. It does not
undo it.
"""

import hashlib
import importlib.util
import os
import pathlib
import subprocess
import sys
import tempfile

CENSUS = pathlib.Path(__file__).resolve().parent / "citation_ref_census.py"


def _load():
    spec = importlib.util.spec_from_file_location("citation_ref_census", CENSUS)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args],
                          capture_output=True, text=True, check=True).stdout


def _unfiltered_pin(cwd):
    """The predicate as it stood before the fix -- transcribed, not imported.

    Imported, it would silently become whatever the fixed version does and B would
    stop discriminating. A control has to contain the change it is controlling for.
    """
    out = _git(cwd, "for-each-ref", "--format=%(refname:short) %(objectname)",
               "refs/remotes/origin")
    pairs = sorted(p for p in out.split("\n") if p.strip())
    return len(pairs), hashlib.sha256("\n".join(pairs).encode()).hexdigest()[:12]


def _fixture(root):
    """An upstream with two branches, and two clones of it that differ by one symref."""
    up = root / "up"
    up.mkdir(parents=True)
    _git(up, "init", "-q", ".")
    _git(up, "config", "user.email", "t@example.invalid")
    _git(up, "config", "user.name", "t")
    (up / "f").write_text("a\n")
    _git(up, "add", "f")
    _git(up, "commit", "-qm", "one")
    _git(up, "branch", "feature")

    subprocess.run(["git", "clone", "-q", str(up), str(root / "with")], check=True)
    subprocess.run(["git", "clone", "-q", str(up), str(root / "without")], check=True)
    _git(root / "without", "symbolic-ref", "--delete", "refs/remotes/origin/HEAD")
    return root / "with", root / "without"


def _content(cwd):
    """Non-symbolic (name, target) pairs -- what the two clones must share."""
    out = _git(cwd, "for-each-ref",
               "--format=%(refname:short)|%(objectname)|%(symref)",
               "refs/remotes/origin")
    keep = []
    for line in out.splitlines():
        if not line.strip():
            continue
        name, obj, symref = line.split("|")
        if not symref:
            keep.append((name, obj))
    return sorted(keep)


def test_symref_does_not_split_identical_clones():
    census = _load()
    with tempfile.TemporaryDirectory() as td:
        wit, without = _fixture(pathlib.Path(td))

        # The fixture's own premise, asserted rather than assumed: if these two ever
        # stop being content-identical, A becomes vacuous and C becomes a coincidence.
        assert _content(wit) == _content(without), "fixture clones differ in content"
        assert _git(wit, "symbolic-ref", "refs/remotes/origin/HEAD").strip(), \
            "fixture lost the symbolic ref the test is about"

        # B -- the pair IS discriminating under the old predicate.
        old_with, old_without = _unfiltered_pin(wit), _unfiltered_pin(without)
        assert old_with != old_without, (
            "positive control failed: the unfiltered predicate already agreed, so "
            "this fixture cannot demonstrate the fix"
        )
        assert old_with[0] == old_without[0] + 1, (old_with, old_without)

        # A -- and the fix closes it, in BOTH the count and the digest.
        cwd = os.getcwd()
        try:
            os.chdir(wit)
            new_with = census.ref_population_pin("refs/remotes/origin")
            os.chdir(without)
            new_without = census.ref_population_pin("refs/remotes/origin")
        finally:
            os.chdir(cwd)
        assert new_with == new_without, (new_with, new_without)

        # ... and it converged on the population, not on the alias.
        assert new_with == old_without, (
            "the filter changed the symref-free clone's answer; it should only ever "
            f"remove the alias: {new_with} vs {old_without}"
        )


def test_filter_is_inert_without_a_symbolic_ref():
    """C -- a clone with no symref must be measured exactly as before the fix."""
    census = _load()
    with tempfile.TemporaryDirectory() as td:
        _, without = _fixture(pathlib.Path(td))
        cwd = os.getcwd()
        try:
            os.chdir(without)
            assert census.ref_population_pin("refs/remotes/origin") == \
                _unfiltered_pin(without)
            # The enumeration too -- `remote_refs` feeds every `n/N` numerator, and a
            # filter that silently dropped a real ref would leave the digest test above
            # green while every count below it moved.
            unfiltered = _git(without, "for-each-ref", "--format=%(refname:short)",
                              "refs/remotes/origin").split()
            assert sorted(census.remote_refs("refs/remotes/origin")) == sorted(unfiltered)
        finally:
            os.chdir(cwd)


def _main():
    failures = 0
    # Enumerate, don't discover. A `sorted(globals().items())` loop runs the same
    # functions, but no Name ever loads them, and tools/ci_selfexec_test.py's
    # inert-function guard -- an AST scan for references, correctly unable to see a
    # globals() dispatch -- flags them as dead code. Name them.
    for fn in (test_symref_does_not_split_identical_clones,
               test_filter_is_inert_without_a_symbolic_ref):
        name = fn.__name__
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as exc:
            failures += 1
            print(f"FAIL {name}: {exc}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_main())
