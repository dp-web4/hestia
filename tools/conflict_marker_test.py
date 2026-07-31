#!/usr/bin/env python3
"""A conflict marker inside a string literal is valid code, and every gauge said so.

Found live in this tree on 2026-07-31. `plugins/agent-inventory/inventory.py`
carried an unresolved cherry-pick:

    <<<<<<< HEAD                                    (line 825)
    ... a docstring paragraph about the two backends ...
    =======
    >>>>>>> 0db1954 (fix(agent-inventory): ...)      (line 835)

The markers landed BETWEEN the opening and closing `\"\"\"` of a docstring. So:

    python3 -c 'ast.parse(...)'            -> PARSES OK
    python3 plugins/agent-inventory/test_inventory.py  -> ok: 0 failure(s)

The file's own 20-assertion suite passed with the markers in it, because to the
parser they are prose. Nothing in .github/workflows/ or tools/ looked for them.
The single tell was `git status` reporting `UU`, on the one machine where the
cherry-pick happened -- and the fleet's standing rule for this shared working
tree is to stage EXPLICIT PATHS, never `git add -A`. Staging a path by name is
exactly how a marker gets committed as valid Python.

Same shape this repo keeps finding: the check that would catch it is blind in
precisely the case it exists for. tools/ci_test_coverage_test.py (absence read
as pass), and PR #140 (an instrument that could not survive the failure it
measured). Here the syntax check is not wrong -- it is answering a different
question than the one anyone thought it answered.

TWO DETECTORS, DIFFERENT GRAIN. They do not overlap and neither subsumes
the other:

  D  marker text in a tracked WORKING-TREE file.  This is the CI-relevant one:
     a CI checkout's working tree IS the commit, so it catches markers that were
     committed. Read from the git INDEX instead -- the way tools/shebang_exec_bit
     _test.py legitimately does -- and this detector goes BLIND on the case
     above, because an unmerged path has no stage-0 entry for `git show :path`
     to return.

  E  unmerged entries in the index (`git ls-files -u`). This fires on a conflict
     IN PROGRESS. It can only ever fire locally: a fresh CI checkout has no
     unmerged entries, by construction.

SCOPE, STATED RATHER THAN IMPLIED: detector E is why the 2026-07-31 instance was
findable, and E cannot run in CI. So this guard would NOT have caught that
instance in CI -- it was never committed. Its CI value is that a marker which
DOES get committed stops being invisible. Its local value is E. Claiming it
"would have caught" the live case would be false.

WHY THE TRIGGER IS `<<<<<<<` / `>>>>>>>` AND NOT `=======`. Calibrated against
this tree before choosing: a bare 7-character `=======` at line start currently
hits exactly one file (the conflicted one). That is luck, not design -- a
markdown setext underline of exactly seven `=` is ordinary prose and would be a
false positive. The open/close markers cannot occur in prose. Triggering only on
them means this guard needs NO exclusion list, which matters because an
exclusion list is how a guard later goes blind.

This file contains no literal marker at line start: the patterns are built by
repetition at import time, so the scanner does not match its own source and
needs no self-exemption.

Run:  ./tools/conflict_marker_test.py
"""

import pathlib
import subprocess
import sys

OPEN = "<" * 7
CLOSE = ">" * 7
MIDDLE = "=" * 7

# Deliberately NOT MIDDLE -- see the docstring. Prose cannot produce these two.
TRIGGERS = (OPEN, CLOSE)

_DIED = []


def _death_guard(exc_type, exc, tb):
    """Any escape from a check body is RECORDED, not silently fatal.

    PR #140: an uncaught raise and a clean sys.exit(1) are the same exit code,
    so CI cannot tell a truncated run from a smaller count. If this fires, the
    toll below is a FLOOR.
    """
    _DIED.append(exc)
    sys.__excepthook__(exc_type, exc, tb)


sys.excepthook = _death_guard


def repo_root():
    return pathlib.Path(subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True,
    ).stdout.strip())


def scan_text(text):
    """Return [(lineno, marker)] for conflict markers at line start.

    A marker is the 7-char run followed by a space or end-of-line. The trailing
    space is what separates `>>>>>>> 0db1954` from a `>>>>>>>` a doc might use
    as a rule, and from a `>>> ` doctest prompt.
    """
    hits = []
    for i, line in enumerate(text.splitlines(), 1):
        for marker in TRIGGERS:
            if line.startswith(marker) and line[len(marker):len(marker) + 1] in ("", " "):
                hits.append((i, marker))
    return hits


def tracked_files(repo):
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=repo, capture_output=True, check=True,
    ).stdout
    return [p.decode() for p in out.split(b"\0") if p]


def unmerged_paths(repo):
    out = subprocess.run(
        ["git", "ls-files", "-u", "-z"], cwd=repo, capture_output=True, check=True,
    ).stdout
    paths = set()
    for entry in out.split(b"\0"):
        if entry and b"\t" in entry:
            paths.add(entry.split(b"\t", 1)[1].decode())
    return sorted(paths)


