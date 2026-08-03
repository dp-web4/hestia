#!/usr/bin/env python3
"""A file CI runs as `python3 file.py` must actually execute its assertions.

The plugin-tests and hooks jobs both run each discovered file with bare
`python3`. That suits this repo's house style: assertions at module scope (or in
a `__main__` block), a `check()`/`FAILS` accumulator, and `sys.exit(1)` at the
end.

It does NOT work for a pytest-style file. Import the module, define some
`def test_*` functions, fall off the end, exit 0. Nothing ran. CI prints the
filename inside a green ::group:: and moves on.

Not hypothetical, and not a future risk:
`plugin-sdk/python/tests/conformance/test_conformance.py` is this shape today --
`pytestmark = pytest.mark.asyncio`, test functions never called at module scope.
Under bare `python3` it exits 0 having run zero of its assertions. It is outside
the current globs by luck of location, not by any rule.

Demonstrated before this file was written: a planted
`plugins/member-mesh/tests/zz_planted_pytest_style_test.py` containing
`assert 1 == 2` was discovered by the real glob and reported PASS by the real
runner loop.

THE RULE. Not "has a __main__ guard" -- most files here correctly have none and
run at module scope. The exact shape of the trap is: *test functions that are
defined and never called*. Anything pytest would collect and bare `python3`
would not. That is what this checks, via `ast` rather than a text grep, so a
name inside a string or a comment cannot fake a call.

This guard is PREVENTIVE: green on the commit that introduced it, because every
file currently in the globs either runs at module scope or calls its tests from
a `__main__` block. Its red is demonstrated by sabotage -- see the table in the
PR -- not by the state of the tree. Stated plainly rather than left to be
assumed, because an assertion nobody has seen fail is a comment with a check()
around it.

Run:  python3 tools/ci_selfexec_test.py
"""

import ast
import importlib.util
import pathlib
import re
import subprocess
import sys

REPO = pathlib.Path(
    subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
)

# The same module CI calls to build its run list -- not a copy of its globs.
# The hooks job runs its files with bare `python3` too (from their own cwd), so
# both sets are subject to this rule.
_spec = importlib.util.spec_from_file_location(
    "ci_discovery", REPO / "tools" / "ci_discovery.py")
D = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(D)

FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if not ok:
        FAILS.append(f"{name}{': ' + detail if detail else ''}")


def bare_python_files() -> list[pathlib.Path]:
    return [REPO / p for p in D.bare_python_files() + D.hooks_job_files()]


def uncalled_test_functions(src: str) -> list[str]:
    """Names of `def test_*` defined at module scope and never referenced.

    Referenced, not "called with parens at top level": a file may collect its
    tests into a list and loop over them, or pass them to a runner. Any mention
    of the name outside its own definition counts -- this guard is looking for
    functions that are *inert*, not policing how they are invoked.
    """
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return [f"<unparseable: {exc}>"]

    defined = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test")
    }
    if not defined:
        return []

    # Every Name load anywhere in the module, minus the def statements
    # themselves (a FunctionDef is not a Name node, so nothing to subtract).
    referenced = {
        node.id for node in ast.walk(tree) if isinstance(node, ast.Name)
    }
    # Decorated/attribute references e.g. suite.append(test_x) are Names too.
    return sorted(name for name in defined if name not in referenced)


def test_glob_is_not_empty():
    """A guard that inspects nothing passes trivially. Refuse that."""
    files = bare_python_files()
    check("bare-python globs discover something", bool(files),
          "no files matched -- the layout moved and this guard is inspecting "
          "an empty set, which would pass forever")


def test_no_inert_test_functions():
    """The load-bearing one: functions only pytest would ever call."""
    for path in bare_python_files():
        rel = path.relative_to(REPO).as_posix()
        inert = uncalled_test_functions(
            path.read_text(encoding="utf-8", errors="replace"))
        check(f"no inert test functions: {rel}", not inert,
              f"defines {inert} but never calls them. CI runs this file with "
              "bare `python3`, so those functions NEVER EXECUTE and the file "
              "reports green no matter what they assert. Either call them "
              "(module scope or a __main__ block), or move the file out of "
              "the bare-python globs and run it under pytest.")


def test_no_pytest_dependency():
    """The other tell: pytest fixtures/marks/parametrize silently do nothing.

    A file can call its test functions AND still depend on pytest for
    fixtures or parametrize, in which case bare `python3` runs one degenerate
    case or dies on a missing fixture argument. Either way the glob is lying
    about what it covers.
    """
    for path in bare_python_files():
        rel = path.relative_to(REPO).as_posix()
        src = path.read_text(encoding="utf-8", errors="replace")
        if re.search(r"^\s*(import\s+pytest|from\s+pytest\b)", src, re.M):
            check(f"no pytest dependency: {rel}", False,
                  "imports pytest but lives in a glob CI runs with bare "
                  "`python3` -- marks, fixtures and parametrize will not run")


