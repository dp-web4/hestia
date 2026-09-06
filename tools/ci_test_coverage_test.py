#!/usr/bin/env python3
"""Every test-shaped file is either RUN by CI or DECLARED unrunnable, with a reason.

The gate built in #78 and extended in #109 is a glob, and the comment above it
says so: "the glob is the gate". That is true about *discovery* and silent about
*coverage*. Both jobs refuse a glob matching ZERO -- and neither can notice a
glob matching seven of nine. A file that misses the naming convention by
prefix-vs-suffix is not discovered, not run, and not reported. It is absent, and
absence was read as pass.

Found by auditing a single dismissed clause. kimi re-ran this repo's plugin
tests and got 10 where CI runs 7, and we both wrote that off as "discovery
scope, not a disagreement". It was not a difference of opinion about scope. The
wider number was the right one, and the gap was larger than either count:
SEVEN of sixteen test-shaped files ran in no job at all --

    plugin-sdk/python/tests/conformance/test_conformance.py
    plugin-sdk/python/tests/test_smoke.py
    plugins/agent-inventory/test_inventory.py
    plugins/lib/tests/test_path_scope.py          (21 assertions, path scope)
    plugins/reviewer/test_discover_prs.py         (shipped ungated in #92)
    tools/shebang_exec_bit_test.py
    tools/public_boundary_test.py

-- because the repo carries two naming conventions and each job's glob was
blind to the other's.

This test does NOT require that everything run in CI. Three files legitimately
cannot today. It requires that the not-running set be WRITTEN DOWN with a
reason, so the gap is declared rather than accidental. An undeclared orphan is
the failure; a declared one is a decision someone made in a sentence.

ANCHORING: there is no local copy of CI's globs to drift. Discovery lives in
tools/ci_discovery.py, CI *calls* that module, and this test *imports* it. What
is still asserted below is that ci.yml really does invoke it -- because if CI
stops calling the module, every verdict here becomes a statement about code
nothing runs. A check whose only evidence is its own samples goes green when
all of them are wrong the same way.

Run:  python3 tools/ci_test_coverage_test.py
"""

import importlib.util
import pathlib
import subprocess
import sys

REPO = pathlib.Path(
    subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
)

CI = REPO / ".github" / "workflows" / "ci.yml"
MANIFEST = REPO / "tools" / "ci_excluded_tests.txt"

_spec = importlib.util.spec_from_file_location(
    "ci_discovery", REPO / "tools" / "ci_discovery.py")
D = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(D)

MIN_REASON_CHARS = 60

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if not ok:
        FAILS.append(f"{name}{': ' + detail if detail else ''}")


def manifest_reasons() -> dict[str, str]:
    """Path -> the comment block directly above it in the manifest."""
    reasons: dict[str, str] = {}
    buf: list[str] = []
    for raw in MANIFEST.read_text(encoding="utf-8").splitlines():
        s = raw.strip()
        if not s:
            buf = []
        elif s.startswith("#"):
            buf.append(s.lstrip("#").strip())
        else:
            reasons[s] = " ".join(buf).strip()
            buf = []
    return reasons


def test_ci_actually_calls_the_discovery_module():
    """If CI stops calling it, everything below is about dead code."""
    ci = CI.read_text(encoding="utf-8")
    check("ci.yml invokes tools/ci_discovery.py",
          "tools/ci_discovery.py" in ci,
          "ci.yml no longer references the discovery module -- this test is "
          "reasoning about code CI does not run, and its green means nothing")
    check("ci.yml consumes the 'bare' mode", "ci_discovery.py bare" in ci,
          "the plugin tests job no longer asks for the bare-python list")
    check("ci.yml consumes the 'hooks' mode", "ci_discovery.py hooks" in ci,
          "the hook tests job no longer asks for its list")


