#!/usr/bin/env python3
"""Contract tests for tools/claimable.py — the reader that answers "is this permit spendable?"

The load-bearing one is `test_an_undecided_row_is_never_YES`. Until 2026-08-15 `verdict()`
answered **`YES — <n>s left` on escalations that had never been decided at all**, for the
first `APPROVAL_CLAIM_WINDOW_SECS` after they opened. Three things had to line up, and all
three were shaped like an absence:

  1. `if status and status != "approved"` — an undecided row's status is `""`, so the
     guard's own falsy short-circuit stepped over it.
  2. `if row.get("bar_met") is False` — an undecided row's `bar_met` is `None`, and
     `None is False` is False, so the second guard stepped over the same absence.
  3. `horizon()` fell back `decided_at or opened_at`, manufacturing a grant anchor for a
     grant that was never issued.

The `UNKNOWN — never decided in this window` branch existed the whole time and fired zero
times on 373 rows: two sentinel guards in series let the row past before it could be
reached. Measured on the live chain the day of the fix: **81 of 82 never-decided rows read
YES** when evaluated 60s after they opened. The 82nd had no `_opened` event in the window.

The exposure window is not incidental. It is 600s from OPEN — which is exactly when the
question gets asked, because you ask right after you are refused. This file's job is to
keep the answer affirmative-only: approval must be PRESENT to pass, never merely
un-contradicted.

Run: python3 tools/claimable_test.py   (or via pytest)
"""
import importlib.util
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location("claimable",
                                               os.path.join(_HERE, "claimable.py"))
cl = importlib.util.module_from_spec(_spec)
sys.modules["claimable"] = cl
_spec.loader.exec_module(cl)

T0 = 1_786_800_000
WIN = cl.APPROVAL_CLAIM_WINDOW_SECS


def check(name, cond, detail=""):
    if not cond:
        raise AssertionError(f"{name} — {detail}")


def _opened(**kw):
    """A row carrying only what a `gate_escalation_opened` event supplies."""
    row = {"id": "e" * 16, "opened_at": T0, "expires_at": T0 + 3600,
           "ttl_secs": 3600, "bar": "single_approver"}
    row.update(kw)
    return row


def _approved(decided_at=T0 + 20, **kw):
    row = _opened(status="approved", bar_met=True, decided_at=decided_at)
    row.update(kw)
    return row


def test_an_undecided_row_is_never_YES():
    """The regression. Sample the whole 600s post-open window, not just one point: the
    old bug was a function of elapsed time, so a single sample could sit either side."""
    row = _opened()
    for offset in (0, 1, 60, 300, WIN - 1, WIN, WIN + 1, 3600, 4200):
        v = cl.verdict(row, T0 + offset)
        check("undecided never claims", not v.startswith("YES"),
              f"at +{offset}s the reader said {v!r} about a row with no decision event")
        check("undecided says why", "undecided" in v,
              f"at +{offset}s the verdict {v!r} does not name the missing decision")


def test_an_undecided_row_has_no_horizon():
    """No grant, no grant anchor. `opened_at` is not a substitute for `decided_at`."""
    check("no fabricated horizon", cl.horizon(_opened()) is None,
          f"horizon()={cl.horizon(_opened())} for a row that was never decided")


def test_an_approved_row_still_claims_inside_its_window():
    """Positive control — the tightening must not turn every row into NO. If this passes
    while the regression test also passes on a broken build, the suite proves nothing."""
    row = _approved()
    v = cl.verdict(row, T0 + 20 + WIN - 5)
    check("approved claims", v.startswith("YES"), v)
    check("horizon is grant-anchored", cl.horizon(row) == T0 + 20 + WIN,
          f"horizon()={cl.horizon(row)}, expected grant+{WIN}")


def test_an_approved_row_dies_at_the_grant_anchor_not_the_ttl():
    """The e5c0ff1 semantics this file was written for: 600s from the GRANT, even though
    the open-anchored TTL still has ~58 minutes on it."""
    row = _approved()
    v = cl.verdict(row, T0 + 20 + WIN + 1)
    check("dead past grant horizon", v.startswith("NO — past horizon"), v)
    check("ttl has not expired", T0 + 20 + WIN + 1 < row["expires_at"],
          "the fixture no longer exercises the grant-vs-TTL divergence")


def test_a_denied_row_names_its_status():
    v = cl.verdict(_opened(status="denied", bar_met=False, decided_at=T0 + 20), T0 + 30)
    check("denied is NO", v.startswith("NO — status=denied"), v)


