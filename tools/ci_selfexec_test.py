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


PYTEST_ENTRY_POINTS = (
    "setup_module", "teardown_module", "setup_function", "teardown_function",
    "setup", "teardown", "pytest_generate_tests",
)


def _pytest_reachable(name: str) -> bool:
    """Names pytest calls without anyone in the file referencing them.

    `test_*` by collection, the xunit hooks by name. They are the ROOTS of the
    outside world: no matter who else calls them, pytest gets there without
    `__main__`, so they can never belong to the `__main__` guard.

    Fixtures would belong here too, and are absent by construction -- a file in
    the bare-python globs that imports pytest is already failed by
    `test_no_pytest_dependency`. That is a dependency between two rules in this
    file, so it is written down rather than left to hold by luck.
    """
    return name.startswith("test") or name in PYTEST_ENTRY_POINTS


def main_only_nodes(tree: ast.Module) -> set:
    """ids of every node reachable ONLY through the `__main__` guard.

    Both rules below ask "is this assert / this read outside `__main__`?" and
    both used to answer it lexically. kimi-code refuted that (notice 795) with
    the most ordinary refactor there is -- extract function:

        def main() -> int:
            test_one(); test_two()
            assert not FAILS, FAILS     # lexically outside the guard...
        if __name__ == "__main__":
            sys.exit(main())            # ...reachable only from inside it

    Both rules reported green; pytest reported `2 passed`; bare `python3`
    exited 1. A read routes through a helper exactly the way a failure channel
    does, so deciding the LEXICAL location of the read answers a question one
    hop away from the one being asked.

    So: start from the guard's own body, then to fixpoint absorb any
    module-level function whose every reference is already inside it. `main`
    joins, and the assert and the read it holds stop counting as outside.

    ONE PIN, load-bearing: `_pytest_reachable` names never join. Without it the
    closure swallows the module -- `main` joins, then the `test_*` functions it
    calls, then the `check()` they call, and the append itself is suddenly
    in-guard. kimi's first draft of this repair did exactly that and reported a
    clean zero over all 26 files (notice 796): a rule that could not flag
    anything, passing the census because the census contains no helper-routed
    file to regress on. Zero census diff is compatible with a dead rule.

    A SECOND PIN WAS WRITTEN HERE AND REMOVED, because the control that was
    supposed to justify it came back with no diff at all. The claim was that a
    function referenced NOWHERE must not join -- "every reference is inside the
    guard" being vacuously true of zero references -- to stop the closure
    erasing the zero-reference `teardown_module` this PR adds as four files'
    channel. The name pin above already covers `teardown_module`, so sabotaging
    the clause changed no answer anywhere. Pressed for a case where it DID
    change one, it turned out to change it the wrong way:

        FAILS = []
        def test_a(): FAILS.append("a")
        def _report(): assert not FAILS      # zero refs, never a pytest hook
        if __name__ == "__main__": test_a()

    pytest reports `1 passed`; `_report` never runs; the file is a false green.
    Absorbing an unreferenced function is the RIGHT answer -- an assert nothing
    reaches is not a channel -- and the pin suppressed both flags. A hook name
    this list misses is absorbed the same way and shows up as a loud false
    positive, which is the direction to fail in.

    Still lexical in one direction: a function called from BOTH `main` and a
    test stays outside, so a channel reachable only via a long private chain
    from `__main__` can still read as delivered. That is the conservative
    direction -- it under-flags, never over-flags -- and it is why the
    docstrings below claim direct-plus-closure, not decidability.
    """
    inside = {
        id(inner)
        for node in tree.body
        if isinstance(node, ast.If) and "__main__" in ast.dump(node.test)
        for inner in ast.walk(node)
    }
    if not inside:
        return inside

    funcs = {
        node.name: node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and not _pytest_reachable(node.name)
    }
    joined: set[str] = set()
    changed = True
    while changed:
        changed = False
        for name, fn in funcs.items():
            if name in joined:
                continue
            refs = [
                node for node in ast.walk(tree)
                if isinstance(node, ast.Name) and node.id == name
                and isinstance(node.ctx, ast.Load)
            ]
            if all(id(node) in inside for node in refs):
                joined.add(name)
                inside |= {id(inner) for inner in ast.walk(fn)}
                changed = True
    return inside


