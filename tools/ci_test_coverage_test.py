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
    tools/workspace_root_test.py

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


def test_no_undeclared_orphans():
    """The load-bearing one. Every test-shaped file is run or declared."""
    every = set(D.all_test_shaped())
    accounted = (set(D.bare_python_files())
                 | set(D.hooks_job_files())
                 | set(D.excluded()))
    orphans = sorted(every - accounted)
    check("no undeclared orphan tests", not orphans,
          "these test-shaped files run in NO CI job and are not declared in "
          "tools/ci_excluded_tests.txt:\n        " + "\n        ".join(orphans))


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


if __name__ == "__main__":
    test_ci_actually_calls_the_discovery_module()
    test_no_undeclared_orphans()
    test_discovery_is_not_vacuous()
    test_exclusions_are_real_used_and_reasoned()
    test_both_conventions_are_discovered()
    for f in FAILS:
        print("FAIL", f)
    print(f"{'FAILED' if FAILS else 'ok'}: {len(FAILS)} failure(s), "
          f"{len(D.all_test_shaped())} test-shaped file(s) considered")
    sys.exit(1 if FAILS else 0)
