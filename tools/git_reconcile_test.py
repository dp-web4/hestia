#!/usr/bin/env python3
"""Contract tests for tools/git_reconcile.py.

The load-bearing one is `test_the_transplant_count_survives_an_annotation`: the summary
used to count `flag == "TRANSPLANT"` on a string that also carried the PR annotation, so
relabelling a row "TRANSPLANT PR#445" silently dropped it from the count — the summary
UNDERCOUNTED exactly the live open-PR population an operator most needs (GPT audit,
2026-08-14). A count that a *display* change can move is not a count; category and
annotation are separate values now, and this pins that.

Run: python3 tools/git_reconcile_test.py   (or via pytest)
"""
import importlib.util
import os
import sys
from collections import Counter

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("git_reconcile",
                                               os.path.join(_HERE, "git_reconcile.py"))
gr = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(gr)


def check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} — {detail}")


def _rows():
    """The row shape the report builds: (behind, ahead, ref, category, annotation)."""
    return [
        (400, 1, "origin/a", "TRANSPLANT", ""),          # stranded, no PR
        (300, 2, "origin/b", "TRANSPLANT", "PR#445"),    # stranded AND live — the bug's victim
        (250, 1, "origin/c", "RETIRED", "#299"),         # disposition made
        (200, 3, "origin/d", "merged", "#297"),          # squash-merged, branch remains
        (5, 1, "origin/e", "rebase", "PR#443"),
        (0, 3, "origin/f", "mergeable", "PR#439"),
        (-1, -1, "origin/g", "UNFETCHED", ""),
    ]


def test_the_transplant_count_survives_an_annotation():
    rows = _rows()
    tally = Counter(r[3] for r in rows)
    check("counts_both_transplants", tally.get("TRANSPLANT") == 2,
          f"got {tally.get('TRANSPLANT')} — an annotated row was dropped, which is the bug")
    # the old, broken form, kept as the negative control: it must NOT reproduce the right answer
    broken = sum(1 for r in rows if f"{r[3]} {r[4]}".strip() == "TRANSPLANT")
    check("old_form_undercounts", broken == 1,
          "the pre-fix expression should undercount; if it agrees, this test proves nothing")


def test_open_pr_rows_are_countable_separately():
    rows = _rows()
    n_open = sum(1 for r in rows if r[4].startswith("PR#"))
    check("open_pr_rows", n_open == 3, str(n_open))


def test_every_row_carries_a_category_and_an_annotation_field():
    for r in _rows():
        check("row_arity", len(r) == 5, str(r))
        check("category_is_bare", " " not in r[3],
              f"category {r[3]!r} contains a space — annotation has leaked back into it")


def test_in_use_worktree_is_never_reapable():
    """The reaper must not race the work it tidies around: a live process cwd'd inside a
    clean, fully-pushed worktree is a KEEP. Verified against this very process."""
    here = os.getcwd()
    busy = gr.in_use_by(here)
    check("detects_live_process", bool(busy), f"expected a hit for cwd {here}, got {busy!r}")
    check("names_the_holder", "pid" in busy, busy)


def test_ignorance_never_licenses_a_reap():
    """An unreadable /proc yields no evidence of idleness — the guard must KEEP, not reap."""
    real = os.listdir
    try:
        os.listdir = lambda p: (_ for _ in ()).throw(OSError("denied")) if p == "/proc" else real(p)
        out = gr.in_use_by("/tmp")
        check("keeps_on_ignorance", bool(out), f"expected a KEEP reason, got {out!r}")
    finally:
        os.listdir = real


ALL = [
    test_the_transplant_count_survives_an_annotation,
    test_open_pr_rows_are_countable_separately,
    test_every_row_carries_a_category_and_an_annotation_field,
    test_in_use_worktree_is_never_reapable,
    test_ignorance_never_licenses_a_reap,
]

if __name__ == "__main__":
    failed = []
    for t in ALL:
        try:
            t()
            print("PASS", t.__name__)
        except AssertionError as e:
            failed.append(t.__name__)
            print("FAIL", t.__name__, "::", e)
    print()
    if failed:
        print(f"FAILURES: {failed}")
        sys.exit(1)
    print(f"OK — {len(ALL)} tests")