def pytest_blind_functions(src: str) -> list[str]:
    """Names of pytest-collectable `test_*` functions in a module with no way to fail.

    A module-scope `def test_*` is what pytest collects. It fails only by raising -- an
    `assert`, or an exception. A file whose entire failure signal is `check()` appending to an
    accumulator that the `__main__` block reads has no such channel: pytest calls the
    function, the function records, the function returns, pytest prints PASSED.

    The rule is EXISTENCE of a channel somewhere in the module outside the `__main__` guard,
    not per-function coverage. `teardown_module`, a raising decorator, and an inline `assert`
    all satisfy it. Returns the collectable names when the module has none at all.

    KNOWN GAP, and the reason `undelivered_accumulators` exists beside this. An `assert` that
    measures the TEST RIG rather than the subject satisfies this rule while every check of the
    subject stays undelivered. `plugins/_shared/test_gate_core.py` is the worked example --
    one of the four files this PR fixes, and at `87b5732` this rule did NOT flag it, because
    `_workspace()` asserts that the scratch dir is not under /tmp. Scaffolding hygiene, never
    a property of the gate. Confirmed from a second seat by kimi-code (notice 791): stripping
    that file's new `teardown_module` leaves this check green.
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

    main_guard = main_only_nodes(tree)
    has_channel = any(
        isinstance(node, (ast.Assert, ast.Raise)) and id(node) not in main_guard
        for node in ast.walk(tree)
    )
    return [] if has_channel else collectable


def undelivered_accumulators(src: str) -> list[str]:
    """Module-level accumulators that only the `__main__` block ever reads.

    `pytest_blind_functions` asks whether ANY failure channel exists. This asks the sharper
    question its known gap lets through: is the file's OWN failure record delivered? A module
    that appends to `FAILS` outside `__main__` and reads it only inside `__main__` has, by
    construction, routed every check it makes to the one invocation CI uses -- whatever
    unrelated `assert` may sit elsewhere in the file.

    Coverage in general is not decidable from an AST, and this shape is not decidable either
    -- the first version of this docstring said it was. kimi-code refuted that in one hop
    (notice 795): move the read into a `main()` called only from `__main__` and a lexical rule
    calls it delivered. `main_only_nodes` closes over that, so what is decided now is reads
    outside the `__main__` guard AND outside everything only that guard reaches. A read behind
    a helper shared with a test function still escapes. What the rule buys is the exact defect
    observed five times, separated from a scaffolding assert without knowing which asserts
    measure the subject -- not a proof that every check is delivered.

    NOT a superset of `pytest_blind_functions`, and not a replacement -- a file with
    collectable tests, no accumulator and no assert at all is caught by that rule and not by
    this one. Both run; each catches what the other cannot.
    """
    try:
        tree = ast.parse(src)
    except SyntaxError:
        return []          # the sibling rule reports the parse failure; don't double-report

    if not any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
               and node.name.startswith("test") for node in tree.body):
        return []          # pytest collects nothing here; it cannot report a false green

    accumulators = set()
    for node in tree.body:
        # `FAILS = []` and `FAILS: list[str] = []` are different nodes. Every file in this
        # repo uses the annotated form, so an Assign-only scan flags nothing, anywhere.
        if isinstance(node, ast.Assign) and isinstance(node.value, (ast.List, ast.Dict, ast.Set)):
            accumulators |= {t.id for t in node.targets if isinstance(t, ast.Name)}
        elif (isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name)
              and isinstance(node.value, (ast.List, ast.Dict, ast.Set))):
            accumulators.add(node.target.id)
    if not accumulators:
        return []

    main_guard = main_only_nodes(tree)

    appended, receivers = set(), set()
    for node in ast.walk(tree):
        if (id(node) not in main_guard and isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id in accumulators
                and node.func.attr in ("append", "add", "extend", "update")):
            appended.add(node.func.value.id)
            # The receiver of `FAILS.append(...)` is itself a Load of `FAILS`, and
            # `ast.walk` yields it as its own node. Excluded by identity -- otherwise every
            # appended accumulator marks itself as read and this rule flags nothing, ever.
            receivers.add(id(node.func.value))

    read_outside = {
        node.id for node in ast.walk(tree)
        if isinstance(node, ast.Name) and node.id in accumulators
        and isinstance(node.ctx, ast.Load)
        and id(node) not in main_guard and id(node) not in receivers
    }
    return sorted(appended - read_outside)


def test_no_undelivered_accumulators():
    """The scaffolding-assert gap in `test_no_pytest_blind_files`, closed.

    kimi-code, re-deriving the blind-file census independently at `87b5732` (notice 791),
    flagged only three of the four files this PR fixes. `plugins/_shared/test_gate_core.py`
    passes the sibling rule on the strength of one `assert` inside `_workspace()` that checks
    the scratch directory is not under /tmp -- the test rig, not the gate. Every one of that
    file's actual checks went to `FAILURES`, and `FAILURES` was read only in `__main__`.

    So the sibling rule's green there was a true answer to a question nobody was asking. This
    check asks the one that was: at `87b5732` it flags all four, and `harness_toll_test.py` --
    whose whole body sits inside `__main__`, so pytest collects nothing and no green can be
    false -- is correctly not among them.
    """
    for path in bare_python_files():
        rel = path.relative_to(REPO).as_posix()
        undelivered = undelivered_accumulators(
            path.read_text(encoding="utf-8", errors="replace"))
        check(f"failure record reaches pytest: {rel}", not undelivered,
              f"appends to {undelivered} outside `__main__` but reads it only inside, so "
              "every recorded failure is delivered to the CI invocation alone. Under "
              "`python3 -m pytest` the tests record and return normally and pytest reports "
              "PASSED. An unrelated `assert` elsewhere in the file satisfies "
              "`test_no_pytest_blind_files` without making this any less true. Add a "
              "`teardown_module` that asserts the accumulator is empty.")


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
    files, zero channels between them.

    "Outside the `__main__` guard" means outside its closure, not outside its braces: an
    assert in a `main()` that only `__main__` calls is not a channel, and was counted as one
    until kimi-code's counterexample (notice 795). The closure is still one-sided -- a helper
    called from both `main` and a test stays outside it, so its assert still counts. Same
    caveat class as this file's siblings: a green means nobody has removed the last
    *reachable* channel, not that every check is delivered.
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


# Sources both rules must decide correctly. Held here rather than as fixture files because
# a fixture file under the globs would be discovered and flagged by the very rules it tests.
_HELPER_HOP = '''\
import sys
FAILS: list[str] = []
def check(name, ok):
    if not ok:
        FAILS.append(name)
def test_one():
    check("one", 1 == 2)
def test_two():
    check("two", 2 == 3)
def main() -> int:
    test_one(); test_two()
    assert not FAILS, FAILS
    return 0
if __name__ == "__main__":
    sys.exit(main())
'''

_DEAD_CHANNEL = '''\
FAILS = []
def test_a():
    FAILS.append("a")
def _report():
    assert not FAILS
if __name__ == "__main__":
    test_a()
'''

_REAL_CHANNEL = '''\
FAILS: list[str] = []
def check(name, ok):
    if not ok:
        FAILS.append(name)
def test_one():
    check("one", 1 == 2)
def teardown_module(module):
    assert not FAILS, FAILS
if __name__ == "__main__":
    test_one()
'''


def test_closure_reaches_through_helpers():
    """Both rules on three sources whose answers a lexical test gets wrong.

    Not a census assertion -- the census cannot carry this, because at `87b5732` it holds no
    helper-routed file to regress on, which is exactly how a dead version of this closure
    passes it (kimi-code, notice 796). These are the live controls: the repair must FLAG the
    first two and must NOT flag the third, and each one fails a different way if the closure
    is wrong.

    `_HELPER_HOP` is kimi's refutation of #184's decidability claim (notice 795): the
    extract-function refactor of this repo's own house style. Real accumulator, real assert,
    `python3 -m pytest` reports `2 passed`, bare `python3` exits 1, and before the closure
    both rules reported green.

    `_DEAD_CHANNEL` is the case that killed a pin this file briefly carried: an assert in a
    function nothing references is not a channel, and must be absorbed, not protected.

    `_REAL_CHANNEL` is the shape of the fix applied to four files in this PR. It must stay
    green, or the closure has eaten the remedy -- the failure mode where a rule flags
    everything is as dead as the one where it flags nothing.
    """
    check("closure flags the helper-hop counterexample (blind)",
          pytest_blind_functions(_HELPER_HOP) == ["test_one", "test_two"],
          f"got {pytest_blind_functions(_HELPER_HOP)} -- a read or assert routed one hop "
          "through main() is being read as lexically outside the guard again")
    check("closure flags the helper-hop counterexample (undelivered)",
          undelivered_accumulators(_HELPER_HOP) == ["FAILS"],
          f"got {undelivered_accumulators(_HELPER_HOP)}")
    check("an unreferenced assert is not a channel",
          pytest_blind_functions(_DEAD_CHANNEL) == ["test_a"],
          f"got {pytest_blind_functions(_DEAD_CHANNEL)} -- pytest never calls `_report`, so "
          "its assert cannot deliver anything")
    check("a teardown_module channel stays green",
          not pytest_blind_functions(_REAL_CHANNEL)
          and not undelivered_accumulators(_REAL_CHANNEL),
          f"blind={pytest_blind_functions(_REAL_CHANNEL)} "
          f"undelivered={undelivered_accumulators(_REAL_CHANNEL)} -- the closure has absorbed "
          "the pytest entry points and now flags the very remedy this PR applies")


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
    test_no_undelivered_accumulators()
    test_closure_reaches_through_helpers()
    for f in FAILS:
        print("FAIL", f)
    n = len(bare_python_files())
    print(f"{'FAILED' if FAILS else 'ok'}: {len(FAILS)} failure(s), "
          f"{n} bare-python file(s) checked")
    sys.exit(1 if FAILS else 0)