RESULTS = []


def check(label, cond, detail=""):
    """cond may be a zero-arg callable; a raise becomes a FAIL, not a truncation."""
    try:
        ok = bool(cond() if callable(cond) else cond)
    except Exception as exc:  # noqa: BLE001 -- recording it IS the point
        RESULTS.append((False, label, f"raised {type(exc).__name__}: {exc}"))
        return False
    RESULTS.append((ok, label, detail))
    return ok


# --- The instrument, proven on synthetic input -------------------------------
# These do not depend on the tree being dirty. A guard whose only evidence is a
# transient working-tree state stops proving anything the moment it is cleaned.

CONFLICTED = "\n".join([
    "def f():",
    '    """doc',
    OPEN + " HEAD",
    "    ours",
    MIDDLE,
    "    theirs",
    CLOSE + " 0db1954 (subject)",
    '    """',
    "    return 1",
])

# The calibrated collision: a markdown setext underline of exactly seven '='.
# A REAL marker is embedded alongside it on a known line. Asserting only
# "finds nothing" would be VACUOUSLY green against a blinded scanner -- the
# same defect PR #140 found in its own check 3, and it reappeared here on the
# first draft. Each negative check now carries its own positive control, so a
# scanner that stops matching fails these rows instead of passing them.
MARKDOWN = "\n".join([
    "Title", MIDDLE, "", "body text", "", "> a blockquote",
    OPEN + " HEAD",                       # line 7: MUST be found
])
MARKDOWN_EXPECT = [(7, OPEN)]

# Near-misses that must NOT fire: a doctest prompt, an over-long run, a partial.
NEAR_MISS = "\n".join([
    ">>> import sys", ">>>>>>>>>> not a marker", "<<< partial",
    CLOSE,                                # line 4: bare marker, EOL -> found
])
NEAR_MISS_EXPECT = [(4, CLOSE)]


def main():
    repo = repo_root()

    check("A  scanner fires on a marker inside a docstring",
          lambda: len(scan_text(CONFLICTED)) == 2,
          f"hits={scan_text(CONFLICTED)}")

    check("B  ignores a 7-char markdown '=' underline, keeps the real marker",
          lambda: scan_text(MARKDOWN) == MARKDOWN_EXPECT,
          f"hits={scan_text(MARKDOWN)} want={MARKDOWN_EXPECT}")

    check("C  ignores doctest prompts / over-long runs, keeps the real marker",
          lambda: scan_text(NEAR_MISS) == NEAR_MISS_EXPECT,
          f"hits={scan_text(NEAR_MISS)} want={NEAR_MISS_EXPECT}")

    check("D  the conflicted sample still parses as Python",
          lambda: __import__("ast").parse(CONFLICTED) is not None,
          "this is WHY the syntax gauge cannot be the guard")

    # --- The live tree ------------------------------------------------------
    offenders = {}
    unreadable = []
    for rel in tracked_files(repo):
        path = repo / rel
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            unreadable.append(rel)      # binary or gone; not a marker carrier
            continue
        hits = scan_text(text)
        if hits:
            offenders[rel] = hits

    check("E  no tracked working-tree file carries a conflict marker",
          not offenders,
          f"{len(offenders)} file(s)" if offenders else
          f"scanned {len(tracked_files(repo)) - len(unreadable)} text files")

    unmerged = unmerged_paths(repo)
    check("F  no unresolved merge/cherry-pick in the index",
          not unmerged,
          f"{len(unmerged)} unmerged path(s)" if unmerged else "index clean")

    # --- Toll ---------------------------------------------------------------
    # Per-row, not a grep over stdout: a summary trailer carrying the word FAIL
    # is how a whole-stdout assertion goes green on unfixed code.
    print()
    for ok, label, detail in RESULTS:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   [{detail}]" if detail else ""))

    if offenders:
        print("\nConflict markers in tracked files:")
        for rel, hits in offenders.items():
            for lineno, marker in hits:
                print(f"    {rel}:{lineno}: {marker}")
    if unmerged:
        print("\nUnmerged index entries (a conflict is IN PROGRESS here):")
        for rel in unmerged:
            print(f"    UU  {rel}")
        print("\n  Resolve, or `git cherry-pick --abort` / `git merge --abort`.")
        print("  NOTE on this shared tree: --abort also reverts unrelated")
        print("  uncommitted work. Check `git status` for a sibling's edits first.")

    red = sum(1 for ok, _, _ in RESULTS if not ok)
    truncated = bool(_DIED)
    if truncated:
        print(f"\n!! HARNESS DIED -- {red} is a FLOOR, not the count")
    print(f"\n{'FAILED' if red else 'ok'}: {red} of {len(RESULTS)} red"
          + (" (TRUNCATED)" if truncated else ""))
    return 1 if (red or truncated) else 0


if __name__ == "__main__":
    sys.exit(main())
