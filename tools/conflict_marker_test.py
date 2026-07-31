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
the other. They are checks E and F below (check D is the parse assertion --
these labels were off by one in the first cut of this docstring, in a file
whose whole claim is that prose and instrument agree; kimi-code caught it):

  E  marker text in a tracked WORKING-TREE file.  This is the CI-relevant one:
     a CI checkout's working tree IS the commit, so it catches markers that were
     committed. Read from the git INDEX instead -- the way
     tools/shebang_exec_bit_test.py legitimately does -- and this detector goes
     BLIND on the case above, because an unmerged path has no stage-0 entry for
     `git show :path` to return.

  F  unmerged entries in the index (`git ls-files -u`). This fires on a conflict
     IN PROGRESS. It can only ever fire locally: a fresh CI checkout has no
     unmerged entries, by construction.

SCOPE, STATED RATHER THAN IMPLIED: detector F is why the 2026-07-31 instance was
findable, and F cannot run in CI. So this guard would NOT have caught that
instance in CI -- it was never committed. Its CI value is that a marker which
DOES get committed stops being invisible. Its local value is F. Claiming it
"would have caught" the live case would be false.

CHOSEN LIMIT, NOT A DISCOVERED ONE: the scanner requires exactly a 7-char run
followed by space or EOL, so it MISSES a real conflict whose markers git's xdiff
auto-bumped to 8+ characters -- which xdiff does when the conflicting content
already contains marker text. NEAR_MISS asserts that miss as intended. The trade
is deliberate: an 8+ run is also how a doc writes a rule or an arrow, and a guard
that fires on those acquires an exclusion list, which is how a guard goes blind.
Zero false positives over the rare auto-bumped conflict is the call being made.

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

import os
import pathlib
import shutil
import subprocess
import sys
import tempfile

# Set in the child of check G only. Makes main() raise at a fixed point, so the
# death path is EXERCISED rather than merely present.
INJECT_DEATH = "CONFLICT_MARKER_TEST_INJECT_DEATH"

OPEN = "<" * 7
CLOSE = ">" * 7
MIDDLE = "=" * 7

# Deliberately NOT MIDDLE -- see the docstring. Prose cannot produce these two.
TRIGGERS = (OPEN, CLOSE)

_DIED = []


def _death_guard(exc_type, exc, tb):
    """Any escape from a check body is RECORDED, and the toll so far is PRINTED.

    PR #140: an uncaught raise and a clean sys.exit(1) are the same exit code,
    so CI cannot tell a truncated run from a smaller count.

    The first cut of this hook only recorded, and left the printing to a trailer
    at the end of main(). That trailer is UNREACHABLE from here: an excepthook
    runs after main() has already unwound, so a mid-run death printed ZERO rows
    and the FLOOR annotation this docstring promised could never appear -- the
    exact shape of #140, one layer up, in the harness instead of the scanner.
    kimi-code found it by injected raise; check G now holds the repair down.

    So this hook does the printing itself: it is the code that runs at death.
    """
    _DIED.append(exc)
    sys.__excepthook__(exc_type, exc, tb)
    sys.stderr.flush()
    try:
        report(truncated=True)
    except Exception as exc2:  # noqa: BLE001 -- a dying reporter must still say so
        print(f"\n!! HARNESS DIED and the report ALSO failed: {exc2!r}")


sys.excepthook = _death_guard


def repo_root():
    return pathlib.Path(subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        capture_output=True, text=True, check=True,
    ).stdout.strip())