# Tracked .py files that LOOK test-adjacent to the anchors below but are not
# tests. Kept deliberately short: every entry is a place an anchor was told to
# stop looking, so each one costs a sentence.
NOT_A_TEST = {
    "plugin-sdk/python/tests/__init__.py":
        "package marker, no assertions",
    "plugin-sdk/python/tests/mock_hestia_server.py":
        "fixture: the stub daemon the SDK suites connect to, imported not run",
    "plugins/claude-code/tests/projection_fixture.py":
        "fixture: renders a seat config projection under a fixture HESTIA_HOME, imported "
        "not run (projection_consumer_test.py and the end-to-end suites import "
        "write_projection/projection_env). It renders the same shape the daemon does, so a "
        "test's projection is the real artifact rather than a lookalike -- naming it a test "
        "would make CI grade the fixture by itself",
    "plugins/gemini/tests/runner_decision.py":
        "fidelity model of gemini-cli's hook-result parser, imported not run "
        "(channel_contract_test.py:33 `from runner_decision import decide`); it is "
        "the thing the gemini tests assert AGAINST, so naming it a test would make "
        "CI grade the ruler by itself",
}


def test_discovery_covers_every_test_shaped_file():
    """Structural, and deliberately NOT the load-bearing check.

    With catch-all discovery this cannot fail: bare_python_files() is defined as
    everything minus excluded minus hooks, so the three sets partition the whole
    set by construction. It is kept as a partition invariant -- it would fire if
    someone reintroduced a glob-shaped filter inside bare_python_files() -- and
    it is labelled here so nobody reads its green as evidence of coverage. The
    checks that can actually fail are the two anchors below.
    """
    every = set(D.all_test_shaped())
    accounted = (set(D.bare_python_files())
                 | set(D.hooks_job_files())
                 | set(D.excluded()))
    orphans = sorted(every - accounted)
    check("discovery partitions every test-shaped file", not orphans,
          "these run in NO job and are not declared in "
          "tools/ci_excluded_tests.txt:\n        " + "\n        ".join(orphans))


def test_anchor_naming_no_third_convention():
    """ANCHOR 1, and one of the two load-bearing checks.

    `is_test_shaped()` recognises two conventions. The bug being fixed here was
    a job that recognised ONE, so the failure mode is real and cheap to repeat:
    somebody writes `foo_tests.py` or `tests_foo.py`, no rule matches, and the
    file is not run, not reported, and not missed.

    A check with no evidence outside its own samples goes green when all of them
    are wrong the same way. So this sweeps with a DELIBERATELY LOOSER rule --
    any tracked .py with "test" anywhere in its basename -- and requires the
    strict rule to have caught everything the loose one found. The two agree
    today (18 = 18). A third convention breaks the tie and reddens this.
    """
    strict = set(D.all_test_shaped())
    loose = set()
    for path in D.tracked_python_files():
        if "test" in path.rsplit("/", 1)[-1].lower():
            loose.add(path)
    missed = sorted(loose - strict - set(NOT_A_TEST))
    check("no test-shaped file escapes is_test_shaped()", not missed,
          "these have 'test' in the filename but match neither convention "
          "is_test_shaped() knows, so they are invisible to CI:\n        "
          + "\n        ".join(missed)
          + "\n      Either rename to *_test.py / test_*.py, or add to "
            "NOT_A_TEST with a reason.")


def test_anchor_location_tests_directories():
    """ANCHOR 2, the other load-bearing check.

    Naming is one way to hide; location is the other. Anything living in a
    `tests/` directory is presumed to be a test regardless of what it is called
    -- a file named `scenario_one.py` in there is a test somebody forgot to
    name. Helpers and fixtures are real, so they get NOT_A_TEST entries rather
    than a blanket exemption for the directory.
    """
    strict = set(D.all_test_shaped())
    in_tests_dir = {
        p for p in D.tracked_python_files()
        if "/tests/" in "/" + p or p.startswith("tests/")
    }
    missed = sorted(in_tests_dir - strict - set(NOT_A_TEST))
    check("no unnamed test hides in a tests/ directory", not missed,
          "these live in a tests/ directory but match no test naming "
          "convention:\n        " + "\n        ".join(missed)
          + "\n      Either rename, or add to NOT_A_TEST with a reason.")


