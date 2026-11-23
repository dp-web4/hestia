#!/usr/bin/env python3
"""The withdrawn #1082 resolver archive stays out of everything that runs.

`tools/redirect_resolver_1082/` is withdrawn candidate code kept as measured evidence
(#1173). Its README says none of it may be imported by the runtime gate. "No production
import was found" is a grep that is true on the day it is run; this makes it a test.

Fails when any Python file outside the archive
  - imports an archive module by name (`import x`, `from x import y`, `from pkg import x`), or
  - names the archive directory in code (a `sys.path` insert, an `importlib` path, a
    subprocess argv): any string constant containing the directory name.

Also fails when an archive file does not parse, or parses with a SyntaxWarning: an
invalid escape sequence is a SyntaxError in a future Python, and an archive that no
longer parses is no longer evidence anyone can re-run.

Run:  python3 tools/redirect_resolver_1082_quarantine_test.py
"""

import ast
import os
import sys
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE_NAME = "redirect_resolver_" + "1082"  # split so this file does not name it whole
ARCHIVE = ROOT / "tools" / ARCHIVE_NAME
SKIP_DIRS = {".git", "node_modules", "target", "__pycache__", ".venv", "venv", "dist", "build"}


def archive_modules():
    return {p.stem for p in ARCHIVE.glob("*.py")}


def references(src, modules, archive_name=ARCHIVE_NAME):
    """Every way `src` reaches the archive, as (lineno, what)."""
    hits = []
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                parts = alias.name.split(".")
                if modules & set(parts) or archive_name in parts:
                    hits.append((node.lineno, f"import {alias.name}"))
        elif isinstance(node, ast.ImportFrom):
            parts = (node.module or "").split(".")
            names = {alias.name for alias in node.names}
            if modules & set(parts) or archive_name in parts or modules & names or archive_name in names:
                hits.append((node.lineno, f"from {node.module or '.'} import {sorted(names)}"))
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            if archive_name in node.value:
                hits.append((node.lineno, "string naming the archive directory"))
    return hits


def python_files_outside_archive():
    out = []
    for dirpath, dirnames, filenames in os.walk(ROOT):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        here = Path(dirpath)
        if here == ARCHIVE:
            dirnames[:] = []
            continue
        out.extend(here / f for f in filenames if f.endswith(".py"))
    return sorted(out)


def test_the_archive_exists_and_is_enumerated():
    # A guard over an empty module set passes for the wrong reason.
    modules = archive_modules()
    assert ARCHIVE.is_dir(), f"{ARCHIVE} is gone; retire this guard with it, do not leave it vacuous"
    assert "redirect_target_resolver_v7" in modules and len(modules) >= 8, sorted(modules)
    files = python_files_outside_archive()
    assert len(files) > 100, f"walk found only {len(files)} files; the guard is not seeing the repo"
    assert not [f for f in files if ARCHIVE in f.parents], "the walk leaked into the archive"


def test_the_detector_sees_each_way_in():
    # Negative controls: each spelling must be caught, and a clean file must not be.
    modules = {"redirect_target_resolver_v7", "redirect_resolver_battery"}
    red = (
        "import redirect_target_resolver_v7",
        "import redirect_target_resolver_v7 as r",
        "from redirect_target_resolver_v7 import resolve",
        "from tools.archive_dir import redirect_resolver_battery",
        "import tools.archive_dir.anything",
        "from tools.archive_dir import anything",
        "import sys\nsys.path.insert(0, 'tools/archive_dir')",
        "def f():\n    import redirect_resolver_battery",
    )
    for src in red:
        assert references(src, modules, "archive_dir"), f"detector missed: {src!r}"
    green = (
        "import os",
        "from pathlib import Path",
        "x = 'redirect_target_resolver_v7'",  # a module name in prose/data is not an import
        "import redirect_target_resolver_v70",
    )
    for src in green:
        assert not references(src, modules, "archive_dir"), f"detector false positive: {src!r}"


def test_nothing_outside_the_archive_reaches_it():
    modules = archive_modules()
    me = Path(__file__).resolve()
    found = []
    for path in python_files_outside_archive():
        if path.resolve() == me:
            continue
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                hits = references(path.read_text(encoding="utf-8", errors="replace"), modules)
        except SyntaxError:
            continue  # an unparseable file imports nothing; other guards own that defect
        found.extend(f"{path.relative_to(ROOT)}:{line}: {what}" for line, what in hits)
    assert not found, (
        "withdrawn #1082 resolver code is reachable from outside its archive "
        "(tools/" + ARCHIVE_NAME + "/README.md: evidence only, never imported):\n  "
        + "\n  ".join(found)
    )


def test_the_archive_parses_without_warnings():
    bad = []
    for path in sorted(ARCHIVE.glob("*.py")):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            try:
                ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError as exc:
                bad.append(f"{path.name}: does not parse: {exc}")
        bad.extend(f"{path.name}:{w.lineno}: {w.message}" for w in caught
                   if issubclass(w.category, SyntaxWarning))
    assert not bad, "archive does not parse cleanly:\n  " + "\n  ".join(bad)


TESTS = [
    test_the_archive_exists_and_is_enumerated,
    test_the_detector_sees_each_way_in,
    test_nothing_outside_the_archive_reaches_it,
    test_the_archive_parses_without_warnings,
]


def main():
    defined = {k for k in globals() if k.startswith("test_")}
    listed = {t.__name__ for t in TESTS}
    if defined != listed:
        print(f"FAIL TESTS is stale: defined-not-listed={sorted(defined - listed)} "
              f"listed-not-defined={sorted(listed - defined)}")
        return 1
    failed = []
    for t in TESTS:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed.append((t.__name__, e))
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(TESTS) - len(failed)}/{len(TESTS)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