def head_ref(repo):
    """`<short-sha>` plus a suffix naming WHICH divergence, because they move
    different things. A file count with no ref beside it is not checkable --
    two machines report different totals and neither is wrong. kimi-code
    measured 939/940/937 across three checkouts of this repo.

    A single `-dirty` bit was not enough, and the drift it was written for is
    what shows why. On 2026-07-31 this tree stamped `3e4e040-dirty` and scanned
    935 against the branch's 940 at `1e65678`. The gap was exactly the 5 files
    the 23 commits between those refs add, so the SHA carried the whole
    explanation -- and `-dirty` was set by four untracked paths and one
    worktree-modified file, none of which can change the number. The suffix
    said "this total may not be 3e4e040's" about a total that provably was.

    Two independent facts a reader needs, so two independent suffixes:

      +list     the index's file LIST differs from HEAD's tree, so the COUNT is
                not HEAD's. Only staged adds/deletes/renames do this.
      +content  some tracked file's worktree bytes differ from HEAD's, so the
                OFFENDER SET is not HEAD's. Check E reads the working tree
                (`path.read_text`), not the blob, so an unstaged edit is enough.

    Untracked files get NO suffix. Both detectors reach the index only --
    E through `git ls-files`, F through `git ls-files -u` -- so an untracked
    path cannot enter either answer. Marking it would report a divergence that
    is unreachable by construction, which is how `-dirty` became unreadable.
    Check H asserts all four cases.
    """
    def git(*a):
        return subprocess.run(
            ["git", *a], cwd=repo, capture_output=True, text=True,
        ).stdout.strip()
    sha = git("rev-parse", "--short", "HEAD") or "?"
    marks = ""
    if git("diff", "--cached", "--name-only", "--diff-filter=ADR", "HEAD"):
        marks += "+list"
    if git("diff", "--name-only", "HEAD"):
        marks += "+content"
    return sha + marks


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


# Live-tree findings live at MODULE scope, not in main()'s locals, so that
# _death_guard can still print them after main() has unwound.
SCAN = {"offenders": {}, "unmerged": []}


def report(truncated):
    """Print every row recorded so far, the detail, and the toll. Returns red.

    Called from the end of main() on a normal run, and from _death_guard on a
    mid-run death -- the only two places control can reach after checks stop.
    """
    # Per-row, not a grep over stdout: a summary trailer carrying the word FAIL
    # is how a whole-stdout assertion goes green on unfixed code.
    print()
    for ok, label, detail in RESULTS:
        print(f"  {'PASS' if ok else 'FAIL'}  {label}" + (f"   [{detail}]" if detail else ""))

    if SCAN["offenders"]:
        print("\nConflict markers in tracked files:")
        for rel, hits in SCAN["offenders"].items():
            for lineno, marker in hits:
                print(f"    {rel}:{lineno}: {marker}")
    if SCAN["unmerged"]:
        print("\nUnmerged index entries (a conflict is IN PROGRESS here):")
        for rel in SCAN["unmerged"]:
            print(f"    UU  {rel}")
        print("\n  Resolve, or `git cherry-pick --abort` / `git merge --abort`.")
        print("  NOTE on this shared tree: --abort also reverts unrelated")
        print("  uncommitted work. Check `git status` for a sibling's edits first.")

    red = sum(1 for ok, _, _ in RESULTS if not ok)
    if truncated:
        print(f"\n!! HARNESS DIED after {len(RESULTS)} of the checks"
              f" -- {red} is a FLOOR, not the count")
    # `or truncated`: a dead run with zero recorded reds used to print the word
    # `ok`. Exit was still 1, so CI was safe -- but the human-readable trailer,
    # and any reader grepping it, saw green on a run that never finished. Found
    # while repairing the line above it, which is the third sighting of this one
    # class in this one file. The trailer keyword is load-bearing; treat it so.
    print(f"\n{'FAILED' if (red or truncated) else 'ok'}: {red} of {len(RESULTS)} red"
          + (" (TRUNCATED)" if truncated else ""))
    return red


def death_run_reports_its_floor(repo):
    """Re-run this file with a death injected after check D; assert the toll.

    A death guard that is never fired is a claim, not a guard. This is the row
    that would have caught the unreachable-trailer defect: against the code as
    merged in #142 the child prints ZERO rows, so every assertion below fails.

    Deliberately asserts the ROWS, not just the trailer -- the trailer alone
    going green is how a summary sentence stands in for the evidence it summarises.
    """
    child = subprocess.run(
        [sys.executable, str(pathlib.Path(__file__).resolve())],
        cwd=repo, capture_output=True, text=True,
        env={**os.environ, INJECT_DEATH: "1"},
    )
    out = child.stdout
    return (
        child.returncode == 1
        and out.count("  PASS  ") + out.count("  FAIL  ") == 4   # A-D ran
        and "HARNESS DIED after 4 of the checks" in out
        and "is a FLOOR, not the count" in out
        and "(TRUNCATED)" in out
        and "\nFAILED: " in out and "\nok: " not in out          # trailer not green
        and "injected mid-run death" in child.stderr             # cause survives
    )