def test_not_a_test_entries_are_real():
    """An exemption for a file that no longer exists is a stale hole."""
    tracked = set(D.tracked_python_files())
    strict = set(D.all_test_shaped())
    for path, reason in sorted(NOT_A_TEST.items()):
        check(f"NOT_A_TEST exists: {path}", path in tracked,
              "exempted but not a tracked .py file")
        check(f"NOT_A_TEST not shadowing a real test: {path}",
              path not in strict,
              "exempted but it IS test-shaped and CI runs it -- delete the "
              "exemption")
        check(f"NOT_A_TEST has a reason: {path}", len(reason.strip()) > 15,
              "give a reason, not a placeholder")


def test_discovery_is_not_vacuous():
    """A discovery that finds nothing satisfies every assertion above it."""
    check("discovery finds test files", len(D.all_test_shaped()) > 5,
          f"only {len(D.all_test_shaped())} test-shaped file(s) tracked -- "
          "the layout moved and this guard is inspecting an empty set")
    check("the bare-python job has work", bool(D.bare_python_files()),
          "no files routed to the plugin tests job")


def test_exclusions_are_real_used_and_reasoned():
    """A stale excuse is worse than none: it reads as a known gap that is closed."""
    every = set(D.all_test_shaped())
    running = set(D.bare_python_files()) | set(D.hooks_job_files())
    reasons = manifest_reasons()
    for path in D.excluded():
        check(f"exclusion exists: {path}", path in every,
              "listed as excluded but no such tracked test-shaped file")
        check(f"exclusion not redundant: {path}", path not in running,
              "listed as excluded but CI runs it -- delete the line")
        reason = reasons.get(path, "")
        check(f"exclusion has a reason: {path}",
              len(reason) >= MIN_REASON_CHARS,
              f"reason is {len(reason)} chars; under {MIN_REASON_CHARS} is a "
              "placeholder, not a decision. Put it in a #-comment directly "
              "above the path.")


def test_both_conventions_are_discovered():
    """The prefix/suffix split is the mechanism that hid the orphans.

    If this fails, the repo normalized on one convention -- good news. Simplify
    the discovery rather than deleting this test.
    """
    every = D.all_test_shaped()
    suffix = [p for p in every if p.rsplit("/", 1)[-1].endswith("_test.py")]
    prefix = [p for p in every if p.rsplit("/", 1)[-1].startswith("test_")]
    check("both conventions present and discovered",
          bool(suffix) and bool(prefix),
          "repo appears to use one convention now -- simplify is_test_shaped()")
    # And the actual regression: a prefix-convention file must reach a job.
    prefix_running = [p for p in prefix
                      if p in set(D.bare_python_files()) | set(D.hooks_job_files())]
    check("prefix-convention files reach a job", bool(prefix_running),
          "every test_*.py file is excluded or orphaned -- this is exactly the "
          "state this test was written to end")


def teardown_module(module):
    """Deliver this file's accumulated failures to a harness that reads exceptions.

    `check()` records into `FAILS`, read only by the `__main__` block below. That is how CI
    invokes this file, so its exit code always held -- but under `python3 -m pytest` every
    `test_*` recorded its failures and returned normally, and real reds were reported as
    PASSED. pytest calls this after the module's tests; bare `python3` never calls it.

    See `tools/ci_selfexec_test.py::test_no_pytest_blind_files` for the guard that now makes
    the absence of this channel a failure rather than a thing someone has to notice.
    """
    assert not FAILS, (
        f"{len(FAILS)} check(s) failed -- see the FAIL lines in captured stdout: {FAILS}")


if __name__ == "__main__":
    test_ci_actually_calls_the_discovery_module()
    test_discovery_covers_every_test_shaped_file()
    test_anchor_naming_no_third_convention()
    test_anchor_location_tests_directories()
    test_not_a_test_entries_are_real()
    test_discovery_is_not_vacuous()
    test_exclusions_are_real_used_and_reasoned()
    test_both_conventions_are_discovered()
    for f in FAILS:
        print("FAIL", f)
    print(f"{'FAILED' if FAILS else 'ok'}: {len(FAILS)} failure(s), "
          f"{len(D.all_test_shaped())} test-shaped file(s) considered")
    sys.exit(1 if FAILS else 0)