def pytest_blind_functions(src: str) -> list[str]:
    """Names of pytest-collectable `test_*` functions in a module with no way to fail.

    A module-scope `def test_*` is what pytest collects. It fails only by raising -- an
    `assert`, or an exception. A file whose entire failure signal is `check()` appending to an
    accumulator that the `__main__` block reads has no such channel: pytest calls the
    function, the function records, the function returns, pytest prints PASSED.

    The rule is EXISTENCE of a channel somewhere in the module outside the `__main__` guard,
    not per-function coverage. `teardown_module`, a raising decorator, and an inline `assert`
    all satisfy it. Returns the collectable names when the module has none at all.
    """
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return [f"<unparseable: {exc}>"]

    collectable = sorted(
        node.name for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name.startswith("test")
    )
    if not collectable:
        return []          # pytest collects nothing here; it cannot report a false green

    main_guard = {
        id(inner)
        for node in tree.body
        if isinstance(node, ast.If) and "__main__" in ast.dump(node.test)
        for inner in ast.walk(node)
    }
    has_channel = any(
        isinstance(node, (ast.Assert, ast.Raise)) and id(node) not in main_guard
        for node in ast.walk(tree)
    )
    return [] if has_channel else collectable


def test_no_pytest_blind_files():
    """The mirror of `test_no_inert_test_functions`, and the half that was missing.

    That guard asks whether bare `python3` executes what pytest would collect. This one asks
    the reverse and equally load-bearing question: when someone runs the file the way its
    NAME invites, does a failure reach them?

    Found by kimi-code verifying #175 from a second seat: `gate_self_protection_test.py`
    reported `8 passed in 0.33s` on the commit whose entire payload was five deliberate
    failures, and the reviewer nearly returned a "cannot reproduce" on the strength of it.
    CI was never wrong -- it runs discovered files bare, and the exit code held. The wrong
    invocation is the LOCAL one, which is the one a reviewer reaches for, during review, and
    the failure mode is a green identical to the null state.

    The sweep that followed found the shape in four more files. Including this one: the guard
    against files bare `python3` cannot fail was itself a file pytest could not fail.

    WHAT THIS ASSERTS, AND WHAT IT CANNOT
    -------------------------------------
    Existence, not coverage. A file that keeps one asserting test and lets ten others record
    silently passes here. Coverage is not decidable from the AST -- a channel can be reached
    through any depth of helper -- and the defect actually observed was total absence: four
    files, zero channels between them. Same caveat class as this file's siblings: a green
    means nobody has removed the last channel, not that every check is delivered.
    """
    for path in bare_python_files():
        rel = path.relative_to(REPO).as_posix()
        blind = pytest_blind_functions(
            path.read_text(encoding="utf-8", errors="replace"))
        check(f"pytest can report a failure: {rel}", not blind,
              f"defines {blind} but the module contains no assert/raise outside its "
              "`__main__` guard. Under `python3 -m pytest` every one of those functions "
              "records its failures and returns normally, so pytest reports PASSED on a red "
              "file -- a green identical to the null state, in the invocation a `*_test.py` "
              "name invites. Add a `teardown_module` that asserts the accumulator is empty, "
              "or give the tests an assert.")


def teardown_module(module):
    """Deliver this file's accumulated failures to a harness that reads exceptions.

    `check()` records into `FAILS`, and `FAILS` was read ONLY by the `__main__` block below
    -- which is how CI invokes this file, so the exit-code path always held. Under
    `python3 -m pytest`, the invocation a file named `*_test.py` invites, every `test_*` ran
    its checks, recorded its failures and returned normally: real reds delivered as PASSED.

    pytest calls `teardown_module` after the module's tests and reports a failure here as a
    module ERROR with a non-zero exit. Bare `python3` never calls it, so nothing about the CI
    path changes.

    Found by kimi-code while verifying #175: `gate_self_protection_test.py` reported
    `8 passed` on the commit whose entire payload was five deliberate failures. This file was
    one of the four the sweep then found in the same shape -- including, sharply, this one:
    the guard that catches files bare `python3` cannot fail was itself a file pytest could
    not fail.
    """
    assert not FAILS, (
        f"{len(FAILS)} check(s) failed -- see the FAIL lines in captured stdout: {FAILS}")


if __name__ == "__main__":
    test_glob_is_not_empty()
    test_no_inert_test_functions()
    test_no_pytest_dependency()
    test_no_pytest_blind_files()
    for f in FAILS:
        print("FAIL", f)
    n = len(bare_python_files())
    print(f"{'FAILED' if FAILS else 'ok'}: {len(FAILS)} failure(s), "
          f"{n} bare-python file(s) checked")
    sys.exit(1 if FAILS else 0)