def stamp_partitions_by_what_moves_the_number(repo):
    """Build one scratch repo per class of dirt; assert the stamp separates them.

    Synthetic, not read off `repo` -- a stamp asserted only against whatever
    state this tree happens to be in proves nothing the moment it is cleaned,
    and the live tree carries at most one class at a time anyway.

    Against the code as merged in #143 every case below stamps `-dirty`, so
    rows 2 and 4 fail: untracked-only is marked though it cannot be reached,
    and worktree-modified is indistinguishable from a staged add though only
    one of them moves the count.
    """
    def git(d, *a):
        return subprocess.run(["git", *a], cwd=d, capture_output=True,
                              text=True).stdout.strip()

    def scratch():
        # `--template=` and the gpgsign/hooksPath overrides keep a CI runner's
        # global config out of these repos: an inherited commit hook or signing
        # requirement would fail the commit and red H for a reason that has
        # nothing to do with the stamp.
        d = pathlib.Path(tempfile.mkdtemp(prefix="cmt-stamp-"))
        git(d, "init", "-q", "-b", "main", "--template=")
        git(d, "config", "user.email", "test@local")
        git(d, "config", "user.name", "test")
        git(d, "config", "commit.gpgsign", "false")
        git(d, "config", "core.hooksPath", str(d / ".no-hooks"))
        (d / "a.txt").write_text("a\n")
        git(d, "add", "a.txt")
        git(d, "commit", "-qm", "base")
        if not git(d, "rev-parse", "--verify", "HEAD"):
            raise RuntimeError("scratch repo has no HEAD -- git refused the commit")
        return d

    def suffix(d):
        return head_ref(d).split("+", 1)[1] if "+" in head_ref(d) else ""

    made = []
    try:
        clean = scratch(); made.append(clean)

        untracked = scratch(); made.append(untracked)
        (untracked / "junk.txt").write_text("junk\n")        # ls-files cannot see it

        worktree = scratch(); made.append(worktree)
        (worktree / "a.txt").write_text("a modified\n")      # content moves, count does not

        staged = scratch(); made.append(staged)
        (staged / "b.txt").write_text("b\n")
        git(staged, "add", "b.txt")                          # the count itself moves

        return (
            suffix(clean) == ""
            and suffix(untracked) == ""                      # unreachable => unmarked
            and suffix(worktree) == "content"
            and "list" in suffix(staged)
            and suffix(worktree) != suffix(staged)           # the two are readable apart
        )
    finally:
        for d in made:
            shutil.rmtree(d, ignore_errors=True)


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

    if os.environ.get(INJECT_DEATH):
        raise RuntimeError("injected mid-run death (check G)")

    # --- The live tree ------------------------------------------------------
    offenders = SCAN["offenders"]
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
          f"{len(offenders)} file(s) at {head_ref(repo)}" if offenders else
          f"scanned {len(tracked_files(repo)) - len(unreadable)} text files"
          f" at {head_ref(repo)}")

    unmerged = unmerged_paths(repo)
    SCAN["unmerged"] = unmerged
    check("F  no unresolved merge/cherry-pick in the index",
          not unmerged,
          f"{len(unmerged)} unmerged path(s)" if unmerged else "index clean")

    check("G  a mid-run death still prints the rows it got, floored",
          lambda: death_run_reports_its_floor(repo),
          "re-runs this file with the death injected after check D")

    check("H  the ref stamp separates dirt that moves the count from dirt that cannot",
          lambda: stamp_partitions_by_what_moves_the_number(repo),
          "four scratch repos: clean / untracked / worktree-modified / staged")

    return 1 if (report(truncated=bool(_DIED)) or _DIED) else 0


if __name__ == "__main__":
    sys.exit(main())