def test_bar_not_met_is_still_reported():
    v = cl.verdict(_opened(status="approved", bar_met=False, decided_at=T0 + 20), T0 + 30)
    check("bar conjunct named", "bar not met" in v, v)


def test_a_withdrawn_event_names_its_status_not_undecided():
    """534ea5a4bff742aa (2026-09-02): the chain carries `gate_escalation_withdrawn`, no
    `_decided`. Before the fold learned the event, this row read `status=undecided`."""
    row = _opened()
    cl.fold_event(row, "gate_escalation_withdrawn",
                  {"decided_via": "self_withdrawn", "bar_met": False}, T0 + 16)
    check("status folded", row.get("status") == "withdrawn", f"row={row}")
    v = cl.verdict(row, T0 + 30)
    check("verdict names withdrawn", v == "NO — status=withdrawn", f"verdict={v!r}")


def test_an_expired_event_names_its_status_not_undecided():
    row = _opened()
    cl.fold_event(row, "gate_escalation_expired", {}, T0 + 3600)
    v = cl.verdict(row, T0 + 3601)
    check("verdict names expired", v == "NO — status=expired", f"verdict={v!r}")


def test_fold_event_is_what_collect_uses_for_decided_rows():
    row = _opened()
    cl.fold_event(row, "gate_escalation_decided", {"status": "approved", "bar_met": True}, T0 + 20)
    cl.fold_event(row, "gate_escalation_claimed", {}, T0 + 40)
    check("decided folded", row.get("decided_at") == T0 + 20 and row.get("status") == "approved", f"row={row}")
    check("claimed folded", row.get("consumed_at") == T0 + 40, f"row={row}")


def test_a_consumed_row_reads_consumed_even_with_no_open_or_decide():
    """The one live row (620407c5) whose `_opened` fell outside the chain window: it is
    known ONLY through its `_claimed` event. Consumed must be checked before status, or
    the status guard relabels it 'undecided' and loses the more specific truth."""
    v = cl.verdict({"id": "x" * 16, "consumed_at": T0 - 5000}, T0)
    check("consumed named", v.startswith("NO — already consumed"), v)


# Listed by name, deliberately, rather than swept out of `globals()`. The sweep worked --
# run bare, this file printed 7 PASS and exited 0 -- but `tools/ci_selfexec_test.py` checks
# for a reference to each `test_*` by walking `ast.Name`, and a `globals()` dispatch is
# invisible to it. So the file was red in CI for a week while being green on every
# assertion it makes, and PR #468 sat unmerged behind that red.
#
# The guard is right to be unconvinced, which is why this is a fix and not a suppression:
# a dispatch a CHECKER cannot see, a REVIEWER cannot see either, and the failure mode it
# is defending against -- a test file that defines assertions and never runs them, then
# reports green -- is the exact shape this corpus keeps finding elsewhere. An explicit
# list costs one line per test and makes "is this test wired up?" answerable by reading.
# Same defect, same remedy as `test_gate_core.py` on PR #171.
TESTS = [
    test_an_undecided_row_is_never_YES,
    test_an_undecided_row_has_no_horizon,
    test_an_approved_row_still_claims_inside_its_window,
    test_an_approved_row_dies_at_the_grant_anchor_not_the_ttl,
    test_a_denied_row_names_its_status,
    test_bar_not_met_is_still_reported,
    test_a_withdrawn_event_names_its_status_not_undecided,
    test_an_expired_event_names_its_status_not_undecided,
    test_fold_event_is_what_collect_uses_for_decided_rows,
    test_a_consumed_row_reads_consumed_even_with_no_open_or_decide,
]


def main():
    tests = TESTS
    defined = {k for k in globals() if k.startswith("test_")}
    listed = {t.__name__ for t in TESTS}
    if defined != listed:
        # The cost of an explicit list is that it can go stale. This makes staleness a
        # RED, not a silently smaller run -- a new test that nobody added here would
        # otherwise never execute, which is the very thing being fixed.
        print(f"FAIL TESTS is stale: defined-not-listed={sorted(defined - listed)} "
              f"listed-not-defined={sorted(listed - defined)}")
        return 1
    failed = []
    for t in tests:
        try:
            t()
            print(f"PASS {t.__name__}")
        except AssertionError as e:
            failed.append((t.__name__, e))
            print(f"FAIL {t.__name__}: {e}")
    print(f"\n{len(tests) - len(failed)}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
