#!/usr/bin/env python3
"""The rule "every number the prose asserts should be a number the run prints" was
itself written as prose, and failed the way prose fails.

THE INSTANCE. `docs/PRD_GOVERNANCE.md` §15 says "Re-checking the other 34 is the wrong
remedy". 34 was correct exactly once, at `aafe898`, where the same bullet claimed 35
citations and one of them was the one a reader had caught. The base was then corrected
twice -- 35 -> 38 at `ad57091`, then 38 -> 36 live + 3 quoted at `2b46a21` -- by two
successive fixes whose whole subject was that a number must be pinned to a ref. Both
fixes pinned the base. Neither touched the number DERIVED from it, because pinning a
number pins the number and not the arithmetic downstream of it. At `36eea3a` (blob
`fbfd654`) the doc claims 36 live citations and, one clause later, "the other 34".

WHY EVERY AVAILABLE CHECK PASSED. The census header prints:

    36 live citations (26 path-qualified + 10 bare `:NNN` continuations); 34 resolved
    over 6 files, against 71 refs under refs/remotes/origin

A reader spot-checking "34" against the run finds a 34 -- the count of citations whose
PATH resolves at the baseline, a different quantity that happens to collide. The
coincidence does not merely fail to catch the error; it manufactures corroboration for
it. This is the sixth instance of one class in this document and the first where the
wrong number had an innocent twin in the instrument's own output.

WHAT THIS FILE ASSERTS. That the remedy is mechanical rather than another sentence:

  A  a marked number that disagrees with the run is a MISMATCH, and the process exits 3
  B  ... and the identical document with the marker REMOVED exits 0, so A is
     attributable to the marker and not to anything ambient in the fixture
  C  a marked number that agrees exits 0 -- the guard is not simply always-red
  D  an unknown quantity name fails rather than silently passing, because a typo'd
     marker that no-ops is a check whose absence looks exactly like a pass
  E  the blind fraction counts unmarked numerals and does NOT count the line numbers
     inside citations, which the census proper already measures
  F  the document no longer carries an underived "the other N"

A and B together are the control pair. A alone would pass on a fixture that was red for
any reason at all -- a missing file, an unreadable ref -- so the sabotage has to be
shown to be the thing that moved the exit code.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import os
import re
import subprocess
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
CENSUS = REPO / "tools" / "citation_ref_census.py"
#: The well-known empty-tree id. git resolves it without the object existing, which
#: makes it the one tree a depth-1 CI checkout is guaranteed to have.
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

_spec = importlib.util.spec_from_file_location("citation_ref_census", CENSUS)
_census = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_census)
check_claims = _census.check_claims

# The real quantities at 36eea3a, so the unit cases are not testing round numbers that
# no document ever claimed.
REAL = {"live": 36, "qualified": 26, "continuations": 10, "quoted": 3,
        "resolved": 34, "files": 6}


def run_census(text: str) -> subprocess.CompletedProcess:
    """Run the census end to end over a throwaway document inside the repo.

    Inside the repo because the tool asks git whether its input is dirty, and a path
    outside the work tree makes that question an error rather than an answer. The
    fixture carries no citations, so no per-file ref walk happens and the run is fast.
    """
    doc = REPO / "tools" / f".census_fixture_{uuid.uuid4().hex}.md"
    doc.write_text(text, encoding="utf-8")
    try:
        return subprocess.run(
            [sys.executable, str(CENSUS), str(doc.relative_to(REPO))],
            cwd=REPO, capture_output=True, text=True,
        )
    finally:
        os.unlink(doc)


# A fixture with no citations, so every quantity the run computes is 0. A claim of 36
# is then wrong by construction rather than by a number anyone has to maintain.
SABOTAGED = "This document carries 36<!--n:live--> live citations.\n"
INERT = "This document carries 36 live citations.\n"
AGREEING = "This document carries 0<!--n:live--> live citations.\n"


def test_a_mismatch_exits_3():
    r = run_census(SABOTAGED)
    assert r.returncode == 3, f"expected exit 3, got {r.returncode}\n{r.stdout}{r.stderr}"
    assert "MISMATCH" in r.stdout
    assert "the run computes 0" in r.stdout


def test_b_the_same_fixture_without_the_marker_exits_0():
    """The control for A: prove the marker is what moved the exit code."""
    r = run_census(INERT)
    assert r.returncode == 0, f"expected exit 0, got {r.returncode}\n{r.stdout}{r.stderr}"
    assert "MISMATCH" not in r.stdout
    # ... and prove the sabotage was not a no-op at the read point: the inert fixture
    # must actually report that nothing is checked, rather than quietly checking it.
    assert "none marked" in r.stdout


def test_c_an_agreeing_claim_exits_0():
    r = run_census(AGREEING)
    assert r.returncode == 0, f"expected exit 0, got {r.returncode}\n{r.stdout}{r.stderr}"
    assert "0 <!--n:live-->  OK" in r.stdout


def test_d_unknown_quantity_fails():
    assert check_claims("34<!--n:citations-->", REAL) is False


def test_d2_known_quantity_round_trips():
    assert check_claims("36<!--n:live--> and 3<!--n:quoted-->", REAL) is True
    assert check_claims("34<!--n:live-->", REAL) is False


def claims_output(text: str) -> str:
    """check_claims prints; capture it without a pytest fixture.

    Deliberately NOT capsys: a fixture-taking test cannot run under bare `python3`,
    and this repo's CI runs `tools/*_test.py` both ways. A test that silently skips
    under one of them is a check whose absence looks like a pass.
    """
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        check_claims(text, REAL)
    return buf.getvalue()


def test_e_blind_fraction_excludes_citation_line_numbers():
    """A citation's line numbers are measured by the census; counting them as
    unchecked prose would inflate the blind fraction with the one thing that is
    checked, and an over-stated blind fraction is as misleading as an under-stated one.
    """
    # 89, 93, 94 are inside citations; only the marked 36 and nothing else remain.
    out = claims_output("see `presets.rs:89-93` and `:94` -- 36<!--n:live-->")
    assert "1 of 1 numeric tokens carry a marker; 0 are unchecked" in out

    out = claims_output("36<!--n:live--> of 71 refs over 6 files")
    assert "1 of 3 numeric tokens carry a marker; 2 are unchecked" in out


def test_f_the_document_carries_no_underived_other_n():
    doc = (REPO / "docs" / "PRD_GOVERNANCE.md").read_text(encoding="utf-8")
    bad = re.findall(r"the other (\d+)(?!<!--n:)", doc)
    assert not bad, (
        f"underived derived number(s) {bad}: a count of 'the others' is arithmetic on "
        "a number the run prints, so it must be marked or removed"
    )


def test_g_an_unresolvable_baseline_falls_back_and_says_so():
    """CI has no `refs/remotes/origin/*`, and that took the census down with a 128.

    `actions/checkout` fetches one commit and creates no remote-tracking refs, so
    `git ls-tree origin/main` raised `CalledProcessError` and the census died before
    counting anything. The failure surfaced HERE, on this file's own fixtures —
    `test_a` expected exit 3 and got 1 — which is the worst available shape: the
    instrument reported a defect in `PRD_GOVERNANCE.md` when the defect was in the
    instrument's environment, and the document it accused was correct.

    Measured 2026-08-06 on run 31079747597: the doc passed locally at the identical
    SHA and failed in CI, which is the bare-vs-CI disagreement class this repo has
    been bitten by before.
    """
    ref, note = _census.resolve_baseline("origin/definitely-not-a-ref")
    assert ref is not None, "a resolvable fallback exists here and must be found"
    assert _census.ref_resolves(ref), f"fallback {ref} must itself resolve"
    assert "fallback" in note, f"a substituted baseline must SAY it was substituted, got {note!r}"

    # And when nothing resolves at all, the answer is BLIND — never a zero, and never
    # a crash. `git_claim`'s rule, applied here: no instrument may report a zero it
    # cannot distinguish from a blind spot.
    saved = _census.BASELINE_FALLBACKS
    try:
        _census.BASELINE_FALLBACKS = ("origin/nope-a", "origin/nope-b")
        ref, tried = _census.resolve_baseline("origin/nope-c")
        assert ref is None, "no candidate resolves, so the answer must be BLIND"
        assert "origin/nope-c" in tried, "the BLIND report must name what it tried"
    finally:
        _census.BASELINE_FALLBACKS = saved


def test_h_the_ref_population_pin_moves_when_the_population_does():
    """`--doc-ref` pins what the census READS; this pins what it MEASURES AGAINST.

    A count like `25/79` has a denominator that is not in the repository: it is the
    caller's fetch and prune state. `test_g`'s CI case is the proof — 79 refs here,
    0 under `actions/checkout`, identical SHA. And it is not stable across a sitting:
    71 at `ad57091` (2026-08-05), 78 at 20:52Z on 2026-08-06, 79 at 21:15Z the same
    hour, when another seat pushed a branch mid-run.

    The case that decides whether the digest is worth anything is the THIRD one below:
    the same number of refs pointing at different commits is a different population,
    and a bare count cannot tell you so. A digest over names alone would pass the first
    two assertions and be useless for exactly the failure it exists to catch.

    Runs against a synthetic namespace, never `refs/remotes/origin`, so it neither
    depends on nor disturbs this checkout's real population.
    """
    ns = "refs/remotes/censuspintest"
    a = _census.git("rev-parse", "HEAD").strip()
    # `HEAD~1` was the second commit, but `actions/checkout` fetches depth 1, so in CI
    # there IS no HEAD~1 -- rev-parse exits 128, the same shallow-clone class 9b927fe
    # fixed in the census, one layer down. The docstring above already promises this
    # test "neither depends on nor disturbs this checkout's real population"; borrowing
    # its HISTORY violated that. The fixture needs a second distinct commit object, not
    # history -- mint one. git resolves the empty-tree id without the object existing.
    #
    # THIRD LAYER (2026-08-07, cbp). The empty tree was never the problem: minting a
    # commit needs an AUTHOR, and `actions/checkout` sets no `user.name`/`user.email`,
    # so `commit-tree` exits 128 with "empty ident name" -- byte-identical in CI and
    # under `HOME=<empty> GIT_CONFIG_GLOBAL=/dev/null`. The fix above stopped borrowing
    # the checkout's HISTORY and started borrowing its git IDENTITY CONFIG instead; the
    # sibling fixtures already say so in `tools/conflict_marker_test.py::scratch` --
    # "keep a CI runner's global config out of these repos". State the identity here.
    b = _census.git("-c", "user.name=hestia-fixture",
                    "-c", "user.email=fixture@hestia.invalid",
                    "-c", "commit.gpgsign=false",
                    "commit-tree", EMPTY_TREE,
                    "-m", "synthetic second commit for the pin fixture").strip()
    assert a != b, "fixture needs two distinct commits"
    try:
        _census.git("update-ref", f"{ns}/one", a)
        n1, d1 = _census.ref_population_pin(ns)
        n1b, d1b = _census.ref_population_pin(ns)
        assert (n1, d1) == (1, d1b) and n1b == 1, \
            f"the pin must be stable across runs on an unchanged population, got {d1} then {d1b}"

        _census.git("update-ref", f"{ns}/two", a)
        n2, d2 = _census.ref_population_pin(ns)
        assert n2 == 2 and d2 != d1, f"adding a ref must move the pin, got {d2}"

        # THE ONE THAT MATTERS. Count holds at 2; only the target moves.
        _census.git("update-ref", f"{ns}/two", b)
        n3, d3 = _census.ref_population_pin(ns)
        assert n3 == 2, f"retargeting must not change the count, got {n3}"
        assert d3 != d2, (
            "same count, different targets — the pin MUST distinguish these, or a "
            "reader quoting `n/2` cannot tell whether reproduction is expected"
        )
    finally:
        for name in ("one", "two"):
            # check=False: cleanup must run for refs that were never created, so a
            # failure before the second update-ref does not leave the first behind.
            subprocess.run(
                ["git", "update-ref", "-d", f"{ns}/{name}"],
                capture_output=True, text=True, check=False,
            )
    assert _census.remote_refs(ns) == [], "fixture refs must not survive the test"


def main() -> int:
    """Call every test BY NAME.

    A dispatch loop over `globals()` runs the same functions, and
    `tools/ci_selfexec_test.py` rejects it -- correctly. That guard reads the source
    statically to answer "does bare `python3` execute this function?", and a dynamic
    call is invisible to it. Its false alarm here would have been indistinguishable
    from the real defect it exists to catch, so the fix is to be legible to the
    checker rather than to argue with it. This list is the one thing to update when a
    test is added; the guard goes red if it is forgotten.
    """
    tests = [
        test_a_mismatch_exits_3,
        test_b_the_same_fixture_without_the_marker_exits_0,
        test_c_an_agreeing_claim_exits_0,
        test_d_unknown_quantity_fails,
        test_d2_known_quantity_round_trips,
        test_e_blind_fraction_excludes_citation_line_numbers,
        test_f_the_document_carries_no_underived_other_n,
        test_g_an_unresolvable_baseline_falls_back_and_says_so,
        test_h_the_ref_population_pin_moves_when_the_population_does,
    ]
    fails = 0
    for fn in tests:
        try:
            fn()
            print(f"ok   {fn.__name__}")
        except AssertionError as e:
            fails += 1
            print(f"FAIL {fn.__name__}: {e}")
    print(f"{fails} failure(s)")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
