#!/usr/bin/env python3
"""#1102: a discovered test file must execute tests under its declared runner.

`ci_selfexec_test.py` covers inert functions and undelivered accumulators. This adds the two
remaining shapes: an incomplete TESTS/ALL registry, and a file whose pytest collection is empty
without an explicit script-only decision in tools/ci_script_only_tests.txt.
"""

from __future__ import annotations

import ast
from concurrent.futures import ThreadPoolExecutor
import importlib.util
import os
import pathlib
import subprocess
import sys

REPO = pathlib.Path(
    subprocess.run(["git", "rev-parse", "--show-toplevel"],
                   capture_output=True, text=True, check=True).stdout.strip()
)
_spec = importlib.util.spec_from_file_location("ci_discovery", REPO / "tools" / "ci_discovery.py")
D = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(D)

MANIFEST = REPO / "tools" / "ci_script_only_tests.txt"
FAILS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    if not ok:
        FAILS.append(f"{name}{': ' + detail if detail else ''}")


def bare_python_files() -> list[pathlib.Path]:
    return [REPO / p for p in D.bare_python_files() + D.hooks_job_files()]


def script_only() -> list[str]:
    if not MANIFEST.exists():
        return []
    return sorted(line.strip() for line in MANIFEST.read_text(encoding="utf-8").splitlines()
                  if line.strip() and not line.startswith("#"))


def registry_gaps(src: str) -> list[str]:
    """Missing top-level test functions from each module-level TESTS or ALL list."""
    try:
        tree = ast.parse(src)
    except SyntaxError as exc:
        return [f"<unparseable: {exc}>"]
    defined = {node.name for node in tree.body
               if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
               and node.name.startswith("test_")}
    gaps: list[str] = []
    for node in tree.body:
        targets = []
        if isinstance(node, ast.Assign):
            targets = [target for target in node.targets if isinstance(target, ast.Name)]
            value = node.value
        elif isinstance(node, ast.AnnAssign):
            targets = [node.target]
            value = node.value
        else:
            continue
        for target in targets:
            if target.id not in ("TESTS", "ALL") or not isinstance(value, (ast.List, ast.Tuple)):
                continue
            listed = {element.id for element in value.elts if isinstance(element, ast.Name)}
            gaps.extend(f"{target.id}:{name}" for name in sorted(defined - listed))
    return gaps


def _collection_verdict(rel: str, rc: int, count: int, declared: set[str]) -> str | None:
    if rc == 124:
        return "pytest --collect-only timed out; a script-only declaration cannot hide a hang"
    if rel in declared:
        if count:
            return "pytest now collects tests; remove the stale script-only declaration"
        return None
    if rc:
        return f"pytest --collect-only exited {rc} and the file is not declared script-only"
    if not count:
        return "pytest collected zero tests and the file is not declared script-only"
    return None


def collect_one(path: pathlib.Path) -> tuple[str, int, int, str]:
    rel = path.relative_to(REPO).as_posix()
    in_hooks = rel.startswith(D.HOOKS_DIR + "/")
    cwd = REPO / D.HOOKS_DIR if in_hooks else REPO
    argument = path.name if in_hooks else rel
    prefix = path.name if in_hooks else rel
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTEST_DISABLE_PLUGIN_AUTOLOAD="1")
    env.pop("PYTEST_ADDOPTS", None)
    command = [sys.executable, "-B", "-m", "pytest", "--collect-only", "-q",
               "-p", "no:cacheprovider", argument]
    try:
        result = subprocess.run(command, cwd=cwd, env=env, capture_output=True, text=True,
                                timeout=45)
        rc, output = result.returncode, result.stdout + result.stderr
    except subprocess.TimeoutExpired as exc:
        rc = 124
        output = (exc.stdout or b"").decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
    count = sum(line.startswith(prefix + "::") for line in output.splitlines())
    return rel, rc, count, output[-1200:]


def test_glob_is_not_empty():
    files = bare_python_files()
    check("execution-parity glob discovers files", bool(files), "the guard would pass over zero files")


def test_registry_completeness():
    for path in bare_python_files():
        rel = path.relative_to(REPO).as_posix()
        gaps = registry_gaps(path.read_text(encoding="utf-8", errors="replace"))
        check(f"registry includes every test: {rel}", not gaps,
              f"missing {gaps}; the registry runs only a subset of the file's tests")


def test_collection_parity():
    files = bare_python_files()
    declared_list = script_only()
    declared = set(declared_list)
    discovered = {path.relative_to(REPO).as_posix() for path in files}
    for rel in sorted(declared - discovered):
        check(f"script-only declaration is live: {rel}", False, "the file is not in CI discovery")
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(collect_one, files))
    for rel, rc, count, output in rows:
        verdict = _collection_verdict(rel, rc, count, declared)
        check(f"collection matches declared runner: {rel}", verdict is None,
              (verdict or "") + (f"\n{output}" if verdict and rc else ""))


def test_sabotage_red():
    missing = """\
def test_a(): pass
def test_b(): pass
TESTS = [test_a]
"""
    complete = """\
def test_a(): pass
def test_b(): pass
TESTS = [test_a, test_b]
"""
    all_missing = """\
def test_a(): pass
def test_b(): pass
ALL = [test_a]
"""
    check("registry sabotage: TESTS omission is red", registry_gaps(missing) == ["TESTS:test_b"],
          registry_gaps(missing))
    check("registry complete list is green", registry_gaps(complete) == [], registry_gaps(complete))
    check("registry sabotage: ALL omission is red", registry_gaps(all_missing) == ["ALL:test_b"],
          registry_gaps(all_missing))
    check("collection sabotage: zero unlisted is red",
          _collection_verdict("x_test.py", 0, 0, set()) is not None)
    check("collection sabotage: collection error unlisted is red",
          _collection_verdict("x_test.py", 2, 0, set()) is not None)
    check("collection sabotage: timeout is red even when declared",
          _collection_verdict("x_test.py", 124, 0, {"x_test.py"}) is not None)
    check("collection: explicit script-only zero is green",
          _collection_verdict("x_test.py", 0, 0, {"x_test.py"}) is None)
    check("collection sabotage: stale script-only declaration is red",
          _collection_verdict("x_test.py", 0, 1, {"x_test.py"}) is not None)
    check("collection: collected tests without declaration are green",
          _collection_verdict("x_test.py", 0, 1, set()) is None)


def teardown_module(module):
    assert not FAILS, f"{len(FAILS)} execution-parity check(s) failed: {FAILS}"


if __name__ == "__main__":
    test_glob_is_not_empty()
    test_registry_completeness()
    test_sabotage_red()
    test_collection_parity()
    for failure in FAILS:
        print("FAIL", failure)
    print(f"{'FAILED' if FAILS else 'ok'}: {len(FAILS)} failure(s), "
          f"{len(bare_python_files())} discovered file(s), {len(script_only())} script-only declaration(s)")
    sys.exit(1 if FAILS else 0)
